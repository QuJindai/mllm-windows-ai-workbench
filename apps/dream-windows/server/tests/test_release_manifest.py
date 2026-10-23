import json
from dataclasses import replace

from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig


def test_release_manifest_comes_from_served_frontend_without_cache(tmp_path):
    expected = {"release": "test-build", "entry": "http://127.0.0.1:8766/"}
    (tmp_path / "release.json").write_text(json.dumps(expected), encoding="utf-8")
    config = replace(DreamServerConfig.for_testing(), frontend_dist=tmp_path)
    client = TestClient(create_app(config=config, runtime=object()))
    response = client.get("/release.json")
    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"


def test_missing_release_manifest_is_explicit_not_an_invented_version(tmp_path):
    config = replace(DreamServerConfig.for_testing(), frontend_dist=tmp_path)
    client = TestClient(create_app(config=config, runtime=object()))
    response = client.get("/release.json")
    assert response.status_code == 404
    assert response.json()["code"] == "RELEASE_MANIFEST_NOT_FOUND"


def test_entry_html_cannot_reuse_previous_release_from_browser_cache(tmp_path):
    (tmp_path / 'index.html').write_text('<script src="/assets/new-release.js"></script>')
    config = replace(DreamServerConfig.for_testing(), frontend_dist=tmp_path)
    client = TestClient(create_app(config=config, runtime=object()))
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers.get('cache-control') == 'no-store'
    assert 'new-release.js' in response.text
