"""Exercise the real render/collector/history boundary with a CPU model substitute."""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from PIL import Image

from identity_pipeline import IdentitySession
from runtime import DreamRuntime
from test_generation_jobs import make_config
from test_identity_face_polish_engine import request


@pytest.fixture
def render_case(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    generated = Image.linear_gradient('L').resize((256, 256)).convert('RGB')

    class UNet(torch.nn.Module):
        def forward(self, sample, timestep, **kwargs):
            return (sample * .5,)

    class ModelBoundary:
        scheduler = object()
        tokenizer = None

        def __init__(self):
            self.unet = UNet().eval()

        def to(self, device):
            # This external-model substitute always stays on CPU.
            return self

        def __call__(self, **kwargs):
            latent = torch.arange(4 * 32 * 32, dtype=torch.float32).reshape(1, 4, 32, 32) / 4096
            for step in range(kwargs['num_inference_steps']):
                self.unet(torch.cat([latent, latent]), step)
                latent = latent + .1
                kwargs['callback_on_step_end'](self, step, step, {'latents': latent})
            return SimpleNamespace(images=[generated.copy()])

    # Reuse the existing render-test pattern: bypass heavyweight model loading,
    # keeping render, the research collector and all persistence code untouched.
    session = IdentitySession.__new__(IdentitySession)
    session.config, session.pipe, session.projected = {}, ModelBoundary(), None
    session.initial_stages, session.hashes, session.started = [], {}, time.perf_counter()
    session.feature_info = {'cacheHit': True, 'featureKey': 'synthetic-cpu-fixture'}
    monkeypatch.setattr(torch.cuda, 'max_memory_allocated', lambda: 0)
    monkeypatch.setattr(torch.cuda, 'max_memory_reserved', lambda: 0)
    job_id = 'identity-' + 'a' * 24
    item = request(config.dream_root, referenceId='ref-' + 'b' * 24, prompt='portrait', seed=7,
                   width=256, height=256, steps=2, traceLevel='basic',
                   outputPath=str(config.dream_root / 'outputs' / f'{job_id}.png'),
                   metadataPath=str(config.dream_root / 'outputs' / f'{job_id}.json'))
    trace = config.dream_root / 'traces' / f'{job_id}.json'
    return config, session, item, generated, trace


def assert_published_image_and_history(case, result):
    config, _, item, generated, _ = case
    with Image.open(item['outputPath']) as saved:
        assert saved.size == generated.size
        assert saved.tobytes() == generated.tobytes()
    metadata = json.loads(Path(item['metadataPath']).read_text(encoding='utf-8'))
    assert result['metadata'] == metadata
    assert result['jobId'] == item['jobId']
    assert result['imageUrl'] == f"/api/history/{item['jobId']}/image"
    runtime = DreamRuntime(config)
    assert runtime.history({})['items'][0]['id'] == item['jobId']
    assert runtime.history_image(item['jobId']) == Path(item['outputPath'])
    assert metadata['facePolish'] == {'enabled': False, 'status': 'disabled'}
    return metadata


@pytest.mark.parametrize('trace_level', ['basic', 'h6'])
@pytest.mark.parametrize(('error_type', 'errno'), [(PermissionError, 13), (OSError, 28)],
                         ids=['locked-trace', 'trace-disk-full'])
def test_trace_publication_failure_preserves_normal_render_and_history(render_case, monkeypatch, trace_level, error_type, errno):
    _, session, item, _, trace = render_case
    item['traceLevel'] = trace_level
    replace = os.replace

    def fail_trace_publication(source, destination):
        if Path(destination) == trace:
            raise error_type(errno, 'private-path-marker')
        return replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_trace_publication)
    result = session.render(item, 0, [].append, None, 0)
    metadata = assert_published_image_and_history(render_case, result)
    research = metadata['research']
    assert research['status'] == 'failed'
    assert research['error']['code'] == 'IDENTITY_RESEARCH_PUBLICATION_FAILED'
    assert research['message']
    assert research['traceLevel'] == trace_level
    assert research['coverage'] == 'representative'
    assert research['h6'] is False and research['h7'] is False
    assert research.get('runId') is None
    assert research.get('latentSteps', 0) == 0
    assert 'private-path-marker' not in json.dumps(result)
    assert not trace.exists()
    assert all(not module._forward_hooks and not module._forward_pre_hooks for module in session.pipe.unet.modules())


@pytest.mark.parametrize('trace_level', ['off', 'basic', 'h6'])
def test_successful_render_keeps_existing_research_contract(render_case, trace_level):
    _, session, item, _, trace = render_case
    item['traceLevel'] = trace_level
    result = session.render(item, 0, [].append, None, 0)
    research = assert_published_image_and_history(render_case, result)['research']
    assert 'error' not in research
    if trace_level == 'off':
        assert research['h6'] is False and research['h7'] is False
        assert 'runId' not in research and not trace.exists()
    else:
        assert research['runId'] == item['jobId'] and trace.exists()
        assert research['latentSteps'] == 2
        assert research['h6'] is (trace_level == 'h6')


@pytest.mark.parametrize('target', ['outputPath', 'metadataPath'])
def test_generation_storage_failure_is_not_misreported_as_research_failure(render_case, monkeypatch, target):
    _, session, item, _, _ = render_case
    replace = os.replace

    def fail_generation_publication(source, destination):
        if Path(destination) == Path(item[target]):
            raise PermissionError('generation storage unavailable')
        return replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_generation_publication)
    with pytest.raises(PermissionError, match='generation storage unavailable'):
        session.render(item, 0, [].append, None, 0)
    assert not Path(item['metadataPath']).exists()


def test_trace_publication_does_not_swallow_process_interruption(render_case, monkeypatch):
    _, session, item, _, trace = render_case
    replace = os.replace

    def interrupt(source, destination):
        if Path(destination) == trace:
            raise KeyboardInterrupt('controlled process interruption')
        return replace(source, destination)

    monkeypatch.setattr(os, 'replace', interrupt)
    with pytest.raises(KeyboardInterrupt, match='controlled process interruption'):
        session.render(item, 0, [].append, None, 0)
    assert not Path(item['metadataPath']).exists()
