from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "DreamEngineSupport.psm1"


def run_powershell_json(script: str) -> object:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")


def test_model_hash_cache_hits_and_invalidates_when_file_identity_changes(tmp_path: Path):
    model = tmp_path / "model.gguf"
    cache = tmp_path / "model-hashes.json"
    model.write_bytes(b"first model bytes")

    def read_hash() -> dict[str, object]:
        value = run_powershell_json(
            f"Import-Module '{ps_quote(MODULE)}' -Force; "
            f"Get-DreamCachedFileHash -Path '{ps_quote(model)}' -CachePath '{ps_quote(cache)}' | ConvertTo-Json -Compress"
        )
        assert isinstance(value, dict)
        return value

    first = read_hash()
    second = read_hash()

    assert first["CacheHit"] is False
    assert first["Sha256"] == hashlib.sha256(b"first model bytes").hexdigest().upper(), first
    assert second == {**first, "CacheHit": True}

    model.write_bytes(b"replacement model bytes are a different size")
    third = read_hash()

    assert third["CacheHit"] is False
    assert third["Sha256"] == hashlib.sha256(b"replacement model bytes are a different size").hexdigest().upper()


def test_stable_diffusion_arguments_enable_flash_attention_and_keep_h6_opt_in():
    request_literal = "[pscustomobject]@{ model_path='E:\\Dream\\models\\model.gguf'; prompt='lake'; negative='blur'; seed=7; steps=20; cfg=4; width=512; height=512; sampling_method='dpm++2m_sde'; scheduler='karras' }"
    common = (
        f"Import-Module '{ps_quote(MODULE)}' -Force; $request={request_literal}; "
        "$plan=New-DreamStableDiffusionArguments -Request $request -OutputPath 'E:\\Dream\\outputs\\image.png' "
        "-MaxVramGb 4.4 -TraceLevel 'basic'; $plan | ConvertTo-Json -Depth 5 -Compress"
    )
    basic = run_powershell_json(common)

    assert isinstance(basic, dict)
    assert basic["FlashAttention"] is True
    assert "--diffusion-fa" in basic["Arguments"]
    assert basic["Arguments"][basic["Arguments"].index("--sampling-method") + 1] == "dpm++2m_sde"
    assert "--preview" not in basic["Arguments"]

    disabled = run_powershell_json(
        common.replace("-TraceLevel 'basic'", "-TraceLevel 'basic' -DisableDiffusionFlashAttention $true")
    )
    assert disabled["FlashAttention"] is False
    assert "--diffusion-fa" not in disabled["Arguments"]

    h6 = run_powershell_json(
        common.replace(
            "-TraceLevel 'basic'",
            "-TraceLevel 'h6' -TraceDirectory 'E:\\Dream\\traces\\job' -LatentTraceSupported $true -LatentTracePath 'E:\\Dream\\traces\\job\\latent.jsonl'",
        )
    )
    assert "--preview" in h6["Arguments"]
    assert "--latent-trace-path" in h6["Arguments"]
