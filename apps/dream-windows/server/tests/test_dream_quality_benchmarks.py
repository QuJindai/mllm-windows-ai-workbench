"""Exercise real files, hash drift, provenance and missing timing evidence."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


SCRIPTS = Path(__file__).resolve().parents[4] / 'scripts'


def module(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


def dataset(tmp_path):
    Image.new('RGB', (8, 8), (30, 40, 50)).save(tmp_path / 'before.png')
    Image.new('RGB', (8, 8), (35, 45, 55)).save(tmp_path / 'after.png')
    Image.new('L', (8, 8), 0).save(tmp_path / 'edit.png')
    settings = {'modelId': 'synthetic-only', 'prompt': '测试', 'steps': 2, 'cfg': 1,
                'negativePrompt': '', 'width': 8, 'height': 8, 'custom': {'keep': True}}
    source = {'kind': 'synthetic-test', 'reference': 'hand-authored-flat-colours'}
    spec = {'schemaVersion': 1, 'datasetId': 'tiny', 'cases': [{
        'id': 'face', 'route': 'synthetic',
        'baseline': {'path': 'before.png', 'seed': 7, 'settings': settings, 'source': source},
        'variants': [{'id': 'polish', 'path': 'after.png', 'seed': 8,
                      'settings': settings, 'source': source}],
        'masks': {'edit': {'path': 'edit.png'}}}]}
    return spec


def locked(tmp_path):
    return module('benchmark_dream_quality').freeze_manifest(dataset(tmp_path), base_dir=tmp_path)


def test_manifest_retains_all_settings_source_seeds_and_detects_replaced_image(tmp_path):
    quality = module('benchmark_dream_quality')
    spec = dataset(tmp_path)
    original = copy.deepcopy(spec)
    manifest = quality.freeze_manifest(spec, base_dir=tmp_path)
    assert spec == original
    variant = manifest['cases'][0]['variants'][0]
    assert variant['seed'] == 8
    assert variant['settings'] == original['cases'][0]['variants'][0]['settings']
    assert variant['source'] == original['cases'][0]['variants'][0]['source']
    assert len(variant['sha256']) == 64
    assert Path(variant['path']).is_absolute()
    first = quality.evaluate_manifest(manifest)
    assert first == quality.evaluate_manifest(manifest)
    assert first['cases'][0]['variants'][0]['diagnostics']['retention']['outsideEdit']['changedPixels'] == 64
    Image.new('RGB', (8, 8), 'red').save(tmp_path / 'after.png')
    with pytest.raises(ValueError, match='sha256'):
        quality.evaluate_manifest(manifest)


@pytest.mark.parametrize('mutation', ['seed', 'source', 'settings', 'duplicate'])
def test_reproducibility_manifest_rejects_missing_provenance_and_duplicate_ids(tmp_path, mutation):
    quality = module('benchmark_dream_quality')
    spec = dataset(tmp_path)
    if mutation == 'duplicate':
        spec['cases'].append(copy.deepcopy(spec['cases'][0]))
    else:
        del spec['cases'][0]['variants'][0][mutation]
    with pytest.raises(ValueError):
        quality.freeze_manifest(spec, base_dir=tmp_path)


def test_quality_cli_freezes_and_evaluates_files_without_overwriting_existing_output(tmp_path):
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps(dataset(tmp_path)), encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    report = tmp_path / 'report.json'
    script = SCRIPTS / 'benchmark_dream_quality.py'
    for args in [('freeze', spec, manifest), ('evaluate', manifest, report)]:
        result = subprocess.run([sys.executable, str(script), str(args[0]), str(args[1]),
                                 '--output', str(args[2])], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text(encoding='utf-8'))['cases'][0]['route'] == 'synthetic'
    before = report.read_bytes()
    result = subprocess.run([sys.executable, str(script), 'evaluate', str(manifest),
                             '--output', str(report)], capture_output=True)
    assert result.returncode != 0
    assert report.read_bytes() == before


def receipt(manifest, run_id='r1', temperature='cold'):
    return {'runId': run_id, 'caseId': 'face', 'variantId': 'polish', 'temperature': temperature,
            'manifestSha256': module('benchmark_dream_quality').canonical_hash(manifest),
            'temperatureEvidence': 'operator observed a newly created worker' if temperature == 'cold'
            else 'same worker and same pipeline reused',
            'sessionId': 'worker-1', 'outcome': 'complete', 'wallMs': 1000,
            'phasesMs': {'load': 300, 'samplingDecode': 500, 'facePolish': None},
            'environment': {'device': 'cpu-synthetic', 'runtime': 'unit-test'},
            'uncontended': True, 'source': {'kind': 'synthetic-test'}}


def test_performance_separates_cold_warm_and_leaves_missing_phases_unknown(tmp_path):
    performance = module('benchmark_dream_performance')
    manifest = locked(tmp_path)
    cold, warm = receipt(manifest), receipt(manifest, 'r2', 'warm')
    warm['wallMs'] = 600
    warm['phasesMs'] = {'load': 0, 'samplingDecode': 450, 'facePolish': 100}
    result = performance.summarize_runs(manifest, [cold, warm])
    groups = {g['temperature']: g for g in result['groups']}
    assert groups['cold']['wallMs']['median'] == 1000
    assert groups['warm']['wallMs']['median'] == 600
    assert groups['cold']['phasesMs']['facePolish']['count'] == 0
    assert groups['cold']['phasesMs']['facePolish']['median'] is None
    assert groups['warm']['phasesMs']['load']['median'] == 0
    assert result['runs'][0]['timingCoverage']['unattributedMs'] is None
    assert result['runs'][1]['timingCoverage']['unattributedMs'] == 50
    assert result['runs'][0]['provenance']['seed'] == 8
    assert result['runs'][0]['source'] == cold['source']
    json.dumps(result, allow_nan=False)


def test_failed_or_contended_runs_remain_visible_but_do_not_skew_success_summary(tmp_path):
    performance = module('benchmark_dream_performance')
    manifest = locked(tmp_path)
    good, failed, busy = receipt(manifest), receipt(manifest, 'fail'), receipt(manifest, 'busy')
    failed.update(outcome='failed', wallMs=10)
    failed['phasesMs'] = {}
    busy.update(uncontended=False, wallMs=50000)
    result = performance.summarize_runs(manifest, [good, failed, busy])
    assert len(result['runs']) == 3
    assert result['groups'][0]['wallMs']['count'] == 1
    assert result['groups'][0]['wallMs']['median'] == 1000
    assert len(result['excludedRuns']) == 2


@pytest.mark.parametrize('mutation', ['negative', 'nonfinite', 'overlap', 'unknown', 'temperature', 'duplicate', 'manifest'])
def test_performance_rejects_invalid_or_unbound_measurements(tmp_path, mutation):
    performance = module('benchmark_dream_performance')
    manifest = locked(tmp_path)
    row = receipt(manifest)
    rows = [row]
    if mutation == 'negative': row['wallMs'] = -1
    if mutation == 'nonfinite': row['wallMs'] = float('nan')
    if mutation == 'overlap': row['phasesMs']['facePolish'] = 900
    if mutation == 'unknown': row['variantId'] = 'missing'
    if mutation == 'temperature': del row['temperatureEvidence']
    if mutation == 'duplicate': rows.append(copy.deepcopy(row))
    if mutation == 'manifest': row['manifestSha256'] = '0' * 64
    with pytest.raises(ValueError):
        performance.summarize_runs(manifest, rows)


def test_performance_cli_groups_different_devices_separately_and_preserves_source(tmp_path):
    quality, performance = module('benchmark_dream_quality'), module('benchmark_dream_performance')
    manifest = locked(tmp_path)
    one, two = receipt(manifest), receipt(manifest, 'other-device')
    two['environment']['device'] = 'another-cpu'
    rows = [one, two]
    expected = performance.summarize_runs(manifest, rows)
    assert len(expected['groups']) == 2
    manifest_path, receipts_path = tmp_path / 'manifest.json', tmp_path / 'receipts.json'
    quality.write_new_json(manifest_path, manifest)
    quality.write_new_json(receipts_path, rows)
    output = tmp_path / 'performance.json'
    result = subprocess.run([sys.executable, str(SCRIPTS / 'benchmark_dream_performance.py'),
                             str(manifest_path), str(receipts_path), '--output', str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    actual = json.loads(output.read_text(encoding='utf-8'))
    assert actual == expected
    assert actual['runs'][0]['source'] == {'kind': 'synthetic-test'}
