from __future__ import annotations

from pathlib import Path

import pytest


STABLE_DIFFUSION_ROOT = Path("E:/Dream/src/stable-diffusion.cpp")


def _native_source(name: str) -> str:
    path = STABLE_DIFFUSION_ROOT / name
    if not path.exists():
        pytest.skip(f"stable-diffusion.cpp source is not present: {path}")
    return path.read_text(encoding="utf-8")


def test_native_public_api_declares_observed_latent_trace_callback():
    header = _native_source("include/stable-diffusion.h")
    util_header = _native_source("src/core/util.h")
    util_source = _native_source("src/core/util.cpp")

    assert "sd_latent_trace_cb_t" in header
    assert "sd_set_latent_trace_callback" in header
    assert "sd_set_latent_trace_callback" in util_header
    assert "sd_get_latent_trace_callback" in util_header
    assert "sd_latent_trace_cb_t" in util_source


def test_native_sampler_emits_live_latent_state_not_only_rgb_preview():
    source = _native_source("src/stable-diffusion.cpp")

    assert "sd_get_latent_trace_callback" in source
    assert "x.data()" in source
    assert "x.numel()" in source
    assert "shape.data()" in source


def test_native_cli_writes_observed_latent_metrics_and_channel_maps():
    source = _native_source("examples/cli/main.cpp")

    assert "--latent-trace-path" in source
    assert "latent_trace_path" in source
    assert "latent-step-%03d-ch" in source
    assert "delta_mean_abs" in source
    assert "cosine" in source
    assert "\\\"histogram\\\"" in source


def test_windows_wrapper_requests_latent_telemetry_for_microscope_runs():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "latent-metrics.jsonl" in text
    assert '"--latent-trace-path"' in text


def test_windows_wrapper_degrades_when_active_native_binary_lacks_latent_trace_option():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")

    assert "--help" in text
    assert "$latentTraceSupported" in text
    assert "if ($latentTraceSupported)" in text


def test_windows_wrapper_uses_the_configured_engine_and_not_readonly_pid_variable():
    wrapper = Path(__file__).resolve().parents[4] / "scripts" / "run_stable_diffusion_wrapper.ps1"
    text = wrapper.read_text(encoding="utf-8")
    assert "GetEnvironmentVariable('DREAM_STABLE_DIFFUSION_CPP_EXE')" in text
    assert "$sampleProcessId =" in text
    assert "$pid =" not in text


def test_toolkit_preflight_checks_headers_and_libraries_not_just_nvcc():
    preflight = Path(__file__).resolve().parents[4] / "scripts" / "prepare_dream_core.ps1"
    text = preflight.read_text(encoding="utf-8")
    assert "cuda_runtime.h" in text
    assert "cudart.lib" in text
    assert "cublas.lib" in text
    assert "CUDA_TOOLKIT_INCOMPLETE" in text
