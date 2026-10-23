"""Explicit test-only native capabilities; no executable here is ever launched."""
import json


def install_research_engine(config, capabilities=("h6-conditioning-v1",)):
    # An inherited user override must never redirect test writes into a live engine.
    config.h7_engine_exe.resolve().relative_to(config.dream_root.resolve())
    config.h7_engine_exe.parent.mkdir(parents=True, exist_ok=True)
    config.h7_engine_exe.write_bytes(b"test-only-never-executed")
    config.h7_manifest_path.write_text(json.dumps({
        "schemaVersion": 1, "executable": config.h7_engine_exe.name, "source": "debug-unet",
        "capabilities": capabilities,
    }), encoding="utf-8")
