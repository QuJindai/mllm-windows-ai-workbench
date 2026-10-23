import hashlib
import json
import os
from pathlib import Path

import pytest


def test_fingerprint_reuses_verified_bytes_and_invalidates_change(tmp_path, monkeypatch):
    from identity_features import FingerprintCache
    weight = tmp_path / 'weight.bin'
    weight.write_bytes(b'first')
    cache = FingerprintCache(tmp_path / 'fingerprints.json')
    assert cache.digest(weight) == hashlib.sha256(b'first').hexdigest()
    original = Path.open
    def no_weight_read(path, *args, **kwargs):
        if path == weight and (args[0] if args else kwargs.get('mode')) == 'rb':
            pytest.fail('unchanged weight was re-read')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path, 'open', no_weight_read)
        assert FingerprintCache(tmp_path / 'fingerprints.json').digest(weight) == hashlib.sha256(b'first').hexdigest()
    weight.write_bytes(b'second-longer')
    assert cache.digest(weight) == hashlib.sha256(b'second-longer').hexdigest()


def test_feature_identity_independent_from_generator_settings():
    from identity_features import feature_key
    hashes = {'clipVision': 'clip', 'det_10g.onnx': 'detect', 'w600k_r50.onnx': 'recognize', 'checkpoint': 'a'}
    first = feature_key('photo', 0, hashes)
    assert feature_key('photo', 0, {**hashes, 'checkpoint': 'b'}) == first
    assert feature_key('photo', 1, hashes) != first
    assert feature_key('newphoto', 0, hashes) != first
    assert feature_key('photo', 0, {**hashes, 'clipVision': 'new'}) != first


def test_forced_fingerprint_checks_even_unchanged_file_attributes(tmp_path):
    from identity_features import FingerprintCache
    path = tmp_path / 'weight'
    path.write_bytes(b'old')
    cache = FingerprintCache(tmp_path / 'index.json')
    old = cache.digest(path)
    before = path.stat()
    path.write_bytes(b'new')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert cache.digest(path, force=True) == hashlib.sha256(b'new').hexdigest() != old


def make_item(tmp_path, index, **changes):
    return {'referenceId': 'ref-' + 'a' * 24, 'faceIndex': 0, 'prompt': 'portrait', 'seed': 42 + index,
            'jobId': 'identity-' + f'{index:024x}', 'imagePath': str(tmp_path / 'ref.png'),
            'outputPath': str(tmp_path / f'{index}.png'), 'metadataPath': str(tmp_path / f'{index}.json'),
            'dreamRoot': str(tmp_path), 'steps': 20 + index * 8, **changes}


def test_real_batch_loop_loads_session_once_and_persists_each_before_event(tmp_path, monkeypatch):
    import identity_pipeline
    from identity_events import read_events
    instances = []
    class Session:
        def __init__(self, config, first, emit):
            instances.append(self)
        def render(self, item, item_index, emit, preview_dir, preview_every):
            emit({'type': 'step', 'itemIndex': item_index, 'step': 1, 'totalSteps': item['steps'], 'elapsedMs': 1})
            Path(item['outputPath']).write_bytes(b'completed image')
            Path(item['metadataPath']).write_text(json.dumps({'seed': item['seed']}))
            return {'jobId': item['jobId'], 'imageUrl': '/image', 'metadata': {'seed': item['seed']}}
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', Session)
    result = identity_pipeline.generate_batch({}, {'items': [make_item(tmp_path, 0), make_item(tmp_path, 1)], 'eventPath': str(tmp_path / 'events.ndjson'), 'previewDir': str(tmp_path / 'previews'), 'previewEvery': 0})
    assert len(instances) == 1
    assert [item['metadata']['seed'] for item in result['items']] == [42, 43]
    events, _ = read_events(tmp_path / 'events.ndjson')
    assert [e['itemIndex'] for e in events if e['type'] == 'item_complete'] == [0, 1]
    assert (tmp_path / '0.png').exists() and (tmp_path / '1.json').exists()


def test_mixed_people_batch_rejected_before_loading(tmp_path, monkeypatch):
    import identity_pipeline
    def forbidden(*args, **kwargs):
        pytest.fail('model loaded before validating compatible batch')
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', forbidden)
    with pytest.raises(ValueError, match='同一'):
        identity_pipeline.generate_batch({}, {'items': [make_item(tmp_path, 0), make_item(tmp_path, 1, faceIndex=1)]})


def test_callback_reports_real_steps_and_preview_off_does_not_decode(tmp_path):
    from identity_pipeline import sampling_callback
    events = []
    class Pipe:
        @property
        def vae(self):
            pytest.fail('preview disabled must not access VAE')
    callback = sampling_callback('identity-' + 'a' * 24, 0, 28, events.append, tmp_path, 0, 0)
    data = {'latents': object()}
    assert callback(Pipe(), 11, 123, data) is data
    assert events[-1]['step'] == 12 and events[-1]['totalSteps'] == 28
    assert 'previewFile' not in events[-1]


def test_preview_interval_and_failure_do_not_change_latents(tmp_path, monkeypatch):
    import identity_pipeline
    from PIL import Image
    events, decoded = [], []
    def decode(pipe, latents, destination):
        decoded.append(destination.name)
        Image.new('RGB', (10, 10), 'blue').save(destination)
    monkeypatch.setattr(identity_pipeline, 'save_preview', decode)
    callback = identity_pipeline.sampling_callback('identity-' + 'a' * 24, 1, 8, events.append, tmp_path, 5, 0)
    values = {'latents': object()}
    for step in range(8):
        assert callback(object(), step, 100-step, values) is values
    assert decoded == ['identity-'+'a'*24+'-step-005.png', 'identity-'+'a'*24+'-step-008.png']
    assert [e['step'] for e in events if e['type'] == 'step'] == list(range(1,9))
    def broken(*args):
        raise RuntimeError('optional preview failure')
    monkeypatch.setattr(identity_pipeline, 'save_preview', broken)
    assert callback(object(), 4, 12, values) is values
    assert any(e['type'] == 'preview_error' for e in events)
    assert events[-1]['type'] == 'step' and 'previewFile' not in events[-1]


def test_batch_elapsed_does_not_reset_when_second_item_starts(tmp_path, monkeypatch):
    import identity_pipeline
    from identity_events import read_events
    clock = iter([10.0, 20.0, 30.0, 40.0, 50.0])
    monkeypatch.setattr(identity_pipeline.time, 'perf_counter', lambda: next(clock))
    class Session:
        def __init__(self, *args):
            pass
        def render(self, item, index, emit, *args):
            emit({'type': 'step', 'itemIndex': index, 'elapsedMs': 1})
            Path(item['outputPath']).write_bytes(b'image')
            Path(item['metadataPath']).write_text('{}')
            return {'jobId': item['jobId']}
    monkeypatch.setattr(identity_pipeline, 'IdentitySession', Session)
    path = tmp_path / 'events.ndjson'
    identity_pipeline.generate_batch({}, {'items':[make_item(tmp_path, 0),make_item(tmp_path, 1)], 'eventPath':str(path)})
    events, _ = read_events(path)
    assert [e['elapsedMs'] for e in events] == [10000,20000,30000,40000]


def test_preview_capture_preserves_scheduler_result_signature_and_restores_on_error():
    import inspect
    from identity_pipeline import capture_denoised_preview
    predicted, previous = object(), object()
    result = (previous, predicted)
    class Scheduler:
        def step(self, model_output, timestep, sample, generator=None, return_dict=True):
            assert generator == 'rng'
            return result
    scheduler = Scheduler()
    original = scheduler.step
    with pytest.raises(RuntimeError, match='stop'):
        with capture_denoised_preview(scheduler, True) as state:
            assert inspect.signature(scheduler.step) == inspect.signature(original)
            assert scheduler.step(None, None, None, generator='rng', return_dict=False) is result
            assert state['latents'] is predicted
            raise RuntimeError('stop')
    assert scheduler.step == original
    assert state == {}


def test_preview_callback_decodes_actual_denoised_estimate_without_changing_latents(tmp_path, monkeypatch):
    import identity_pipeline
    predicted, raw = object(), object()
    decoded = []
    monkeypatch.setattr(identity_pipeline, 'save_preview', lambda pipe, value, path: decoded.append(value))
    events = []
    callback = identity_pipeline.sampling_callback('identity-'+'a'*24, 0, 20, events.append, tmp_path, 5, 0, {'latents': predicted})
    values = {'latents': raw}
    assert callback(object(), 4, 15, values) is values
    assert values['latents'] is raw
    assert decoded == [predicted]
    assert events[-1]['previewSource'] == 'predicted_original_sample'


@pytest.mark.parametrize('corruption', ['truncated', 'nan'])
def test_invalid_feature_cache_is_quarantined_and_rebuilt(tmp_path, corruption):
    import torch
    from safetensors.torch import save_file
    from identity_features import reference_features
    assets = tmp_path / 'assets'
    (assets / 'models' / 'buffalo_l').mkdir(parents=True)
    for name in ('det_10g.onnx', 'w600k_r50.onnx'):
        (assets / 'models' / 'buffalo_l' / name).write_bytes(name.encode())
    (assets / 'clip').write_bytes(b'clip')
    (assets / 'photo').write_bytes(b'photo')
    config = {'clipVision': str(assets / 'clip'), 'insightfaceRoot': str(assets)}
    request = {'dreamRoot': str(tmp_path), 'imagePath': str(assets / 'photo'), 'faceIndex': 0}
    calls = []
    def extract(*args):
        calls.append(args)
        return {'id': torch.zeros(1, 512), 'clip': torch.zeros(1, 257, 1280), 'negative_clip': torch.zeros(1, 257, 1280)}
    features, original = reference_features(config, request, extract)
    path = tmp_path / 'cache' / 'identity' / (original['featureKey'] + '.safetensors')
    if corruption == 'truncated':
        path.write_bytes(b'broken')
    else:
        features['id'][0, 0] = float('nan')
        save_file(features, str(path))
    recovered, info = reference_features(config, request, extract)
    assert len(calls) == 2 and not info['cacheHit']
    assert info['featureKey'] == original['featureKey']
    assert torch.isfinite(recovered['id']).all()
    assert len(list(path.parent.glob('*.corrupt-*'))) == 1
    _, warm = reference_features(config, request, extract)
    assert warm['cacheHit'] and len(calls) == 2
