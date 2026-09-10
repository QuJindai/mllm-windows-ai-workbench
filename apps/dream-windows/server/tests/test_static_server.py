from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from config import DreamServerConfig


class RuntimeStub:
    pass


def test_browser_build_is_served_from_the_same_localhost_origin(tmp_path: Path):
    dist = tmp_path / "frontend"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Dream</title>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg />", encoding="utf-8")
    config = DreamServerConfig.for_testing()
    config = DreamServerConfig(**{**config.__dict__, "frontend_dist": dist})

    client = TestClient(create_app(config=config, runtime=RuntimeStub()))

    assert client.get("/").status_code == 200
    assert client.get("/").text.startswith("<!doctype html>")
    assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
