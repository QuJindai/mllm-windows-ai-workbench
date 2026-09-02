#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  float denoise_strength = 0.6f;\n  bool img2img = false;\n",
        "  float denoise_strength = 0.6f;\n"
        "  // H6R3 semantic-fidelity lab. Normal production behavior stays\n"
        "  // equal_mean unless the phone UI explicitly selects a diagnostic mode.\n"
        "  std::string fusion_mode = \"equal_mean\";\n"
        "  float fusion_alpha = 0.5f;\n"
        "  bool img2img = false;\n",
        "generation fusion fields",
    )
    text = replace_once(
        text,
        "  float negative_effective_weight = 0.0f;\n};\n",
        "  float negative_effective_weight = 0.0f;\n"
        "  std::string fusion_mode = \"equal_mean\";\n"
        "  float fusion_alpha = 0.5f;\n"
        "  std::vector<float> fusion_weights;\n"
        "};\n",
        "trace fusion fields",
    )
    text = replace_once(
        text,
        "    Conditioning &cond = conds.front();\n    auto clip_dur = elapsedMs(clip_start);\n",
        r'''    Conditioning &cond = conds.front();
    // Token weights are only computed for explicit experimental modes, so the
    // default equal-mean path adds no extra tokenizer work or model calls.
    const bool request_skip_uncond = canSkipUncond() && (req.cfg == 1.0f);
    std::vector<float> fusion_token_weights(conds.size(), 1.0f);
    if (!isAnima() &&
        (req.fusion_mode == "token_weighted" ||
         req.fusion_mode == "anchor_residual")) {
      auto fusion_pos_chunks = text_encoder_.splitPromptChunks(req.prompt);
      auto fusion_neg_chunks = text_encoder_.splitPromptChunks(req.negative_prompt);
      for (size_t j = 0; j < conds.size(); ++j) {
        int pos_tokens = j < fusion_pos_chunks.size()
                             ? text_encoder_.promptContentTokenCount(fusion_pos_chunks[j])
                             : 0;
        int neg_tokens = j < fusion_neg_chunks.size()
                             ? text_encoder_.promptContentTokenCount(fusion_neg_chunks[j])
                             : 0;
        const int effective_tokens = request_skip_uncond
                                         ? pos_tokens
                                         : std::max(pos_tokens, neg_tokens);
        fusion_token_weights[j] =
            static_cast<float>(std::max(1, effective_tokens));
      }
    }
    auto clip_dur = elapsedMs(clip_start);
''',
        "fusion token weights",
    )
    text = replace_once(
        text,
        "      const bool skip_uncond = canSkipUncond() && (req.cfg == 1.0f);\n",
        "      const bool skip_uncond = request_skip_uncond;\n",
        "request-level skip-uncond reuse",
    )
    text = replace_once(
        text,
        "      std::vector<xt::xarray<float>> chunk_predictions;\n"
        "      chunk_predictions.reserve(conds.size());\n"
        "      xt::xarray<float> noise_pred = xt::zeros<float>(shape);\n"
        "      for (auto &chunk_cond : conds) {\n",
        r'''      std::vector<xt::xarray<float>> chunk_predictions;
      chunk_predictions.reserve(conds.size());
      xt::xarray<float> noise_pred = xt::zeros<float>(shape);
      const size_t active_chunk_count =
          req.fusion_mode == "first_only" ? 1 : conds.size();
      for (size_t chunk_index = 0; chunk_index < active_chunk_count; ++chunk_index) {
        auto &chunk_cond = conds[chunk_index];
''',
        "active fusion chunks",
    )
    text = replace_once(
        text,
        "      noise_pred = xt::eval(noise_pred / (float)conds.size());\n\n"
        "      auto step_dur = elapsedMs(step_start_time);\n",
        r'''      std::vector<float> fusion_effective_weights(conds.size(), 0.0f);
      if (req.fusion_mode == "equal_mean") {
        noise_pred = xt::eval(noise_pred / (float)conds.size());
        const float w = 1.0f / static_cast<float>(conds.size());
        std::fill(fusion_effective_weights.begin(), fusion_effective_weights.end(), w);
      } else if (req.fusion_mode == "first_only") {
        noise_pred = xt::eval(chunk_predictions.front());
        fusion_effective_weights[0] = 1.0f;
      } else if (req.fusion_mode == "token_weighted") {
        noise_pred = xt::zeros<float>(shape);
        float weight_sum = 0.0f;
        for (size_t j = 0; j < chunk_predictions.size(); ++j)
          weight_sum += fusion_token_weights[j];
        weight_sum = std::max(weight_sum, 1.0f);
        for (size_t j = 0; j < chunk_predictions.size(); ++j) {
          const float w = fusion_token_weights[j] / weight_sum;
          fusion_effective_weights[j] = w;
          noise_pred = xt::eval(noise_pred + w * chunk_predictions[j]);
        }
      } else if (req.fusion_mode == "anchor_residual") {
        xt::xarray<float> anchor = xt::eval(chunk_predictions.front());
        noise_pred = anchor;
        if (chunk_predictions.size() > 1) {
          xt::xarray<float> residual = xt::zeros<float>(shape);
          float residual_weight_sum = 0.0f;
          for (size_t j = 1; j < chunk_predictions.size(); ++j)
            residual_weight_sum += fusion_token_weights[j];
          residual_weight_sum = std::max(residual_weight_sum, 1.0f);
          for (size_t j = 1; j < chunk_predictions.size(); ++j) {
            const float w = fusion_token_weights[j] / residual_weight_sum;
            residual = xt::eval(
                residual + w * (chunk_predictions[j] - anchor));
            fusion_effective_weights[j] = req.fusion_alpha * w;
          }
          residual = xt::eval(residual);
          noise_pred = xt::eval(anchor + req.fusion_alpha * residual);
          fusion_effective_weights[0] = 1.0f - req.fusion_alpha;
        } else {
          fusion_effective_weights[0] = 1.0f;
        }
      }

      auto step_dur = elapsedMs(step_start_time);
''',
        "fusion algorithms",
    )
    text = replace_once(
        text,
        "      unet_trace.negative_effective_weight = negative_effective_weight;\n"
        "      emit_trace(unet_trace);\n",
        "      unet_trace.negative_effective_weight = negative_effective_weight;\n"
        "      unet_trace.fusion_mode = req.fusion_mode;\n"
        "      unet_trace.fusion_alpha = req.fusion_alpha;\n"
        "      unet_trace.fusion_weights = fusion_effective_weights;\n"
        "      emit_trace(unet_trace);\n",
        "fusion trace values",
    )
    path.write_text(text, encoding="utf-8")


def patch_main(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'''      auto req = std::make_shared<GenerationRequest>(parseGenerationRequest(
          json, pipeline->isSdxl(), pipeline->isAnima(),
          pipeline->supportsImg2Img(), pipeline->supportsUltrafix()));

      std::cout << "Req Rcvd: P:" << req->prompt
''',
        r'''      auto req = std::make_shared<GenerationRequest>(parseGenerationRequest(
          json, pipeline->isSdxl(), pipeline->isAnima(),
          pipeline->supportsImg2Img(), pipeline->supportsUltrafix()));
      req->fusion_mode = json.value("fusion_mode", std::string("equal_mean"));
      if (req->fusion_mode != "equal_mean" && req->fusion_mode != "first_only" &&
          req->fusion_mode != "token_weighted" &&
          req->fusion_mode != "anchor_residual") {
        req->fusion_mode = "equal_mean";
      }
      req->fusion_alpha = std::max(
          0.0f, std::min(1.0f, json.value("fusion_alpha", 0.5f)));

      std::cout << "Req Rcvd: P:" << req->prompt
''',
        "fusion request parser",
    )
    text = replace_once(
        text,
        "                << \" Denoise:\" << req->denoise_strength\n"
        "                << \" ShowProcess:\" << req->show_diffusion_process\n",
        "                << \" Denoise:\" << req->denoise_strength\n"
        "                << \" Fusion:\" << req->fusion_mode\n"
        "                << \" FusionAlpha:\" << req->fusion_alpha\n"
        "                << \" ShowProcess:\" << req->show_diffusion_process\n",
        "fusion request log",
    )
    text = replace_once(
        text,
        "                        {\"negative_effective_weight\", trace.negative_effective_weight},\n"
        "                        {\"image_base64\", trace.image_base64}};\n",
        "                        {\"negative_effective_weight\", trace.negative_effective_weight},\n"
        "                        {\"fusion_mode\", trace.fusion_mode},\n"
        "                        {\"fusion_alpha\", trace.fusion_alpha},\n"
        "                        {\"fusion_weights\", trace.fusion_weights},\n"
        "                        {\"image_base64\", trace.image_base64}};\n",
        "fusion serialization",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v7_fusion_core.py <h6r3-task2-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_pipeline(root)
    patch_main(root)
    print("S24U_IMAGE_HARNESS_H6R3_FUSION_CORE_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
