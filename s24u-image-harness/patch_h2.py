#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    return updated


def patch_gradle(root: Path) -> None:
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'applicationId = "io.github.xororz.localdream"',
        'applicationId = "io.github.xororz.localdream.s24uharness"',
        "applicationId",
    )
    text = replace_once(text, "versionCode = 74", "versionCode = 7402", "versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1"',
        'versionName = "2.8.1-s24u-h2"',
        "versionName",
    )
    text = replace_once(
        text,
        '        debug {\n//            signingConfig = signingConfigs.getByName("release")\n        }',
        '        debug {\n            // H2+ uses one stable TEST-ONLY signing identity so Android in-place upgrades preserve files/models.\n            signingConfig = signingConfigs.getByName("release")\n        }',
        "debug stable signing",
    )
    path.write_text(text, encoding="utf-8")


def patch_strings(root: Path) -> None:
    path = root / "app/src/main/res/values/strings.xml"
    text = path.read_text(encoding="utf-8")
    text = regex_once(
        text,
        r'(<string\s+name="app_name"[^>]*>)(.*?)(</string>)',
        r'\1S24U Image Harness\3',
        "app_name",
        re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    text = regex_once(
        text,
        r'promptField\.replaceText\(if \(isFirstRun\) defaults\.prompt else prefs\.prompt\)',
        'promptField.replaceText(if (isFirstRun) "" else prefs.prompt)',
        "PURE RAW first-run positive",
    )
    text = regex_once(
        text,
        r'negativePromptField\.replaceText\(\s*if \(isFirstRun\) defaults\.negativePrompt else prefs\.negativePrompt,\s*\)',
        'negativePromptField.replaceText(\n                if (isFirstRun) "" else prefs.negativePrompt,\n            )',
        "PURE RAW first-run negative",
        re.DOTALL,
    )
    text = replace_once(
        text,
        "promptField.replaceText(defaults.prompt)",
        'promptField.replaceText("")',
        "PURE RAW reset positive",
    )
    text = replace_once(
        text,
        "negativePromptField.replaceText(defaults.negativePrompt)",
        'negativePromptField.replaceText("")',
        "PURE RAW reset negative",
    )

    anchor = """                        ControlledPromptTagTextField(\n                            controller = promptField,\n"""
    card = """                        Card(\n                            modifier = Modifier.fillMaxWidth(),\n                            colors = CardDefaults.cardColors(\n                                containerColor = MaterialTheme.colorScheme.surfaceVariant,\n                            ),\n                        ) {\n                            val positiveChunks =\n                                (((promptField.tokenCount - 2).coerceAtLeast(0) + 74) / 75)\n                                    .coerceIn(1, 4)\n                            val negativeChunks =\n                                (((negativePromptField.tokenCount - 2).coerceAtLeast(0) + 74) / 75)\n                                    .coerceIn(1, 4)\n                            Column(\n                                modifier = Modifier.padding(12.dp),\n                                verticalArrangement = Arrangement.spacedBy(4.dp),\n                            ) {\n                                Text(\n                                    text = \"S24U HARNESS · PURE RAW\",\n                                    style = MaterialTheme.typography.titleSmall,\n                                    fontWeight = FontWeight.Bold,\n                                )\n                                Text(\n                                    text = \"No semantic rewrite · no model default prompt · Basic build has no optional Safety Checker.\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"RAW INPUT → ${promptField.text.ifBlank { \"(empty)\" }}\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"NEGATIVE → ${negativePromptField.text.ifBlank { \"(empty)\" }}\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"TOKENS → ${promptField.tokenCount}/${promptField.tokenMax}\",\n                                    style = MaterialTheme.typography.labelSmall,\n                                )\n                                Text(\n                                    text = \"POS CHUNKS → $positiveChunks × fixed-77 CLIP · NEG CHUNKS → $negativeChunks\",\n                                    style = MaterialTheme.typography.labelSmall,\n                                )\n                            }\n                        }\n\n"""
    text = replace_once(text, anchor, card + anchor, "PURE RAW trace card")
    path.write_text(text, encoding="utf-8")


def patch_text_encoder(root: Path) -> None:
    path = root / "app/src/main/cpp/src/TextEncoder.hpp"
    text = path.read_text(encoding="utf-8")

    constants = """
// S24U H2 long-prompt harness. Every individual CLIP/QNN invocation stays at
// the upstream static shape (77 = BOS + 75 content + EOS/PAD). Long prompts
// are split into at most four real fixed-shape passes; no 154/302-token QNN
// graph or model-weight replacement is required.
inline constexpr int kS24uClipChunkLen = 77;
inline constexpr int kS24uClipContentTokens = 75;
inline constexpr int kS24uClipChunks = 4;
inline constexpr int kS24uClipEffectiveMaxLength =
    kS24uClipContentTokens * kS24uClipChunks + 2;

"""
    text = replace_once(text, "class TextEncoder {", constants + "class TextEncoder {", "long-prompt constants")

    decode_anchor = """  std::string decode(const std::vector<int> &ids) {\n    return tokenizer_->Decode(ids);\n  }\n"""
    splitter = r'''

  // Split a weighted SD/SDXL prompt into normalized text chunks whose
  // *content* token count never exceeds 75. The existing processWeightedPrompt
  // then adds BOS/EOS/PAD and executes the unchanged 77-slot QNN CLIP graph.
  // PromptProcessor has already collapsed nested weights; re-emitting a leaf
  // as (text:weight) preserves the effective weight across chunk boundaries.
  std::vector<std::string> splitPromptChunks(
      const std::string &prompt_text, int max_chunks = kS24uClipChunks) {
    if (anima_) return {prompt_text};
    if (!tokenizer_) return {prompt_text};
    if (max_chunks < 1) max_chunks = 1;

    auto parsed = promptProcessor_.process(prompt_text);
    std::vector<std::string> chunks;
    std::string current;
    int current_tokens = 0;

    auto escape_piece = [](const std::string &s) {
      std::string out;
      out.reserve(s.size() + 8);
      for (char c : s) {
        if (c == '\\' || c == '(' || c == ')' || c == '[' || c == ']' ||
            c == ':' || c == ',') {
          out.push_back('\\');
        }
        out.push_back(c);
      }
      return out;
    };

    auto render_piece = [&](const std::string &piece, float weight) {
      std::string escaped = escape_piece(piece);
      if (weight > 0.9999f && weight < 1.0001f) return escaped;
      return std::string("(") + escaped + ":" + std::to_string(weight) + ")";
    };

    auto append_piece = [&](const std::string &piece, float weight) {
      if (piece.empty()) return;
      std::string rendered = render_piece(piece, weight);
      if (!current.empty()) {
        if (piece == ",") {
          // No space before comma.
        } else {
          current.push_back(' ');
        }
      }
      current += rendered;
    };

    auto flush = [&]() {
      if (!current.empty() && (int)chunks.size() < max_chunks) {
        chunks.push_back(current);
      }
      current.clear();
      current_tokens = 0;
    };

    const int dim1 = 768;
    const int dim2 = text_embedding_size_2;
    for (const auto &token : parsed) {
      if ((int)chunks.size() >= max_chunks) break;

      int token_count = 0;
      if (token.is_embedding) {
        if (!token.embedding_data.empty())
          token_count = (int)token.embedding_data.size() / dim1;
        else if (sdxl_ && !token.embedding_data_2.empty())
          token_count = (int)token.embedding_data_2.size() / dim2;

        if (token_count > kS24uClipContentTokens) {
          throw std::invalid_argument(
              "textual-inversion embedding exceeds one 75-token CLIP chunk");
        }
        if (current_tokens > 0 &&
            current_tokens + token_count > kS24uClipContentTokens) {
          flush();
          if ((int)chunks.size() >= max_chunks) break;
        }
        append_piece(token.text, token.weight);
        current_tokens += token_count;
        if (current_tokens >= kS24uClipContentTokens) flush();
        continue;
      }

      std::string remaining = token.text;
      while (!remaining.empty() && (int)chunks.size() < max_chunks) {
        int budget = kS24uClipContentTokens - current_tokens;
        if (budget <= 0) {
          flush();
          continue;
        }

        int remaining_tokens = (int)tokenizer_->Encode(remaining).size();
        if (remaining_tokens <= budget) {
          append_piece(remaining, token.weight);
          current_tokens += remaining_tokens;
          remaining.clear();
          if (current_tokens >= kS24uClipContentTokens) flush();
          continue;
        }

        size_t prefix =
            prefixBytesWithinBudget(remaining, budget, tokenizer_.get());
        if (prefix == 0) {
          if (current_tokens > 0) {
            flush();
            continue;
          }
          throw std::invalid_argument("unable to split prompt at CLIP token boundary");
        }
        std::string piece = remaining.substr(0, prefix);
        append_piece(piece, token.weight);
        current_tokens += (int)tokenizer_->Encode(piece).size();
        remaining.erase(0, prefix);
        flush();
      }
    }

    if (!current.empty() && (int)chunks.size() < max_chunks) flush();
    if (chunks.empty()) chunks.push_back("");
    return chunks;
  }
'''
    text = replace_once(text, decode_anchor, decode_anchor + splitter, "prompt chunk splitter")
    path.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  Conditioning encodePrompts(const GenerationRequest &req);\n",
        "  Conditioning encodePrompts(const GenerationRequest &req);\n"
        "  std::vector<Conditioning> encodePromptChunks(const GenerationRequest &req);\n",
        "encodePromptChunks declaration",
    )

    impl_anchor = "inline xt::xarray<float> Pipeline::encodeImageToLatent(\n"
    chunk_impl = r'''
inline std::vector<Conditioning> Pipeline::encodePromptChunks(
    const GenerationRequest &req) {
  if (isAnima()) return {encodePrompts(req)};

  auto positive_chunks = text_encoder_.splitPromptChunks(req.prompt);
  auto negative_chunks = text_encoder_.splitPromptChunks(req.negative_prompt);
  size_t count = std::max(positive_chunks.size(), negative_chunks.size());
  if (count <= 1) return {encodePrompts(req)};
  count = std::min(count, (size_t)kS24uClipChunks);

  QNN_INFO("S24U H2 long prompt: %zu fixed-77 conditioning chunks", count);
  std::vector<Conditioning> result;
  result.reserve(count);
  for (size_t i = 0; i < count; ++i) {
    const std::string chunk_prompt =
        i < positive_chunks.size() ? positive_chunks[i] : std::string();
    const std::string chunk_negative =
        i < negative_chunks.size() ? negative_chunks[i] : std::string();

    // encodePrompts() ultimately calls processPromptPair(..., cond.seq_len),
    // and textSeqLen() remains exactly 77 for SD/SDXL. Only prompt text varies;
    // model/QNN tensor shapes do not.
    GenerationRequest chunk_req;
    chunk_req.prompt = chunk_prompt;
    chunk_req.negative_prompt = chunk_negative;
    chunk_req.width = req.width;
    chunk_req.height = req.height;
    result.push_back(encodePrompts(chunk_req));
  }
  return result;
}

'''
    text = replace_once(text, impl_anchor, chunk_impl + impl_anchor, "encodePromptChunks implementation")

    text = replace_once(
        text,
        "    Conditioning cond = encodePrompts(req);\n",
        "    std::vector<Conditioning> conds = encodePromptChunks(req);\n"
        "    Conditioning &cond = conds.front();\n",
        "generate conditioning vector",
    )

    noise_pattern = re.compile(
        r"      xt::xarray<float> noise_pred;\n"
        r"      if \(unet_tiled\) \{.*?"
        r"      \}\n\n"
        r"      auto step_dur = elapsedMs\(step_start_time\);",
        re.DOTALL,
    )
    replacement = r'''      xt::xarray<float> noise_pred = xt::zeros<float>(shape);
      for (auto &chunk_cond : conds) {
        xt::xarray<float> chunk_pred;
        if (unet_tiled) {
          chunk_pred =
              runUnetTiled(req, latents_scaled, static_cast<int>(current_ts),
                           skip_uncond, chunk_cond);
        } else {
          std::vector<float> latents_in_vec;
          latents_in_vec.reserve(batch_size * single_latent_size);
          latents_in_vec.insert(latents_in_vec.end(), latents_scaled.begin(),
                                latents_scaled.end());
          latents_in_vec.insert(latents_in_vec.end(), latents_scaled.begin(),
                                latents_scaled.end());
          std::vector<float> unet_out_latents(batch_size * single_latent_size);

          runUnetStep(req, latents_in_vec.data(), current_ts, skip_uncond,
                      chunk_cond, unet_out_latents.data());

          if (skip_uncond) {
            std::vector<float> cond_only(
                unet_out_latents.begin() + single_latent_size,
                unet_out_latents.end());
            chunk_pred = xt::adapt(cond_only, shape);
          } else {
            xt::xarray<float> noise_pred_batch =
                xt::adapt(unet_out_latents, shape_batch2);
            xt::xarray<float> uncond = xt::view(noise_pred_batch, 0);
            xt::xarray<float> txt = xt::view(noise_pred_batch, 1);
            chunk_pred = xt::eval(uncond + req.cfg * (txt - uncond));
          }
        }
        noise_pred = xt::eval(noise_pred + chunk_pred);
      }
      noise_pred = xt::eval(noise_pred / (float)conds.size());

      auto step_dur = elapsedMs(step_start_time);'''
    text, count = noise_pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"multi-chunk UNet fusion: expected exactly one block, found {count}")

    path.write_text(text, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "      const int max_len = text_encoder->isAnima() ? anima_text_seq_len : 77;",
        "      const int max_len = text_encoder->isAnima()\n"
        "                              ? anima_text_seq_len\n"
        "                              : kS24uClipEffectiveMaxLength;",
        "expanded /tokenize maximum",
    )
    path.write_text(text, encoding="utf-8")


def patch_cmake(root: Path) -> None:
    path = root / "app/src/main/cpp/CMakeLists.txt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "# QNN SDK PATH\nset(QNN_SDK_ROOT /data/qairt/2.39.0.250926)",
        "# QNN SDK PATH: CI can provide a downloaded QAIRT Community SDK; keep upstream local fallback.\n"
        "if(DEFINED ENV{QNN_SDK_ROOT})\n"
        "    set(QNN_SDK_ROOT \"$ENV{QNN_SDK_ROOT}\")\n"
        "else()\n"
        "    set(QNN_SDK_ROOT /data/qairt/2.39.0.250926)\n"
        "endif()",
        "QNN SDK environment override",
    )
    path.write_text(text, encoding="utf-8")

    preset_path = root / "app/src/main/cpp/CMakePresets.json"
    presets = preset_path.read_text(encoding="utf-8")
    presets = regex_once(
        presets,
        r',\n\s*"environment"\s*:\s*\{\s*"ANDROID_NDK_ROOT"\s*:\s*"/data/android-ndk-r28"\s*\}',
        "",
        "remove hard-coded NDK preset environment",
        re.DOTALL,
    )
    preset_path.write_text(presets, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h2.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_strings(root)
    patch_screen(root)
    patch_text_encoder(root)
    patch_pipeline(root)
    patch_main_cpp(root)
    patch_cmake(root)
    print("S24U_IMAGE_HARNESS_H2_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
