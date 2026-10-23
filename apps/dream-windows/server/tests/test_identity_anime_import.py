"""External anime portraits use the real archive route, queue and persistence."""
import base64
import hashlib
import io
import json
import random

import pytest
from PIL import Image

from test_identity_api import harness, image_base64, upload, submit, finished
from test_identity_profiles import profile_harness, create_profile, wait_profile
from test_identity_anime_profiles import anime_harness, create_anime, source_pair, wait_anime


def import_body(parent, **changes):
    return {'name': 'Example-动漫-GPT', 'profileId': parent['id'], 'sourceName': 'Example-04.png',
            'sourceLabel': 'GPT', 'imageBase64': image_base64((160, 160)), **changes}


def test_import_owns_image_and_real_features_without_fabricating_job(anime_harness):
    client, config, runner, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    parent_path = config.dream_root/'data/identity/profiles'/f"{parent['id']}.json"
    before = parent_path.read_bytes()
    jobs_before = client.get('/api/identity/jobs').json()
    # Valid upload larger than the ordinary JSON route limit must still work.
    stream = io.BytesIO()
    Image.frombytes('RGB', (256, 256), random.Random(42).randbytes(256*256*3)).save(stream, 'PNG')
    response = client.post('/api/identity/anime-profiles/import', json=import_body(
        parent, imageBase64=base64.b64encode(stream.getvalue()).decode('ascii')))
    assert response.status_code == 200, response.text
    anime = wait_anime(client, response.json()['id'])
    assert anime['state'] == 'ready', anime
    assert anime['sourceKind'] == 'upload' and anime['sourceJobId'] is None
    assert anime['sourceLabel'] == 'GPT' and anime['sourceName'] == 'Example-04.png'
    image_response = client.get(anime['imageUrl'])
    assert image_response.status_code == 200
    assert hashlib.sha256(image_response.content).hexdigest() == anime['sourceImageSha256']
    with Image.open(io.BytesIO(image_response.content)) as saved, Image.open(io.BytesIO(stream.getvalue())) as original:
        assert saved.tobytes() == original.tobytes()
    assert parent_path.read_bytes() == before
    assert client.get('/api/identity/jobs').json() == jobs_before
    record = json.loads((config.dream_root/'data/identity/anime-profiles'/f"{anime['id']}.json").read_text())
    assert record['featureKey'] and record['sourceKind'] == 'upload'
    from identity_service import IdentityService
    from identity_anime_profiles import AnimeProfiles
    library = AnimeProfiles(IdentityService(config, runner))
    library.recover()
    assert library.get(anime['id'])['state'] == 'ready'
    assert library.get(anime['id'])['sourceJobId'] is None


def test_import_preserves_existing_archive_and_rejects_duplicate_name(anime_harness):
    client, config, _, _ = anime_harness
    parent, job = source_pair(client)
    old = wait_anime(client, create_anime(client, parent, job).json()['id'])
    folder = config.dream_root/'data/identity/anime-profiles'
    snapshot = {p.name:p.read_bytes() for p in folder.iterdir()}
    response = client.post('/api/identity/anime-profiles/import', json=import_body(parent, name=old['name']))
    assert response.status_code == 409
    assert {p.name:p.read_bytes() for p in folder.iterdir()} == snapshot
    response = client.post('/api/identity/anime-profiles/import', json=import_body(parent))
    assert response.status_code == 200, response.text
    assert wait_anime(client, response.json()['id'])['state'] == 'ready'
    for name, contents in snapshot.items():
        assert (folder/name).read_bytes() == contents


@pytest.mark.parametrize('change,status', [
    ({'imageBase64':'not base64!'},422),
    ({'imageBase64':base64.b64encode(b'not an image').decode()},422),
    ({'imageBase64':image_base64((4001,4000))},413),
    ({'profileId':'person-'+'f'*24},404),
    ({'name':'  '},422),
    ({'sourceName':'x'*256},422),
    ({'sourcePath':'C:/secret.png'},422),
    ({'jobId':'identity-'+'a'*24},422),
])
def test_invalid_import_never_creates_archive(anime_harness, change, status):
    client, config, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    response = client.post('/api/identity/anime-profiles/import', json=import_body(parent, **change))
    assert response.status_code == status, response.text
    assert client.get('/api/identity/anime-profiles').json() == []
    assert not list((config.dream_root/'data/identity/anime-profiles').glob('*'))


def test_import_is_same_origin_and_size_guarded(anime_harness):
    client, _, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    assert client.post('/api/identity/anime-profiles/import', json=import_body(parent),
                       headers={'origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/identity/anime-profiles/import', content=b'{}',
                       headers={'content-length':str(15*1024*1024)}).status_code == 413


def test_imported_archive_can_bind_polish_and_rejects_changed_image(anime_harness):
    client, config, _, _ = anime_harness
    parent, job = source_pair(client)
    response = client.post('/api/identity/anime-profiles/import', json=import_body(parent))
    assert response.status_code == 200, response.text
    anime = wait_anime(client, response.json()['id'])
    request = {**job['request'], 'facePolish':True, 'animeProfileId':anime['id']}
    generated = client.post('/api/identity/generate', json=request)
    assert generated.status_code == 200, generated.text
    result = finished(client, generated.json()['id'])
    assert result['state'] == 'complete', result
    assert result['result']['metadata']['facePolish']['profileName'] == 'Example-动漫-GPT'
    (config.dream_root/'data/identity/anime-profiles'/f"{anime['id']}.png").write_bytes(b'corrupt')
    assert client.post('/api/identity/generate', json=request).status_code == 409


def test_failed_anime_detection_never_becomes_ready(anime_harness, monkeypatch):
    client, _, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    from identity_service import IdentityService
    original = IdentityService._worker
    def fail(self, operation, payload, cancelled=None):
        if operation == 'anime_prepare':
            raise ValueError('未检测到清晰动漫脸')
        return original(self, operation, payload, cancelled)
    monkeypatch.setattr(IdentityService, '_worker', fail)
    response = client.post('/api/identity/anime-profiles/import', json=import_body(parent))
    assert response.status_code == 200, response.text
    final = wait_anime(client, response.json()['id'])
    assert final['state'] == 'failed' and '未检测到' in final['error']


def test_import_rejects_archived_parent_and_unsupported_format(anime_harness):
    client, _, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    stream = io.BytesIO()
    Image.new('RGB',(160,160)).save(stream,'GIF')
    response = client.post('/api/identity/anime-profiles/import', json=import_body(
        parent,imageBase64=base64.b64encode(stream.getvalue()).decode()))
    assert response.status_code == 422
    assert client.post('/api/identity/profiles/'+parent['id']+'/archive').status_code == 200
    assert client.post('/api/identity/anime-profiles/import',json=import_body(parent)).status_code == 409
    assert client.get('/api/identity/anime-profiles').json() == []


def test_import_normalizes_exif_and_drops_metadata(anime_harness):
    client, _, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    response = client.post('/api/identity/anime-profiles/import',json=import_body(
        parent,imageBase64=image_base64((160,240),orientation=6),sourceName='C:\\fakepath\\portrait.jpg'))
    assert response.status_code == 200, response.text
    anime = wait_anime(client,response.json()['id'])
    assert anime['state'] == 'ready' and anime['sourceName'] == 'portrait.jpg'
    with Image.open(io.BytesIO(client.get(anime['imageUrl']).content)) as image:
        assert image.size == (240,160) and not image.getexif()


def test_import_id_collision_cannot_delete_existing_archive(anime_harness, monkeypatch):
    client, config, _, _ = anime_harness
    parent, job = source_pair(client)
    old = wait_anime(client,create_anime(client,parent,job).json()['id'])
    folder = config.dream_root/'data/identity/anime-profiles'
    snapshot = {p.name:p.read_bytes() for p in folder.iterdir()}
    import identity_anime_profiles
    monkeypatch.setattr(identity_anime_profiles.secrets,'token_hex',lambda _:old['id'].removeprefix('anime-'))
    response = client.post('/api/identity/anime-profiles/import',json=import_body(parent))
    assert response.status_code == 409
    assert {p.name:p.read_bytes() for p in folder.iterdir()} == snapshot


def test_transparent_upload_uses_preview_white_background_not_hidden_rgb(anime_harness):
    client, _, _, _ = anime_harness
    parent = wait_profile(client, create_profile(client)['id'])
    image = Image.new('RGBA',(160,160),(255,0,0,0))
    image.putpixel((10,10),(255,0,0,128))
    stream = io.BytesIO(); image.save(stream,'PNG')
    response = client.post('/api/identity/anime-profiles/import',json=import_body(
        parent,imageBase64=base64.b64encode(stream.getvalue()).decode()))
    assert response.status_code == 200, response.text
    anime = wait_anime(client,response.json()['id'])
    with Image.open(io.BytesIO(client.get(anime['imageUrl']).content)) as saved:
        assert saved.getpixel((0,0)) == (255,255,255)
        assert saved.getpixel((10,10)) == (255,127,127)
