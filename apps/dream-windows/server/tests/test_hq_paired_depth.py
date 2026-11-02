import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image

import hq_paired_depth as depth
from hq_tryon_conditioning import PipelineError


def test_released_pairs_match_the_real_abc_control_images():
    # These bytes were captured by the ControlNet input hook for the accepted A/B/C runs.
    goldens = {
        'full_single_P001_low': '307d8ebe4a7fae00278b16f1727f808065e6259c4f2298cdf326581697e2db79',
        'full_single_P015_front': 'f9a6db612b04362bf32a94355e8eae0672c807a0071797fcc7d94549b7168ea2',
    }
    import json
    import numpy as np
    pairs = depth.catalog()['items']
    assert set(goldens) <= {pair['id'] for pair in pairs}
    for pair in pairs:
        run = SimpleNamespace(inputs={'pose': {'id': pair['id'], 'sha256': pair['fullSha256']}},
                              audit={'parameters': {'width': 768, 'height': 1152}, 'conditioning': {}},
                              save_image=lambda *args: {})
        with Image.open(depth.ASSETS / (pair['depthSha256'] + '.webp')) as native:
            image = depth.control_image(run, native)
        assert image.size == (768, 1152)
        receipt = run.audit['conditioning']['pose']['receipt']
        assert receipt['sha256'] == pair['depthSha256']
        expected = goldens.get(pair['id'])
        if expected:
            sample = (np.asarray(image).transpose(2, 0, 1).astype('float32') / 255).astype('float16')
            batch = np.stack([sample, sample])
            header = json.dumps({'dtype': 'torch.float16', 'shape': list(batch.shape)}, sort_keys=True).encode()
            assert hashlib.sha256(header + bytes([0]) + batch.tobytes()).hexdigest() == expected
        run.inputs['pose']['sha256'] = '0' * 64
        with pytest.raises(PipelineError, match='版本不一致'):
            depth.control_image(run, image)
    with pytest.raises(PipelineError, match='没有已核验'):
        depth.lookup('unknown')


def test_full_library_checks_white_identity_and_downloads_only_the_selected_blobs(tmp_path, monkeypatch):
    # A separate pinned library can include a pose which used OpenPose before.
    legacy = depth.catalog()['items'][0]
    data = depth.object_path(legacy).read_bytes()
    digest = legacy['depthSha256']
    item = {**legacy, 'id': 'previously_unpaired', 'bytes': len(data),
            'r2Object': f'hq-tryon-assets/dream-depth/v1/objects/{digest}.webp'}
    manifest = {'depthRelease': 'test-depth', 'release': 'test-white', 'poseEstimator': depth.ESTIMATOR, 'items': [item]}
    raw = json.dumps(manifest).encode()
    (tmp_path / 'manifest.json').write_bytes(raw)
    lock = {'manifestSHA256': hashlib.sha256(raw).hexdigest(), 'count': 1, 'depthRelease': 'test-depth', 'whiteRelease': 'test-white'}
    monkeypatch.setattr(depth, 'full_release', lambda: lock)
    config = {'poseEstimator': depth.ESTIMATOR, 'pairedDepthLibrary': str(tmp_path), 'depthReaderNode': 'node', 'depthReaderCli': 'reader'}
    run = SimpleNamespace(inputs={'pose': {'id': item['id'], 'sha256': '0' * 64}}, check_cancel=lambda: None)
    calls = []

    def get(command, **kwargs):
        from pathlib import Path
        assert command[2:7] == ['r2', 'object', 'get', item['r2Object'], '--remote']
        calls.append(command)
        Path(command[command.index('--file') + 1]).write_bytes(data)

    monkeypatch.setattr(depth.subprocess, 'run', get)
    assert depth.pipeline_id(config, item['id']) == depth.PIPELINE
    assert depth.pipeline_id(config, 'future_pose') == depth.LEGACY_PIPELINE
    with pytest.raises(PipelineError, match='版本不一致'):
        depth.ensure_depth(run, config)
    assert not calls
    run.inputs['pose']['sha256'] = item['fullSha256']
    assert depth.ensure_depth(run, config) == 'r2-download'
    assert depth.ensure_depth(run, config) == 'verified-r2-cache'
    assert len(calls) == 1 and depth.object_path(item, config).read_bytes() == data
    (tmp_path / 'manifest.json').write_bytes(raw + b' ')
    with pytest.raises(PipelineError, match='清单'):
        depth.lookup(item['id'], config)
