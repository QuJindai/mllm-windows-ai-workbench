import hashlib
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
