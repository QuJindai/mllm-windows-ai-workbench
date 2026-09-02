#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_runtime_graph_contract.py <h6r3+-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(html, "RUNTIME COMPUTE GRAPH", "runtime compute graph heading")
    require(html, 'id="runtime-graph"', "runtime graph container")
    require(js, "renderRuntimeGraph", "runtime graph renderer")
    for field in ("backend", "shape", "execution_state", "input_source", "output_destination"):
        require(js, field, f"runtime graph {field}")
    if "expected_calls" in js:
        require(js, "observed_calls", "H6R4 observed call truth")
        require(js, "duration_ms", "H6R4 runtime duration")
    else:
        require(js, "call_count", "H6R3 runtime call count")
        require(js, "duration_ms", "H6R3 runtime duration")
    for backend in ("MNN / CPU", "QNN / HTP", "Scheduler / CPU"):
        require(js, backend, f"backend truth {backend}")
    for node in (
        "Prompt", "Tokenizer / Chunker", "CLIP-1 / CLIP-2", "Conditioning",
        "CFG / Guidance", "UNet Chunk", "Chunk Fusion", "Scheduler",
        "Latent zₜ", "VAE Decode", "Image",
    ):
        require(js, node, f"runtime node {node}")
    require(js, "activeChunks", "fusion-aware expected UNet calls")
    if "observed_calls" in js:
        require(js, "unet_total_ms", "native cumulative duration truth")
        require(js, "Unattributed", "time accounting")
        forbid(js, "sumPhaseDuration", "bounded event history is not runtime truth")
    else:
        require(js, "sumPhaseDuration", "legacy runtime duration aggregation")
    require(js, "node.addEventListener('click'", "click-to-expand graph nodes")

    require(html, "Production QNN 图未导出", "production attention capability boundary")
    require(html, "Debug UNet Graph", "H7 attention path")
    forbid(
        html,
        '<span class="kicker">ARCHITECTURE</span><h2>真实计算链</h2>',
        "old low-density architecture",
    )

    print("H6R3_RUNTIME_GRAPH_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
