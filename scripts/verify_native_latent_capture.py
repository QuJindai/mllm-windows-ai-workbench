"""Validate a real completed GUI/native run, not mock trace fixtures."""
from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
from urllib.request import urlopen

from PIL import Image


def verify(base_url: str, run_id: str, expected_steps: int) -> dict:
    def read_json(route: str) -> dict:
        with urlopen(base_url + route, timeout=30) as response:
            return json.load(response)

    trace = read_json(f'/api/traces/{run_id}')
    latent = read_json(f'/api/traces/{run_id}/latent')
    assert trace['available'] and latent['kind'] == 'latent-state', 'Raw latent telemetry missing'
    samples = latent['telemetry']
    assert len(samples) == expected_steps, f'Expected {expected_steps} states, got {len(samples)}'
    assert [s['step'] for s in samples] == list(range(expected_steps)), 'Sampling states are missing or duplicated'
    raw_path = Path(trace['evidence']['outputPath']).parents[2] / 'traces' / run_id / 'latent-metrics.jsonl'
    native_samples = [json.loads(line) for line in raw_path.read_text(encoding='utf-8-sig').splitlines() if line]
    assert len(native_samples) == expected_steps
    channel_count = 0
    for sample, native in zip(samples, native_samples):
        assert sample['truth'] == 'observed' and sample['shape'][2:] == [4, 1]
        assert len(sample['channels']) == 4
        for key in ('mean', 'std', 'l2'):
            assert math.isfinite(sample[key]) and sample[key] == native[key]
        for api_key, native_key in (('deltaL2', 'delta_l2'), ('deltaMeanAbs', 'delta_mean_abs'), ('cosine', 'cosine')):
            assert sample[api_key] == native[native_key], f'{api_key} changed between native capture and browser API'
        for channel in sample['channels']:
            assert sum(channel['histogram']) == sample['shape'][0] * sample['shape'][1]
            with urlopen(base_url + channel['imageUrl'], timeout=30) as response:
                with Image.open(io.BytesIO(response.read())) as image:
                    image.load()
                    assert image.size == tuple(sample['shape'][:2])
            channel_count += 1
    output = Path(trace['evidence']['outputPath'])
    with Image.open(output) as image:
        image.load()
        resolution = list(image.size)
        assert image.width >= 768 and image.height >= 768, 'Acceptance requires native SDXL-size output'
    return {'passed': True, 'runId': run_id, 'output': str(output), 'resolution': resolution,
            'steps': len(samples), 'rawChannelImages': channel_count,
            'projectionFrames': len(latent['frames']), 'metricsRoundTrip': 'exact',
            'totalTimeMs': trace['totalTimeMs'], 'evidence': trace['evidence']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--base-url', default='http://127.0.0.1:8866')
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args.base_url.rstrip('/'), args.run_id, args.steps)
    formatted = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(formatted, encoding='utf-8')
    print(formatted)
