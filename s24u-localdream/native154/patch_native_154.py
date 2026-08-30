#!/usr/bin/env python3
"""Apply the S24U 154-token native overlay to exact Local Dream v2.8.1.

Run after s24u-localdream/patch_localdream.py so the existing H1 Android
identity/diagnostic card is used as a tested baseline. This patch is fail-closed:
all native source files must still match the exact upstream v2.8.1 Git blobs.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

EXPECTED_GIT_BLOBS = {
    "app/src/main/cpp/src/TextEncoder.hpp": "201c9fac3d53cd146d3a9a2db35a62871b5b497d",
    "app/src/main/cpp/src/PipelineSdxl.hpp": "31c14f7622d7ee4d9e3f57d84c8d3bb97829664a",
    "app/src/main/cpp/src/QnnModel.hpp": "8ef502822d483aaf7f15ef72ae58c99199d89d09",
    "app/src/main/cpp/src/main.cpp": "8f45b840277d669916b045188c7358385a26016f",
    "app/src/main/java/io/github/xororz/localdream/service/BackendService.kt": "e04e5bc49485218b75bcb5555a721ba38e943ba3",
}


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_exact(root: Path, rel: str) -> Path:
    path = root / rel
    data = path.read_bytes()
    got = git_blob_sha(data)
    expected = EXPECTED_GIT_BLOBS[rel]
    if got != expected:
        raise RuntimeError(f"{rel}: upstream blob {got}, expected {expected}")
    return path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"{label}: start anchor missing")
    if text.find(start, a + 1) >= 0:
        raise RuntimeError(f"{label}: start anchor not unique")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"{label}: end anchor missing")
    return text[:a] + replacement + text[b:]


def patch_text_encoder(text: str) -> str:
    text = replace_once(
        text,
        '#include "Logger.hpp"\n#include "MemUtils.hpp"',
        '#include "Logger.hpp"\n#include "LongPromptChunking.hpp"\n#include "MemUtils.hpp"',
        "TextEncoder include",
    )
    text = replace_once(
        text,
        '  ProcessedPrompt processWeightedPrompt(const std::string &prompt_text,\n                                        int max_len = 77) {\n    ProcessedPrompt result;',
        '  ProcessedPrompt processWeightedPrompt(const std::string &prompt_text,\n                                        int max_len = 77) {\n'
        '    if (max_len == localdream::s24u154::kLongSequenceLength)\n'
        '      return processWeightedPromptLong(prompt_text);\n'
        '    if (max_len != localdream::s24u154::kLegacySequenceLength)\n'
        '      throw std::invalid_argument("Unsupported CLIP sequence length: " +\n'
        '                                  std::to_string(max_len));\n'
        '    ProcessedPrompt result;',
        "TextEncoder long dispatch",
    )

    long_method = r'''
  // S24U SDXL long-prompt path. CLIP itself remains a 77-token graph: this
  // prepares two independent windows, each with its own BOS/EOS and restarted
  // positional encoding, then PipelineSdxl executes CLIP once per window.
  ProcessedPrompt processWeightedPromptLong(const std::string &prompt_text) {
    if (!sdxl_)
      throw std::invalid_argument("154-token mode is SDXL-only");

    constexpr int max_len = localdream::s24u154::kLongSequenceLength;
    constexpr int chunks = 2;
    const int dim1 = 768;
    const int dim2 = text_embedding_size_2;

    ProcessedPrompt result;
    std::vector<float> embeddings((size_t)max_len * dim1, 0.0f);
    std::vector<float> embeddings_2((size_t)max_len * dim2, 0.0f);
    std::vector<int> ids(max_len, 49407);   // CLIP-L pads with EOS
    std::vector<int> ids2(max_len, 0);      // CLIP-G pads with id 0 after EOS
    std::vector<float> weights(max_len, 1.0f);

    for (int chunk = 0; chunk < chunks; ++chunk) {
      const int base = chunk * localdream::s24u154::kClipSequenceLength;
      ids[base] = 49406;
      ids2[base] = 49406;
    }

    int content = 0;
    auto next_slot = [&]() -> int {
      if (content >= localdream::s24u154::contentCapacityForSequenceLength(max_len))
        return -1;
      return localdream::s24u154::outputSlotForContentIndex(content++);
    };

    for (const auto &token : promptProcessor_.process(prompt_text)) {
      if (content >= localdream::s24u154::contentCapacityForSequenceLength(max_len))
        break;
      if (token.is_embedding) {
        int emb_tokens = 0;
        if (!token.embedding_data.empty())
          emb_tokens = token.embedding_data.size() / dim1;
        else if (!token.embedding_data_2.empty())
          emb_tokens = token.embedding_data_2.size() / dim2;
        for (int i = 0; i < emb_tokens; ++i) {
          const int slot = next_slot();
          if (slot < 0) break;
          // The CLIP graph consumes embeddings, not token IDs. Use a non-EOS
          // sentinel so textual inversion can never be mistaken for the real
          // EOS when pooled/CLS rows are selected later.
          ids[slot] = 0;
          ids2[slot] = 0;
          if (!token.embedding_data.empty()) {
            for (int j = 0; j < dim1; ++j)
              embeddings[(size_t)slot * dim1 + j] =
                  token.embedding_data[(size_t)i * dim1 + j] * token.weight;
          }
          if (!token.embedding_data_2.empty()) {
            for (int j = 0; j < dim2; ++j)
              embeddings_2[(size_t)slot * dim2 + j] =
                  token.embedding_data_2[(size_t)i * dim2 + j] * token.weight;
          }
        }
      } else {
        for (int tid : tokenizer_->Encode(token.text)) {
          const int slot = next_slot();
          if (slot < 0) break;
          ids[slot] = tid;
          ids2[slot] = tid;
          weights[slot] = token.weight;
        }
      }
    }

    const int placed = std::min(
        content, localdream::s24u154::contentCapacityForSequenceLength(max_len));
    for (int chunk = 0; chunk < chunks; ++chunk) {
      const int used = std::clamp(
          placed - chunk * localdream::s24u154::kClipContentLength, 0,
          localdream::s24u154::kClipContentLength);
      const int eos = localdream::s24u154::eosSlotForChunk(chunk, used);
      ids[eos] = 49407;
      ids2[eos] = 49407;
      // ids is already EOS-filled after eos; ids2 is already zero-filled.
    }

    applyTokenAndPosEmb(ids, weights, token_emb_, pos_emb_, dim1, max_len,
                        embeddings);
    applyTokenAndPosEmb(ids2, weights, token_emb_2_, pos_emb_2_, dim2, max_len,
                        embeddings_2);
    result.ids = std::move(ids);
    result.ids_2 = std::move(ids2);
    result.weighted_embeddings = std::move(embeddings);
    result.weighted_embeddings_2 = std::move(embeddings_2);
    return result;
  }

'''
    text = replace_once(
        text,
        "\n  // Anima/Qwen: BPE ids",
        long_method + "  // Anima/Qwen: BPE ids",
        "TextEncoder long method insertion",
    )
    text = replace_once(
        text,
        "    // Tokens that fit alongside the implicit BOS/EOS markers.\n"
        "    const int budget = max_len - 2;",
        "    // 154 consists of two independent 77-token CLIP windows, hence\n"
        "    // 150 content-token slots rather than max_len-2.\n"
        "    const int budget =\n"
        "        localdream::s24u154::contentCapacityForSequenceLength(max_len);\n"
        "    if (budget <= 0)\n"
        "      throw std::invalid_argument(\"Unsupported CLIP sequence length\");",
        "TextEncoder tokenize budget",
    )
    text = replace_once(
        text,
        "    info.count = content + 2;  // BOS + EOS\n    return info;",
        "    info.count = content +\n"
        "                 2 * localdream::s24u154::usedChunkCount(content);\n"
        "    return info;",
        "TextEncoder tokenize count",
    )
    text = replace_once(
        text,
        "      float weight = (i < (int)weights.size()) ? weights[i] : 1.0f;\n\n"
        "      bool has_emb = false;",
        "      float weight = (i < (int)weights.size()) ? weights[i] : 1.0f;\n"
        "      const int pos =\n"
        "          localdream::s24u154::localPositionForSlot(i);\n\n"
        "      bool has_emb = false;",
        "TextEncoder local position",
    )
    text = replace_once(
        text,
        "          embeddings[i * dim + j] = token_val * weight + pos_emb[i * dim + j];",
        "          embeddings[i * dim + j] =\n"
        "              token_val * weight + pos_emb[pos * dim + j];",
        "TextEncoder token pos embedding",
    )
    text = replace_once(
        text,
        "          embeddings[i * dim + j] += pos_emb[i * dim + j];",
        "          embeddings[i * dim + j] += pos_emb[pos * dim + j];",
        "TextEncoder TI pos embedding",
    )
    return text


def patch_pipeline(text: str) -> str:
    text = replace_once(
        text,
        '#include "Config.hpp"\n#include "MnnUtils.hpp"',
        '#include "Config.hpp"\n#include "LongPromptChunking.hpp"\n#include "MnnUtils.hpp"',
        "Pipeline include",
    )
    text = replace_once(
        text,
        "               std::string vae_encoder_path, bool use_v_pred, bool lowram)\n"
        "      : PipelineQnn(text_encoder, model_dir, /*sdxl=*/true, use_v_pred),",
        "               std::string vae_encoder_path, bool use_v_pred,\n"
        "               int text_seq_len, bool lowram)\n"
        "      : PipelineQnn(text_encoder, model_dir, /*sdxl=*/true, use_v_pred),",
        "Pipeline constructor signature",
    )
    text = replace_once(
        text,
        "        vae_encoder_path_(std::move(vae_encoder_path)),\n        lowram_(lowram) {}",
        "        vae_encoder_path_(std::move(vae_encoder_path)),\n"
        "        text_seq_len_(text_seq_len),\n        lowram_(lowram) {\n"
        "    if (!localdream::s24u154::isSupportedSequenceLength(text_seq_len_))\n"
        "      throw std::invalid_argument(\"Unsupported SDXL text sequence length\");\n"
        "    if (text_seq_len_ == localdream::s24u154::kLongSequenceLength &&\n"
        "        !lowram_)\n"
        "      throw std::invalid_argument(\"154-token SDXL requires low-RAM mode\");\n"
        "  }",
        "Pipeline constructor body",
    )
    text = replace_once(
        text,
        "  int vaeTilePixelSize() const override { return 1024; }",
        "  int vaeTilePixelSize() const override { return 1024; }\n"
        "  int textSeqLen() const override { return text_seq_len_; }",
        "Pipeline textSeqLen",
    )
    text = replace_once(
        text,
        "                  prompts.ids.data() + 77, cond.posHidden(), cond.posPooled());",
        "                  prompts.ids.data() + text_seq_len_, cond.posHidden(),\n"
        "                  cond.posPooled());",
        "Pipeline positive ids offset",
    )
    text = replace_once(
        text,
        "                                   cond.negPooled(), time_ids, out_batch2))",
        "                                   cond.negPooled(), time_ids, text_seq_len_,\n"
        "                                   out_batch2))",
        "Pipeline uncond seq",
    )
    text = replace_once(
        text,
        "            cond.posPooled(), time_ids + 6, out_batch2 + single_latent_size))",
        "            cond.posPooled(), time_ids + 6, text_seq_len_,\n"
        "            out_batch2 + single_latent_size))",
        "Pipeline cond seq",
    )

    dual = r'''  // CLIP remains a fixed 77-token MNN graph. For 154 mode execute both
  // encoders twice and concatenate [77,2048] + [77,2048]. SDXL pooled
  // conditioning intentionally comes from chunk 0, matching Compel's pooled
  // path (which truncates pooled tokenization to one CLIP window). For hidden
  // conditioning, copy chunk-0 CLS/EOS to later chunk CLS rows, also matching
  // Compel's default COPY_FIRST_CLS_TOKEN long-prompt behavior.
  void runDualClip(const std::vector<float> &emb1,
                   const std::vector<float> &emb2, const int *ids,
                   float *out_hidden_concat, float *out_pooled) {
    const int concat_dim = text_embedding_size + text_embedding_size_2;
    const int chunks = text_seq_len_ / localdream::s24u154::kClipSequenceLength;
    std::vector<float> first_cls((size_t)concat_dim, 0.0f);

    for (int chunk = 0; chunk < chunks; ++chunk) {
      const int base = chunk * localdream::s24u154::kClipSequenceLength;
      auto in1 =
          clip_interpreter_->getSessionInput(clip_session_, "input_embedding");
      memcpy(in1->host<float>(),
             emb1.data() + (size_t)base * text_embedding_size,
             77 * text_embedding_size * sizeof(float));
      clip_interpreter_->runSession(clip_session_);
      auto out1 = clip_interpreter_->getSessionOutput(clip_session_,
                                                      "last_hidden_state");
      const float *out1_data = out1->host<float>();

      auto in2 = clip2_interpreter_->getSessionInput(clip2_session_,
                                                     "input_embedding");
      memcpy(in2->host<float>(),
             emb2.data() + (size_t)base * text_embedding_size_2,
             77 * text_embedding_size_2 * sizeof(float));
      clip2_interpreter_->runSession(clip2_session_);
      auto out2_hidden = clip2_interpreter_->getSessionOutput(
          clip2_session_, "last_hidden_state");
      auto out2_pool = clip2_interpreter_->getSessionOutput(
          clip2_session_, "pooled_output");
      const float *out2_hidden_data = out2_hidden->host<float>();
      const float *out2_pool_data = out2_pool->host<float>();

      for (int t = 0; t < 77; ++t) {
        const int dst = base + t;
        memcpy(out_hidden_concat + (size_t)dst * concat_dim,
               out1_data + (size_t)t * text_embedding_size,
               text_embedding_size * sizeof(float));
        memcpy(out_hidden_concat + (size_t)dst * concat_dim + text_embedding_size,
               out2_hidden_data + (size_t)t * text_embedding_size_2,
               text_embedding_size_2 * sizeof(float));
      }

      int eos_pos = 76;
      for (int i = 0; i < 77; ++i) {
        if (ids[base + i] == 49407) {
          eos_pos = i;
          break;
        }
      }
      float *cls_dst = out_hidden_concat + (size_t)(base + eos_pos) * concat_dim;
      if (chunk == 0) {
        memcpy(first_cls.data(), cls_dst, (size_t)concat_dim * sizeof(float));
        memcpy(out_pooled,
               out2_pool_data + (size_t)eos_pos * text_embedding_size_2,
               text_embedding_size_2 * sizeof(float));
      } else {
        memcpy(cls_dst, first_cls.data(), (size_t)concat_dim * sizeof(float));
      }
    }
  }

'''
    text = replace_between(
        text,
        "  // Encoder 1 (CLIP-L):",
        "  const std::string clip_path_;",
        dual,
        "Pipeline runDualClip",
    )
    text = replace_once(
        text,
        "  const std::string vae_encoder_path_;\n  const bool lowram_;",
        "  const std::string vae_encoder_path_;\n"
        "  const int text_seq_len_;\n  const bool lowram_;",
        "Pipeline seq member",
    )
    return text


def patch_qnn(text: str) -> str:
    text = replace_once(
        text,
        "                                   float *text_embeds, float *time_ids,\n"
        "                                   float *out_sample) {",
        "                                   float *text_embeds, float *time_ids,\n"
        "                                   int text_seq_len, float *out_sample) {",
        "QNN SDXL signature",
    )
    old = r'''    // encoder_hidden_states (fp32, 1x77x2048)
    {
      int elementCount = 1 * 77 * (text_embedding_size + text_embedding_size_2);
      memcpy(static_cast<float *>(QNN_TENSOR_GET_CLIENT_BUF(inputs[1]).data),
             encoder_hidden_states, elementCount * sizeof(float));
    }'''
    new = r'''    // encoder_hidden_states (fp32, 1xSEQx2048). QNN context bins
    // are static-shape; fail before memcpy if a 77-token model is accidentally
    // paired with a 154-token runtime (or vice versa).
    {
      const uint32_t rank = QNN_TENSOR_GET_RANK(inputs[1]);
      uint32_t *dims = QNN_TENSOR_GET_DIMENSIONS(inputs[1]);
      const int hidden_dim = text_embedding_size + text_embedding_size_2;
      if (rank != 3 || dims == nullptr || dims[0] != 1 ||
          dims[1] != (uint32_t)text_seq_len || dims[2] != (uint32_t)hidden_dim) {
        QNN_ERROR("SDXL UNET context mismatch: expected [1,%d,%d]", text_seq_len,
                  hidden_dim);
        return StatusCode::FAILURE;
      }
      const size_t elementCount = (size_t)text_seq_len * hidden_dim;
      if (tensorElems(inputs[1]) != elementCount) {
        QNN_ERROR("SDXL UNET context element mismatch");
        return StatusCode::FAILURE;
      }
      memcpy(static_cast<float *>(QNN_TENSOR_GET_CLIENT_BUF(inputs[1]).data),
             encoder_hidden_states, elementCount * sizeof(float));
    }'''
    return replace_once(text, old, new, "QNN hidden shape")


def patch_main(text: str) -> str:
    text = replace_once(
        text,
        "  bool lowram = false;\n  bool anima_seq_dit = false;",
        "  bool lowram = false;\n"
        "  int text_seq_len = 77;\n"
        "  bool anima_seq_dit = false;",
        "main options member",
    )
    text = replace_once(
        text,
        '         "  --lowram               (sdxl/anima) load/release models per stage\\n"',
        '         "  --lowram               (sdxl/anima) load/release models per stage\\n"\n'
        '         "  --text_seq_len <n>     SDXL text context: 77 or 154\\n"',
        "main help",
    )
    text = replace_once(
        text,
        "    OPT_LOWRAM,\n    OPT_ANIMA_SEQ_DIT,",
        "    OPT_LOWRAM,\n    OPT_TEXT_SEQ_LEN,\n    OPT_ANIMA_SEQ_DIT,",
        "main enum",
    )
    text = replace_once(
        text,
        '      {"lowram", pal::no_argument, NULL, OPT_LOWRAM},\n'
        '      {"anima_seq_dit", pal::no_argument, NULL, OPT_ANIMA_SEQ_DIT},',
        '      {"lowram", pal::no_argument, NULL, OPT_LOWRAM},\n'
        '      {"text_seq_len", pal::required_argument, NULL, OPT_TEXT_SEQ_LEN},\n'
        '      {"anima_seq_dit", pal::no_argument, NULL, OPT_ANIMA_SEQ_DIT},',
        "main long option",
    )
    text = replace_once(
        text,
        "      case OPT_LOWRAM:\n        opts.lowram = true;\n        break;\n"
        "      case OPT_ANIMA_SEQ_DIT:",
        "      case OPT_LOWRAM:\n        opts.lowram = true;\n        break;\n"
        "      case OPT_TEXT_SEQ_LEN:\n"
        "        opts.text_seq_len = std::stoi(pal::g_optArg);\n        break;\n"
        "      case OPT_ANIMA_SEQ_DIT:",
        "main switch",
    )
    text = replace_once(
        text,
        "  if (opts.model_dir.empty()) showHelpAndExit(\"Missing --model_dir\");\n  return opts;",
        "  if (opts.model_dir.empty()) showHelpAndExit(\"Missing --model_dir\");\n"
        "  if (opts.text_seq_len != 77 && opts.text_seq_len != 154)\n"
        "    showHelpAndExit(\"--text_seq_len must be 77 or 154\");\n"
        "  if (!opts.isSdxl() && opts.text_seq_len != 77)\n"
        "    showHelpAndExit(\"154-token context is SDXL-only\");\n"
        "  if (opts.text_seq_len == 154 && !opts.lowram)\n"
        "    showHelpAndExit(\"154-token context requires --lowram\");\n"
        "  return opts;",
        "main validation",
    )
    text = replace_once(
        text,
        "          vae_decoder_path, vae_encoder_path, opts.use_v_pred, opts.lowram);",
        "          vae_decoder_path, vae_encoder_path, opts.use_v_pred,\n"
        "          opts.text_seq_len, opts.lowram);",
        "main pipeline ctor",
    )
    text = replace_once(
        text,
        "static void registerTokenizeEndpoint(httplib::Server &svr,\n"
        "                                     TextEncoder *text_encoder) {\n"
        "  svr.Post(\"/tokenize\", [text_encoder](const httplib::Request &req,",
        "static void registerTokenizeEndpoint(httplib::Server &svr,\n"
        "                                     TextEncoder *text_encoder,\n"
        "                                     int clip_max_len) {\n"
        "  svr.Post(\"/tokenize\", [text_encoder, clip_max_len](const httplib::Request &req,",
        "main tokenize signature",
    )
    text = replace_once(
        text,
        "      const int max_len = text_encoder->isAnima() ? anima_text_seq_len : 77;",
        "      const int max_len =\n"
        "          text_encoder->isAnima() ? anima_text_seq_len : clip_max_len;",
        "main tokenize max",
    )
    text = replace_once(
        text,
        "  if (text_encoder) registerTokenizeEndpoint(svr, text_encoder.get());",
        "  if (text_encoder)\n"
        "    registerTokenizeEndpoint(svr, text_encoder.get(), opts.text_seq_len);",
        "main tokenize registration",
    )
    return text


def patch_backend(text: str) -> str:
    text = replace_once(
        text,
        "        val height: Int,\n        val listenOnAll: Boolean,",
        "        val height: Int,\n        val textSeqLen: Int,\n        val listenOnAll: Boolean,",
        "Backend config member",
    )
    text = replace_once(
        text,
        "        val height = intent.getIntExtra(\"height\", 512)\n        // Host mode is read",
        "        val height = intent.getIntExtra(\"height\", 512)\n"
        "        val modelDir = File(Model.getModelsDir(this), modelId)\n"
        "        // A 154 QNN UNet is a distinct static graph. Only an explicit\n"
        "        // marker opts a model in; missing/invalid markers fail closed to 77.\n"
        "        val textSeqLen = if (backendType == \"sdxl\") {\n"
        "            val marker = File(modelDir, \"TEXT_SEQ_LEN\")\n"
        "            runCatching { marker.readText().trim().toInt() }.getOrNull()\n"
        "                ?.takeIf { it == 154 } ?: 77\n"
        "        } else {\n"
        "            77\n"
        "        }\n"
        "        // Host mode is read",
        "Backend marker",
    )
    text = replace_once(
        text,
        "        return BackendConfig(modelId, backendType, width, height, listenOnAll)",
        "        return BackendConfig(modelId, backendType, width, height, textSeqLen, listenOnAll)",
        "Backend config return",
    )
    text = replace_once(
        text,
        "        Log.i(TAG, \"backend start, model: $modelId, resolution: $width×$height\")",
        "        Log.i(TAG, \"backend start, model: $modelId, resolution: $width×$height, textSeq=${config.textSeqLen}\")",
        "Backend log",
    )
    text = replace_once(
        text,
        "            if (backendType != \"sd15cpu\" && backendType != BACKEND_TYPE_UPSCALER) {\n"
        "                command += listOf(\"--lib_dir\", runtimeDir.absolutePath)\n"
        "            }",
        "            if (backendType != \"sd15cpu\" && backendType != BACKEND_TYPE_UPSCALER) {\n"
        "                command += listOf(\"--lib_dir\", runtimeDir.absolutePath)\n"
        "            }\n"
        "            if (backendType == \"sdxl\") {\n"
        "                command += listOf(\"--text_seq_len\", config.textSeqLen.toString())\n"
        "            }",
        "Backend CLI seq",
    )
    text = replace_once(
        text,
        "            if (backendType == \"sdxl\" && preferences.getBoolean(\"sdxl_lowram\", true)) {\n"
        "                command += \"--lowram\"\n"
        "            }",
        "            if (backendType == \"sdxl\" &&\n"
        "                (config.textSeqLen == 154 || preferences.getBoolean(\"sdxl_lowram\", true))\n"
        "            ) {\n"
        "                command += \"--lowram\"\n"
        "            }",
        "Backend force lowram",
    )
    return text


def patch_h1_identity(root: Path) -> None:
    gradle = root / "app/build.gradle.kts"
    s = gradle.read_text(encoding="utf-8")
    s = replace_once(s, 'applicationId = "io.github.xororz.localdream.s24uharness"',
                     'applicationId = "io.github.xororz.localdream.s24u154"', "identity app id")
    s = replace_once(s, "versionCode = 7401", "versionCode = 74154", "identity version code")
    s = replace_once(s, 'versionName = "2.8.1-s24u-h1"',
                     'versionName = "2.8.1-s24u154-r1"', "identity version name")
    gradle.write_text(s, encoding="utf-8")

    strings = root / "app/src/main/res/values/strings.xml"
    s = strings.read_text(encoding="utf-8")
    s = replace_once(s, ">S24U Image Harness</string>", ">Local Dream S24U 154</string>", "identity app name")
    strings.write_text(s, encoding="utf-8")

    screen = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    s = screen.read_text(encoding="utf-8")
    s = replace_once(s, 'text = "S24U HARNESS · RAW",',
                     'text = "S24U 154 · NPU LONG PROMPT",', "harness card title")
    s = replace_once(
        s,
        'text = "No LLM semantic rewrite. Basic build: optional Safety Checker is not loaded.",',
        'text = "77-token legacy + marker-gated 154-token SDXL. RAW prompt, no semantic rewrite.",',
        "harness card description",
    )
    screen.write_text(s, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_native_154.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()

    paths = {rel: verify_exact(root, rel) for rel in EXPECTED_GIT_BLOBS}
    helper_src = Path(__file__).resolve().parent / "LongPromptChunking.hpp"
    helper_dst = root / "app/src/main/cpp/src/LongPromptChunking.hpp"
    helper_dst.write_text(helper_src.read_text(encoding="utf-8"), encoding="utf-8")

    transforms = {
        "app/src/main/cpp/src/TextEncoder.hpp": patch_text_encoder,
        "app/src/main/cpp/src/PipelineSdxl.hpp": patch_pipeline,
        "app/src/main/cpp/src/QnnModel.hpp": patch_qnn,
        "app/src/main/cpp/src/main.cpp": patch_main,
        "app/src/main/java/io/github/xororz/localdream/service/BackendService.kt": patch_backend,
    }
    for rel, transform in transforms.items():
        p = paths[rel]
        p.write_text(transform(p.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"PATCHED {rel}")

    patch_h1_identity(root)
    print("S24U_154_NATIVE_PATCH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
