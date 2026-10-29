import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from errors import DreamApiError
from identity_contract import IdentityGenerateRequest
from job_runner import JobRunner
from runtime import DreamRuntime
from test_generation_jobs import make_config


def test_identity_history_keeps_friendly_model_name_without_native_registration(tmp_path):
    config = make_config(tmp_path)
    output = config.dream_root / 'outputs'
    output.mkdir()
    image = output / 'identity-test.png'
    image.write_bytes(b'PNG')
    (output / 'identity-test.json').write_text(json.dumps({
        'id': 'identity-test', 'model_id': 'realistic-vision-v5.1-faceid',
        'model_name': 'Realistic Vision V5.1 · FaceID Plus V2', 'output': str(image)}), encoding='utf-8')
    item = DreamRuntime(config, job_runner=JobRunner(config)).history({'page': 1, 'page_size': 10, 'filter': 'all', 'query': ''})['items'][0]
    assert item['modelId'] == 'realistic-vision-v5.1-faceid'
    assert item['modelName'] == 'Realistic Vision V5.1 · FaceID Plus V2'


IDENTITY_ID = 'identity-' + 'a' * 24


def history_case(tmp_path, item_id=IDENTITY_ID, with_original=True):
    config = make_config(tmp_path)
    folder = config.dream_root / 'outputs' / '2026-09-20'
    folder.mkdir(parents=True)
    output, metadata = (folder / (item_id + suffix) for suffix in ('.png', '.json'))
    Image.new('RGB', (256, 256), 'navy').save(output)
    metadata.write_text(json.dumps({'id': item_id, 'model_id': 'realistic-vision-v5.1-faceid',
                                    'output': str(output)}), encoding='utf-8')
    original = config.dream_root / 'data' / 'identity' / 'originals' / (item_id + '.png')
    if with_original:
        original.parent.mkdir(parents=True)
        Image.new('RGB', (256, 256), 'red').save(original)
    return config, DreamRuntime(config, job_runner=JobRunner(config)), output, metadata, original


def test_delete_identity_history_removes_original_and_revokes_registered_download(tmp_path):
    config, runtime, output, metadata, original = history_case(tmp_path)
    neighbor = original.with_name('identity-' + 'b' * 24 + '.png')
    neighbor.write_bytes(b'unrelated original')
    request = IdentityGenerateRequest(referenceId='ref-' + 'c' * 24, faceIndex=0,
                                      prompt='portrait', width=256, height=256, facePolish=True).model_dump()
    value = json.loads(metadata.read_text(encoding='utf-8'))
    value['facePolish'] = {'enabled': True, 'status': 'completed',
                           'originalImageUrl': f'/api/identity/jobs/{IDENTITY_ID}/original'}
    # Saved path hints must not choose which original gets removed.
    value['originalPath'] = str(neighbor)
    metadata.write_text(json.dumps(value), encoding='utf-8')
    job_path = config.dream_root / 'data' / 'identity' / 'jobs' / (IDENTITY_ID + '.json')
    job_path.parent.mkdir()
    job_path.write_text(json.dumps({'id': IDENTITY_ID, 'state': 'complete', 'progress': 100,
                                   'message': '生成完成', 'error': None, 'request': request,
                                   'result': {'imageUrl': f'/api/history/{IDENTITY_ID}/image', 'metadata': value}}), encoding='utf-8')
    with TestClient(create_app(config, runtime), base_url='http://127.0.0.1:8866') as client:
        url = f'/api/identity/jobs/{IDENTITY_ID}/original'
        assert client.get(url).status_code == 200
        response = client.delete(f'/api/history/{IDENTITY_ID}')
        assert response.status_code == 200
        assert response.json() == {'deleted': IDENTITY_ID, 'truth': 'observed'}
        assert not original.exists()
        assert not output.exists() and not metadata.exists()
        assert client.get(url).status_code == 404
    assert neighbor.read_bytes() == b'unrelated original'
    assert job_path.exists()


@pytest.mark.parametrize('item_id', [IDENTITY_ID, 'sdxl-image', 'identity-test', 'identity-' + 'a' * 23])
def test_history_delete_without_repair_preserves_other_originals(tmp_path, item_id):
    config, runtime, output, metadata, original = history_case(tmp_path, item_id, with_original=False)
    other = config.dream_root / 'data' / 'identity' / 'originals' / ('identity-' + 'b' * 24 + '.png')
    other.parent.mkdir(parents=True)
    other.write_bytes(b'keep')
    if item_id != IDENTITY_ID:
        original.write_bytes(b'not a canonical identity original')
    assert runtime.delete_history(item_id) == {'deleted': item_id, 'truth': 'observed'}
    assert not output.exists() and not metadata.exists()
    assert other.read_bytes() == b'keep'
    if item_id != IDENTITY_ID:
        assert original.read_bytes() == b'not a canonical identity original'


@pytest.mark.parametrize('outside', [True, False], ids=['outside-root', 'inside-root'])
@pytest.mark.parametrize('redirect', ['original', 'originals', 'identity', 'data', 'output', 'metadata'])
def test_identity_history_delete_rejects_redirects_before_deleting_anything(tmp_path, outside, redirect):
    config, runtime, output, metadata, original = history_case(tmp_path)
    paths = {'original': original, 'originals': original.parent, 'identity': original.parent.parent,
             'data': config.dream_root / 'data', 'output': output, 'metadata': metadata}
    link = paths[redirect]
    saved = {path: path.read_bytes() for path in (original, output, metadata)}
    destination = (tmp_path if outside else config.dream_root) / 'redirected' / link.name
    destination.parent.mkdir(parents=True)
    is_directory = link.is_dir()
    link.rename(destination)
    try:
        link.symlink_to(destination, target_is_directory=is_directory)
    except OSError as exc:
        destination.rename(link)
        pytest.skip(f'Symlinks unavailable: {exc}')
    with pytest.raises(DreamApiError) as error:
        runtime.delete_history(IDENTITY_ID)
    assert error.value.code == 'HISTORY_DELETE_PATH_INVALID'
    for path, content in saved.items():
        assert path.read_bytes() == content
    assert destination.exists()


def test_identity_history_delete_rejects_dangling_original_symlink(tmp_path):
    _, runtime, output, metadata, original = history_case(tmp_path)
    original.unlink()
    try:
        original.symlink_to(tmp_path / 'missing-private.png')
    except OSError as exc:
        pytest.skip(f'Symlinks unavailable: {exc}')
    with pytest.raises(DreamApiError) as error:
        runtime.delete_history(IDENTITY_ID)
    assert error.value.code == 'HISTORY_DELETE_PATH_INVALID'
    assert output.exists() and metadata.exists() and original.is_symlink()


def test_original_delete_failure_returns_api_error_and_preserves_history_for_retry(tmp_path, monkeypatch):
    config, runtime, output, metadata, original = history_case(tmp_path)
    saved = {path: path.read_bytes() for path in (original, output, metadata)}
    rename = Path.rename

    def permission_denied(path, *args, **kwargs):
        if path == original:
            raise PermissionError('controlled locked original')
        return rename(path, *args, **kwargs)

    with TestClient(create_app(config, runtime), base_url='http://127.0.0.1:8866') as client:
        with monkeypatch.context() as locked:
            locked.setattr(Path, 'rename', permission_denied)
            response = client.delete(f'/api/history/{IDENTITY_ID}')
            assert response.status_code == 503
            assert response.json()['code'] == 'HISTORY_ORIGINAL_DELETE_FAILED'
            assert response.json()['retryable'] is True
            assert 'deleted' not in response.json()
            assert str(config.dream_root) not in response.text
            for path, content in saved.items():
                assert path.read_bytes() == content
        assert client.delete(f'/api/history/{IDENTITY_ID}').status_code == 200
    assert all(not path.exists() for path in saved)
