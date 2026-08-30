#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def read(root: Path, rel: str) -> str:
    p = root / rel
    assert p.is_file(), f"missing {rel}"
    return p.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--expect", choices=["baseline", "patched"], required=True)
    a = ap.parse_args()
    root = a.root.resolve()

    te = read(root, "app/src/main/cpp/src/TextEncoder.hpp")
    pipe = read(root, "app/src/main/cpp/src/PipelineSdxl.hpp")
    qnn = read(root, "app/src/main/cpp/src/QnnModel.hpp")
    maincpp = read(root, "app/src/main/cpp/src/main.cpp")
    backend = read(root, "app/src/main/java/io/github/xororz/localdream/service/BackendService.kt")
    gradle = read(root, "app/build.gradle.kts")
    strings = read(root, "app/src/main/res/values/strings.xml")
    screen = read(root, "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt")

    # H1 is the known-good parallel-installable baseline.
    assert 'applicationId = "io.github.xororz.localdream.s24uharness"' in gradle or \
           'applicationId = "io.github.xororz.localdream.s24u154"' in gradle
    assert "S24U HARNESS · RAW" in screen or "S24U 154 · NPU LONG PROMPT" in screen

    if a.expect == "baseline":
        assert "LongPromptChunking.hpp" not in te
        assert "processWeightedPromptLong" not in te
        assert "text_seq_len_" not in pipe
        assert "--text_seq_len" not in maincpp
        assert 'File(modelDir, "TEXT_SEQ_LEN")' not in backend
        assert 'applicationId = "io.github.xororz.localdream.s24uharness"' in gradle
        print("NATIVE154_BASELINE=PASS")
        return 0

    helper = read(root, "app/src/main/cpp/src/LongPromptChunking.hpp")
    assert "kLongSequenceLength = 154" in helper
    assert "kClipContentLength = 75" in helper

    # TextEncoder: exact legacy entry remains, 154 dispatches to two-window path,
    # position IDs restart at each 77-token boundary, and token counting exposes
    # the larger static context to the UI.
    assert "processWeightedPromptLong" in te
    assert "kLongSequenceLength" in te
    assert "contentCapacityForSequenceLength(max_len)" in te
    assert "localPositionForSlot(i)" in te
    assert "usedChunkCount(content)" in te
    assert "int max_len = 77" in te

    # Pipeline: dynamic conditioning length, two CLIP-window loop, first pooled
    # embedding retained, first CLS copied to later chunks, 154 forced low-RAM.
    assert "int textSeqLen() const override { return text_seq_len_; }" in pipe
    assert "prompts.ids.data() + text_seq_len_" in pipe
    assert "const int chunks = text_seq_len_ /" in pipe
    assert "memcpy(first_cls.data()" in pipe
    assert "memcpy(out_pooled" in pipe
    assert "154-token SDXL requires low-RAM mode" in pipe

    # QNN: model binary must prove its static graph is exactly [1,SEQ,2048]
    # before encoder-hidden-state memcpy.
    assert "int text_seq_len, float *out_sample" in qnn
    assert "QNN_TENSOR_GET_RANK(inputs[1])" in qnn
    assert "dims[1] != (uint32_t)text_seq_len" in qnn
    assert "tensorElems(inputs[1]) != elementCount" in qnn

    # Native server + Android process launcher agree on sequence length.
    assert '"text_seq_len", pal::required_argument' in maincpp
    assert "opts.text_seq_len != 77 && opts.text_seq_len != 154" in maincpp
    assert "154-token context requires --lowram" in maincpp
    assert "registerTokenizeEndpoint(svr, text_encoder.get(), opts.text_seq_len)" in maincpp

    assert "val textSeqLen: Int" in backend
    assert 'File(modelDir, "TEXT_SEQ_LEN")' in backend
    assert 'command += listOf("--text_seq_len", config.textSeqLen.toString())' in backend
    assert "config.textSeqLen == 154 || preferences.getBoolean(\"sdxl_lowram\", true)" in backend

    # Parallel-install identity protects the installed official app/model set.
    assert 'applicationId = "io.github.xororz.localdream.s24u154"' in gradle
    assert "versionCode = 74154" in gradle
    assert 'versionName = "2.8.1-s24u154-r1"' in gradle
    assert "Local Dream S24U 154" in strings
    assert "S24U 154 · NPU LONG PROMPT" in screen

    print("NATIVE154_SOURCE_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
