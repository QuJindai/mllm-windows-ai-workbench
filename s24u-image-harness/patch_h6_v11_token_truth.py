#!/usr/bin/env python3
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_gradle(root: Path) -> None:
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7409", "versionCode = 7410", "H6R4 versionCode")
    text = replace_once(text, 'versionName = "2.8.1-s24u-h6r3"', 'versionName = "2.8.1-s24u-h6r4"', "H6R4 versionName")
    path.write_text(text, encoding="utf-8")


def patch_text_encoder(root: Path) -> None:
    path = root / "app/src/main/cpp/src/TextEncoder.hpp"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  std::vector<float> weighted_embeddings_2;  // SDXL: 77*1280\n",
        "  std::vector<float> weighted_embeddings_2;  // SDXL: 77*1280\n"
        "  // H6R4: exact unpadded content stream after PromptProcessor cleanup.\n"
        "  // These ids/weights are the source of truth for long-prompt slicing.\n"
        "  std::vector<int> content_ids;\n"
        "  std::vector<float> content_weights;\n",
        "ProcessedPrompt content truth fields",
    )
    text = replace_once(
        text,
        "  std::vector<float> positive_embeddings_2;  // SDXL (77*1280)\n",
        "  std::vector<float> positive_embeddings_2;  // SDXL (77*1280)\n"
        "  std::vector<int> negative_content_ids;\n"
        "  std::vector<int> positive_content_ids;\n"
        "  std::vector<float> negative_content_weights;\n"
        "  std::vector<float> positive_content_weights;\n",
        "ProcessedPromptPair content truth fields",
    )

    text = replace_once(
        text,
        "    std::vector<int> ids;\n    std::vector<float> weights;\n\n    int current_pos = 1;\n",
        "    std::vector<int> ids;\n"
        "    std::vector<float> weights;\n"
        "    std::vector<int> content_ids;\n"
        "    std::vector<float> content_weights;\n\n"
        "    int current_pos = 1;\n",
        "single-prompt content vectors",
    )
    text = replace_once(
        text,
        "          ids.push_back(49407);\n          if (!token.embedding_data.empty()) {\n",
        "          ids.push_back(49407);\n"
        "          content_ids.push_back(49407);\n"
        "          content_weights.push_back(token.weight);\n"
        "          if (!token.embedding_data.empty()) {\n",
        "single-prompt TI content ids",
    )
    text = replace_once(
        text,
        "          ids.push_back(tid);\n\n          if (current_pos < max_len) {\n",
        "          ids.push_back(tid);\n"
        "          content_ids.push_back(tid);\n"
        "          content_weights.push_back(token.weight);\n\n"
        "          if (current_pos < max_len) {\n",
        "single-prompt text content ids",
    )
    text = replace_once(
        text,
        "    result.ids = ids;\n\n    // SDXL encoder 2 uses pad id 0 instead of 49407 after the first EOS.\n",
        "    result.ids = ids;\n"
        "    result.content_ids = content_ids;\n"
        "    result.content_weights = content_weights;\n\n"
        "    // SDXL encoder 2 uses pad id 0 instead of 49407 after the first EOS.\n",
        "single-prompt content result",
    )

    pair_anchor = '''    result.negative_embeddings_2 = neg_result.weighted_embeddings_2;
    result.positive_embeddings_2 = pos_result.weighted_embeddings_2;

    if (anima_) {
'''
    pair_new = '''    result.negative_embeddings_2 = neg_result.weighted_embeddings_2;
    result.positive_embeddings_2 = pos_result.weighted_embeddings_2;
    result.negative_content_ids = neg_result.content_ids;
    result.positive_content_ids = pos_result.content_ids;
    result.negative_content_weights = neg_result.content_weights;
    result.positive_content_weights = pos_result.content_weights;

    if (anima_) {
'''
    text = replace_once(text, pair_anchor, pair_new, "single pair content truth")

    anchor = "  // Count the actual prompt content tokens after prompt-weight syntax has\n"
    helper = r'''  // H6R4 token-preserving long-prompt path. PromptProcessor is run once,
  // each cleaned leaf is tokenized once, and the resulting weighted token
  // stream is sliced directly into <=75-content-token CLIP chunks. No chunk is
  // converted back to escaped text and re-tokenized for inference.
  std::vector<int> promptContentTokenIds(const std::string &prompt_text) {
    std::vector<int> ids;
    if (!tokenizer_) return ids;
    auto tokens = promptProcessor_.process(prompt_text);
    const int dim1 = 768;
    const int dim2 = text_embedding_size_2;
    for (const auto &token : tokens) {
      if (token.is_embedding) {
        int count = 0;
        if (!token.embedding_data.empty())
          count = static_cast<int>(token.embedding_data.size()) / dim1;
        else if (sdxl_ && !token.embedding_data_2.empty())
          count = static_cast<int>(token.embedding_data_2.size()) / dim2;
        ids.insert(ids.end(), count, 49407);
      } else {
        auto piece = tokenizer_->Encode(token.text);
        ids.insert(ids.end(), piece.begin(), piece.end());
      }
    }
    return ids;
  }

  std::vector<std::vector<int>> promptContentTokenIdChunks(
      const std::string &prompt_text, int max_chunks = kS24uClipChunks) {
    std::vector<std::vector<int>> chunks;
    auto ids = promptContentTokenIds(prompt_text);
    if (max_chunks < 1) max_chunks = 1;
    for (size_t offset = 0;
         offset < ids.size() && static_cast<int>(chunks.size()) < max_chunks;
         offset += kS24uClipContentTokens) {
      const size_t end = std::min(
          ids.size(), offset + static_cast<size_t>(kS24uClipContentTokens));
      chunks.emplace_back(ids.begin() + offset, ids.begin() + end);
    }
    if (chunks.empty()) chunks.emplace_back();
    return chunks;
  }

  std::vector<ProcessedPrompt> processWeightedPromptChunks(
      const std::string &prompt_text, int max_chunks = kS24uClipChunks,
      int max_len = kS24uClipChunkLen) {
    if (anima_) return {processAnimaPrompt(prompt_text, max_len)};
    if (!tokenizer_) return {processWeightedPrompt(prompt_text, max_len)};
    if (max_chunks < 1) max_chunks = 1;
    const int content_limit = std::max(1, max_len - 2);
    const int dim1 = 768;
    const int dim2 = text_embedding_size_2;

    struct WeightedUnit {
      int id = 0;
      float weight = 1.0f;
      bool is_embedding = false;
      std::vector<float> embedding_1;
      std::vector<float> embedding_2;
    };
    std::vector<WeightedUnit> units;
    auto tokens = promptProcessor_.process(prompt_text);
    for (const auto &token : tokens) {
      if (token.is_embedding) {
        int count = 0;
        if (!token.embedding_data.empty())
          count = static_cast<int>(token.embedding_data.size()) / dim1;
        else if (sdxl_ && !token.embedding_data_2.empty())
          count = static_cast<int>(token.embedding_data_2.size()) / dim2;
        for (int row = 0; row < count; ++row) {
          WeightedUnit unit;
          unit.id = 49407;
          unit.weight = token.weight;
          unit.is_embedding = true;
          if (!token.embedding_data.empty()) {
            unit.embedding_1.assign(
                token.embedding_data.begin() + static_cast<size_t>(row) * dim1,
                token.embedding_data.begin() + static_cast<size_t>(row + 1) * dim1);
          }
          if (sdxl_ && !token.embedding_data_2.empty()) {
            unit.embedding_2.assign(
                token.embedding_data_2.begin() + static_cast<size_t>(row) * dim2,
                token.embedding_data_2.begin() + static_cast<size_t>(row + 1) * dim2);
          }
          units.push_back(std::move(unit));
        }
      } else {
        auto token_ids = tokenizer_->Encode(token.text);
        for (int id : token_ids) {
          WeightedUnit unit;
          unit.id = id;
          unit.weight = token.weight;
          units.push_back(std::move(unit));
        }
      }
    }

    auto build_chunk = [&](size_t begin, size_t end) {
      ProcessedPrompt result;
      std::vector<int> ids;
      std::vector<float> weights;
      ids.reserve(max_len);
      weights.reserve(max_len);
      ids.push_back(49406);
      std::vector<float> embeddings(static_cast<size_t>(max_len) * dim1, 0.0f);
      std::vector<float> embeddings_2;
      if (sdxl_)
        embeddings_2.assign(static_cast<size_t>(max_len) * dim2, 0.0f);
      int pos = 1;
      for (size_t i = begin; i < end && pos < max_len - 1; ++i, ++pos) {
        const auto &unit = units[i];
        ids.push_back(unit.id);
        weights.push_back(unit.weight);
        result.content_ids.push_back(unit.id);
        result.content_weights.push_back(unit.weight);
        if (unit.is_embedding) {
          if (!unit.embedding_1.empty()) {
            for (int j = 0; j < dim1; ++j)
              embeddings[static_cast<size_t>(pos) * dim1 + j] =
                  unit.embedding_1[j] * unit.weight;
          }
          if (sdxl_ && !unit.embedding_2.empty()) {
            for (int j = 0; j < dim2; ++j)
              embeddings_2[static_cast<size_t>(pos) * dim2 + j] =
                  unit.embedding_2[j] * unit.weight;
          }
        }
      }
      while (ids.size() < static_cast<size_t>(max_len)) {
        ids.push_back(49407);
        weights.push_back(1.0f);
      }
      result.ids = ids;
      if (sdxl_) {
        std::vector<int> ids2 = ids;
        int eos_pos = -1;
        for (int i = 1; i < max_len; ++i) {
          if (ids2[i] == 49407) { eos_pos = i; break; }
        }
        if (eos_pos >= 0)
          for (int i = eos_pos + 1; i < max_len; ++i) ids2[i] = 0;
        result.ids_2 = ids2;
      }
      if (!token_emb_.empty() && !pos_emb_.empty())
        applyTokenAndPosEmb(ids, weights, token_emb_, pos_emb_, dim1, max_len,
                            embeddings);
      if (sdxl_ && !token_emb_2_.empty() && !pos_emb_2_.empty())
        applyTokenAndPosEmb(result.ids_2, weights, token_emb_2_, pos_emb_2_, dim2,
                            max_len, embeddings_2);
      result.weighted_embeddings = std::move(embeddings);
      result.weighted_embeddings_2 = std::move(embeddings_2);
      return result;
    };

    std::vector<ProcessedPrompt> chunks;
    const size_t max_units = static_cast<size_t>(max_chunks) * content_limit;
    const size_t retained = std::min(units.size(), max_units);
    for (size_t begin = 0;
         begin < retained && static_cast<int>(chunks.size()) < max_chunks;
         begin += content_limit) {
      const size_t end = std::min(retained, begin + static_cast<size_t>(content_limit));
      chunks.push_back(build_chunk(begin, end));
    }
    if (chunks.empty()) chunks.push_back(build_chunk(0, 0));
    return chunks;
  }

  std::vector<ProcessedPromptPair> processPromptPairChunks(
      const std::string &positive, const std::string &negative,
      int max_chunks = kS24uClipChunks, int max_len = kS24uClipChunkLen) {
    if (anima_) return {processPromptPair(positive, negative, max_len)};
    auto positives = processWeightedPromptChunks(positive, max_chunks, max_len);
    auto negatives = processWeightedPromptChunks(negative, max_chunks, max_len);
    size_t count = std::min(
        static_cast<size_t>(max_chunks), std::max(positives.size(), negatives.size()));
    auto empty = processWeightedPromptChunks("", 1, max_len).front();
    std::vector<ProcessedPromptPair> result;
    result.reserve(count);
    for (size_t i = 0; i < count; ++i) {
      const ProcessedPrompt &pos = i < positives.size() ? positives[i] : empty;
      const ProcessedPrompt &neg = i < negatives.size() ? negatives[i] : empty;
      ProcessedPromptPair pair;
      pair.ids.reserve(static_cast<size_t>(2 * max_len));
      pair.ids.insert(pair.ids.end(), neg.ids.begin(), neg.ids.end());
      pair.ids.insert(pair.ids.end(), pos.ids.begin(), pos.ids.end());
      pair.negative_embeddings = neg.weighted_embeddings;
      pair.positive_embeddings = pos.weighted_embeddings;
      pair.negative_embeddings_2 = neg.weighted_embeddings_2;
      pair.positive_embeddings_2 = pos.weighted_embeddings_2;
      pair.negative_content_ids = neg.content_ids;
      pair.positive_content_ids = pos.content_ids;
      pair.negative_content_weights = neg.content_weights;
      pair.positive_content_weights = pos.content_weights;
      result.push_back(std::move(pair));
    }
    return result;
  }

'''
    text = replace_once(text, anchor, helper + anchor, "H6R4 token-preserving helpers")
    path.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "  int seq_len = 77;  // 77 for CLIP (SD/SDXL), 512 for Qwen/T5 (Anima)\n",
        "  int seq_len = 77;  // 77 for CLIP (SD/SDXL), 512 for Qwen/T5 (Anima)\n"
        "  int positive_content_tokens = 0;\n"
        "  int negative_content_tokens = 0;\n"
        "  bool positive_clip_executed = false;\n"
        "  bool negative_clip_executed = false;\n",
        "Conditioning token truth fields",
    )

    # Single-chunk encodePrompts keeps its cache, but records exact content
    # counts and whether this invocation actually executed each CLIP side.
    text = replace_once(
        text,
        "  if (sdxl_) {\n    cond.pooled.assign((size_t)batch_size * cond.pooled_dim, 0.0f);\n",
        "  cond.positive_content_tokens =\n"
        "      static_cast<int>(text_encoder_.promptContentTokenIds(req.prompt).size());\n"
        "  cond.negative_content_tokens = static_cast<int>(\n"
        "      text_encoder_.promptContentTokenIds(req.negative_prompt).size());\n"
        "  if (sdxl_) {\n    cond.pooled.assign((size_t)batch_size * cond.pooled_dim, 0.0f);\n",
        "single conditioning content counts",
    )
    text = replace_once(
        text,
        "  encodeText(processed, !neg_hit, !pos_hit, cond);\n\n  // Persist freshly-computed CLIP outputs (per side).\n",
        "  encodeText(processed, !neg_hit, !pos_hit, cond);\n"
        "  cond.negative_clip_executed = !neg_hit;\n"
        "  cond.positive_clip_executed = !pos_hit;\n\n"
        "  // Persist freshly-computed CLIP outputs (per side).\n",
        "single conditioning CLIP execution facts",
    )

    start = text.index("inline std::vector<Conditioning> Pipeline::encodePromptChunks(")
    end = text.index("inline xt::xarray<float> Pipeline::encodeImageToLatent(", start)
    replacement = r'''inline std::vector<Conditioning> Pipeline::encodePromptChunks(
    const GenerationRequest &req) {
  if (isAnima()) return {encodePrompts(req)};

  auto processed_chunks = text_encoder_.processPromptPairChunks(
      req.prompt, req.negative_prompt, kS24uClipChunks, textSeqLen());
  if (processed_chunks.size() <= 1) return {encodePrompts(req)};

  QNN_INFO("S24U H6R4 token-preserving prompt: %zu direct fixed-77 chunks",
           processed_chunks.size());
  std::vector<Conditioning> result;
  result.reserve(processed_chunks.size());
  for (auto &processed : processed_chunks) {
    const int batch_size = 2;
    Conditioning cond;
    cond.hidden_dim = textHiddenDim();
    cond.pooled_dim = textPooledDim();
    cond.seq_len = textSeqLen();
    cond.hidden.assign(
        static_cast<size_t>(batch_size) * cond.seq_len * cond.hidden_dim, 0.0f);
    if (sdxl_) {
      cond.pooled.assign(static_cast<size_t>(batch_size) * cond.pooled_dim, 0.0f);
      cond.time_ids.assign(static_cast<size_t>(batch_size) * 6, 0.0f);
      for (int b = 0; b < batch_size; ++b) {
        cond.time_ids[b * 6 + 0] = static_cast<float>(req.height);
        cond.time_ids[b * 6 + 1] = static_cast<float>(req.width);
        cond.time_ids[b * 6 + 2] = 0.0f;
        cond.time_ids[b * 6 + 3] = 0.0f;
        cond.time_ids[b * 6 + 4] = static_cast<float>(req.height);
        cond.time_ids[b * 6 + 5] = static_cast<float>(req.width);
      }
    }
    cond.positive_content_tokens =
        static_cast<int>(processed.positive_content_ids.size());
    cond.negative_content_tokens =
        static_cast<int>(processed.negative_content_ids.size());
    encodeText(processed, true, true, cond);
    cond.positive_clip_executed = true;
    cond.negative_clip_executed = true;
    result.push_back(std::move(cond));
  }
  return result;
}

'''
    text = text[:start] + replacement + text[end:]

    fusion_start = text.index("    // Token weights are only computed for explicit experimental modes")
    fusion_end = text.index("    auto clip_dur = elapsedMs(clip_start);", fusion_start)
    fusion = r'''    // H6R4: fusion weights come from the exact content counts attached to
    // the already-encoded Conditioning chunks. No reconstructed chunk text is
    // ever sent through the tokenizer again.
    const bool request_skip_uncond = canSkipUncond() && (req.cfg == 1.0f);
    std::vector<float> fusion_token_weights(conds.size(), 1.0f);
    if (!isAnima() &&
        (req.fusion_mode == "token_weighted" ||
         req.fusion_mode == "anchor_residual")) {
      for (size_t j = 0; j < conds.size(); ++j) {
        const int pos_tokens = conds[j].positive_content_tokens;
        const int neg_tokens = conds[j].negative_content_tokens;
        const int effective_tokens = request_skip_uncond
                                         ? pos_tokens
                                         : std::max(pos_tokens, neg_tokens);
        fusion_token_weights[j] =
            static_cast<float>(std::max(1, effective_tokens));
      }
    }
'''
    text = text[:fusion_start] + fusion + text[fusion_end:]

    # Separate prompt presence, CLIP execution and UNet execution truth.
    text = replace_once(
        text,
        "  bool negative_encoded = false;\n  float positive_effective_weight = 1.0f;\n",
        "  bool negative_encoded = false;\n"
        "  bool negative_prompt_present = false;\n"
        "  bool negative_clip_executed = false;\n"
        "  bool negative_unet_executed = false;\n"
        "  float positive_effective_weight = 1.0f;\n",
        "guidance fact trace fields",
    )
    text = replace_once(
        text,
        "      unet_trace.negative_encoded = negative_encoded;\n"
        "      unet_trace.positive_effective_weight = positive_effective_weight;\n",
        "      unet_trace.negative_encoded = negative_encoded;\n"
        "      unet_trace.negative_prompt_present = !req.negative_prompt.empty();\n"
        "      unet_trace.negative_clip_executed = std::any_of(\n"
        "          conds.begin(), conds.end(), [](const Conditioning &c) {\n"
        "            return c.negative_clip_executed;\n"
        "          });\n"
        "      unet_trace.negative_unet_executed = !skip_uncond;\n"
        "      unet_trace.positive_effective_weight = positive_effective_weight;\n",
        "guidance fact trace values",
    )
    path.write_text(text, encoding="utf-8")


def patch_main(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")

    start = text.index("              std::vector<int> positive_token_ids;")
    end = text.index('              std::string phase = "prompt";', start)
    truth = r'''              // H6R4 token truth: the trace uses the exact cleaned content
              // token stream and the same direct 75-token boundaries as inference.
              std::vector<int> positive_token_ids;
              std::vector<int> negative_token_ids;
              std::vector<std::vector<int>> positive_chunk_token_ids;
              std::vector<std::vector<int>> negative_chunk_token_ids;
              std::vector<std::string> positive_chunks;
              std::vector<std::string> negative_chunks;
              if (text_encoder && text_encoder->tokenizer()) {
                positive_token_ids = text_encoder->promptContentTokenIds(req->prompt);
                negative_token_ids =
                    text_encoder->promptContentTokenIds(req->negative_prompt);
                positive_chunk_token_ids =
                    text_encoder->promptContentTokenIdChunks(req->prompt);
                negative_chunk_token_ids =
                    text_encoder->promptContentTokenIdChunks(req->negative_prompt);
                for (const auto &ids : positive_chunk_token_ids)
                  positive_chunks.push_back(text_encoder->decode(ids));
                for (const auto &ids : negative_chunk_token_ids)
                  negative_chunks.push_back(text_encoder->decode(ids));
              }
              auto flatten_chunks = [](const std::vector<std::vector<int>> &chunks) {
                std::vector<int> result;
                for (const auto &chunk : chunks)
                  result.insert(result.end(), chunk.begin(), chunk.end());
                return result;
              };
              auto positive_retained_ids = flatten_chunks(positive_chunk_token_ids);
              auto negative_retained_ids = flatten_chunks(negative_chunk_token_ids);
              auto prefix_preserved = [](const std::vector<int> &original,
                                         const std::vector<int> &retained) {
                if (retained.size() > original.size()) return false;
                return std::equal(retained.begin(), retained.end(), original.begin());
              };
              const bool positive_token_preserved =
                  prefix_preserved(positive_token_ids, positive_retained_ids);
              const bool negative_token_preserved =
                  prefix_preserved(negative_token_ids, negative_retained_ids);
              std::vector<int> positive_chunk_tokens;
              std::vector<int> negative_chunk_tokens;
              for (const auto &chunk : positive_chunk_token_ids)
                positive_chunk_tokens.push_back(static_cast<int>(chunk.size()));
              for (const auto &chunk : negative_chunk_token_ids)
                negative_chunk_tokens.push_back(static_cast<int>(chunk.size()));
              const int positive_input_tokens =
                  static_cast<int>(positive_token_ids.size());
              const int negative_input_tokens =
                  static_cast<int>(negative_token_ids.size());
              const int positive_effective_tokens =
                  static_cast<int>(positive_retained_ids.size());
              const int negative_effective_tokens =
                  static_cast<int>(negative_retained_ids.size());
              const int positive_truncated_tokens =
                  std::max(0, positive_input_tokens - positive_effective_tokens);
              const int negative_truncated_tokens =
                  std::max(0, negative_input_tokens - negative_effective_tokens);

'''
    text = text[:start] + truth + text[end:]

    # The old H4 budget block sat between the H3 chunk reconstruction and phase.
    # Because the span above ends at phase, any duplicate declarations are gone.
    text = replace_once(
        text,
        '''                  {"positive_chunk_tokens", positive_chunk_tokens},
                  {"negative_chunk_tokens", negative_chunk_tokens},
                  {"max_chunks", kS24uClipChunks},
''',
        '''                  {"positive_chunk_tokens", positive_chunk_tokens},
                  {"negative_chunk_tokens", negative_chunk_tokens},
                  {"positive_chunk_token_ids", positive_chunk_token_ids},
                  {"negative_chunk_token_ids", negative_chunk_token_ids},
                  {"positive_token_preserved", positive_token_preserved},
                  {"negative_token_preserved", negative_token_preserved},
                  {"max_chunks", kS24uClipChunks},
''',
        "prompt token preservation JSON",
    )
    text = replace_once(
        text,
        '''                        {"negative_encoded", trace.negative_encoded},
                        {"positive_effective_weight", trace.positive_effective_weight},
''',
        '''                        {"negative_encoded", trace.negative_encoded},
                        {"negative_prompt_present", trace.negative_prompt_present},
                        {"negative_clip_executed", trace.negative_clip_executed},
                        {"negative_unet_executed", trace.negative_unet_executed},
                        {"positive_effective_weight", trace.positive_effective_weight},
''',
        "guidance fact serialization",
    )
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "        val negativeEncoded: Boolean = false,\n        val positiveEffectiveWeight: Float = 1f,\n",
        "        val negativeEncoded: Boolean = false,\n"
        "        val negativePromptPresent: Boolean = false,\n"
        "        val negativeClipExecuted: Boolean = false,\n"
        "        val negativeUnetExecuted: Boolean = false,\n"
        "        val positiveEffectiveWeight: Float = 1f,\n",
        "event guidance fact fields",
    )
    text = replace_once(
        text,
        "        val negativeEncoded: Boolean = false,\n        val positiveEffectiveWeight: Float = 1f,\n",
        "        val negativeEncoded: Boolean = false,\n"
        "        val negativePromptPresent: Boolean = false,\n"
        "        val negativeClipExecuted: Boolean = false,\n"
        "        val negativeUnetExecuted: Boolean = false,\n"
        "        val positiveEffectiveWeight: Float = 1f,\n",
        "snapshot guidance fact fields",
    )
    # Prompt preservation lives on snapshot only; prompt events carry via parser
    # fields below and reducer stores them.
    text = replace_once(
        text,
        "        val maxChunks: Int = 8,\n        val cfgValue: Float = 1f,\n",
        "        val maxChunks: Int = 8,\n"
        "        val positiveChunkTokenIds: List<List<Int>> = emptyList(),\n"
        "        val negativeChunkTokenIds: List<List<Int>> = emptyList(),\n"
        "        val positiveTokenPreserved: Boolean = true,\n"
        "        val negativeTokenPreserved: Boolean = true,\n"
        "        val cfgValue: Float = 1f,\n",
        "snapshot token preservation fields",
    )
    # Add matching event fields next to maxChunks in the event declaration; the
    # first occurrence is MicroscopeEvent before Snapshot.
    marker = "        val maxChunks: Int = 8,\n    )\n\n    data class MicroscopeSnapshot("
    if marker in text:
        text = text.replace(
            marker,
            "        val maxChunks: Int = 8,\n"
            "        val positiveChunkTokenIds: List<List<Int>> = emptyList(),\n"
            "        val negativeChunkTokenIds: List<List<Int>> = emptyList(),\n"
            "        val positiveTokenPreserved: Boolean = true,\n"
            "        val negativeTokenPreserved: Boolean = true,\n"
            "    )\n\n    data class MicroscopeSnapshot(",
            1,
        )
    else:
        raise RuntimeError("event token preservation anchor not found")

    json_helper_anchor = "    private fun jsonIntList(message: JSONObject, key: String): List<Int> {"
    idx = text.find(json_helper_anchor)
    if idx < 0:
        raise RuntimeError("jsonIntList helper anchor not found")
    helper_end = text.find("\n    }", idx) + len("\n    }")
    nested_helper = r'''

    private fun jsonNestedIntList(message: JSONObject, key: String): List<List<Int>> {
        val outer = message.optJSONArray(key) ?: return emptyList()
        return buildList {
            for (i in 0 until outer.length()) {
                val inner = outer.optJSONArray(i) ?: continue
                add(buildList { for (j in 0 until inner.length()) add(inner.optInt(j)) })
            }
        }
    }
'''
    text = text[:helper_end] + nested_helper + text[helper_end:]

    text = replace_once(
        text,
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
            cfgValue = message.optDouble("cfg_value", 1.0).toFloat(),
''',
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
            positiveChunkTokenIds = jsonNestedIntList(message, "positive_chunk_token_ids"),
            negativeChunkTokenIds = jsonNestedIntList(message, "negative_chunk_token_ids"),
            positiveTokenPreserved = message.optBoolean("positive_token_preserved", true),
            negativeTokenPreserved = message.optBoolean("negative_token_preserved", true),
            cfgValue = message.optDouble("cfg_value", 1.0).toFloat(),
''',
        "event token preservation parser",
    )
    text = replace_once(
        text,
        '''            negativeEncoded = message.optBoolean("negative_encoded", false),
            positiveEffectiveWeight = message.optDouble("positive_effective_weight", 1.0).toFloat(),
''',
        '''            negativeEncoded = message.optBoolean("negative_encoded", false),
            negativePromptPresent = message.optBoolean("negative_prompt_present", false),
            negativeClipExecuted = message.optBoolean("negative_clip_executed", false),
            negativeUnetExecuted = message.optBoolean("negative_unet_executed", false),
            positiveEffectiveWeight = message.optDouble("positive_effective_weight", 1.0).toFloat(),
''',
        "event guidance fact parser",
    )
    text = replace_once(
        text,
        '''            maxChunks = if (event.phase == "prompt") event.maxChunks else previous.maxChunks,
        )
''',
        '''            maxChunks = if (event.phase == "prompt") event.maxChunks else previous.maxChunks,
            positiveChunkTokenIds = if (event.phase == "prompt") event.positiveChunkTokenIds else previous.positiveChunkTokenIds,
            negativeChunkTokenIds = if (event.phase == "prompt") event.negativeChunkTokenIds else previous.negativeChunkTokenIds,
            positiveTokenPreserved = if (event.phase == "prompt") event.positiveTokenPreserved else previous.positiveTokenPreserved,
            negativeTokenPreserved = if (event.phase == "prompt") event.negativeTokenPreserved else previous.negativeTokenPreserved,
        )
''',
        "snapshot token preservation reducer",
    )
    text = replace_once(
        text,
        '''            negativeEncoded = if (event.phase == "unet_step") event.negativeEncoded else previous.negativeEncoded,
            positiveEffectiveWeight = if (event.phase == "unet_step") event.positiveEffectiveWeight else previous.positiveEffectiveWeight,
''',
        '''            negativeEncoded = if (event.phase == "unet_step") event.negativeEncoded else previous.negativeEncoded,
            negativePromptPresent = if (event.phase == "unet_step") event.negativePromptPresent else previous.negativePromptPresent,
            negativeClipExecuted = if (event.phase == "unet_step") event.negativeClipExecuted else previous.negativeClipExecuted,
            negativeUnetExecuted = if (event.phase == "unet_step") event.negativeUnetExecuted else previous.negativeUnetExecuted,
            positiveEffectiveWeight = if (event.phase == "unet_step") event.positiveEffectiveWeight else previous.positiveEffectiveWeight,
''',
        "snapshot guidance fact reducer",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '            put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")\n',
        '            put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")\n'
        '            put("h6r4_marker", "S24U_H6R4_TOKEN_TRUTH")\n',
        "H6R4 DEX marker",
    )
    # helper for nested arrays lives inside payload function next to intArrayJson
    anchor = '''        fun intArrayJson(values: List<Int>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }
'''
    nested = '''        fun intArrayJson(values: List<Int>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }

        fun nestedIntArrayJson(values: List<List<Int>>): JSONArray = JSONArray().apply {
            values.forEach { row -> put(intArrayJson(row)) }
        }
'''
    text = replace_once(text, anchor, nested, "nested token id JSON helper")
    text = replace_once(
        text,
        '            put("max_chunks", microscope.maxChunks)\n',
        '            put("max_chunks", microscope.maxChunks)\n'
        '            put("positive_chunk_token_ids", nestedIntArrayJson(microscope.positiveChunkTokenIds))\n'
        '            put("negative_chunk_token_ids", nestedIntArrayJson(microscope.negativeChunkTokenIds))\n'
        '            put("positive_token_preserved", microscope.positiveTokenPreserved)\n'
        '            put("negative_token_preserved", microscope.negativeTokenPreserved)\n',
        "WebView token preservation payload",
    )
    text = replace_once(
        text,
        '            put("negative_encoded", microscope.negativeEncoded)\n',
        '            put("negative_encoded", microscope.negativeEncoded)\n'
        '            put("negative_prompt_present", microscope.negativePromptPresent)\n'
        '            put("negative_clip_executed", microscope.negativeClipExecuted)\n'
        '            put("negative_unet_executed", microscope.negativeUnetExecuted)\n',
        "WebView guidance fact payload",
    )
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    # Add preservation and guidance facts to the existing tensor/mechanism view.
    old = "    const posWeight=num(s.positive_effective_weight,cfg),negWeight=num(s.negative_effective_weight,Math.max(cfg-1,0)),negEncoded=Boolean(s.negative_encoded);\n"
    new = "    const posWeight=num(s.positive_effective_weight,cfg),negWeight=num(s.negative_effective_weight,Math.max(cfg-1,0)),negEncoded=Boolean(s.negative_encoded),negPresent=Boolean(s.negative_prompt_present),negClip=Boolean(s.negative_clip_executed),negUnet=Boolean(s.negative_unet_executed);\n"
    text = replace_once(text, old, new, "mechanism guidance fact variables")
    old_grid = "[['CFG',cfg.toFixed(3)],['NEG effective',negWeight.toFixed(3)],['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['Influence',arr(s.influence_samples).length],['Scheduler',s.scheduler_seen?'YES':'NO']]"
    new_grid = "[['CFG',cfg.toFixed(3)],['NEG effective',negWeight.toFixed(3)],['Negative prompt',negPresent?'PRESENT':'EMPTY'],['Negative CLIP',negClip?'EXECUTED':'NOT EXECUTED'],['Negative UNet',negUnet?'EXECUTED':'SKIPPED'],['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['Influence',arr(s.influence_samples).length],['Scheduler',s.scheduler_seen?'YES':'NO']]"
    text = replace_once(text, old_grid, new_grid, "mechanism guidance truth grid")

    # Add an explicit preservation card at the top of Token/Chunk budget.
    needle = "  function renderBudget(s){"
    idx = text.index(needle)
    body_idx = idx + len(needle)
    inject = r'''const preservation=$('token-preservation');if(preservation){const pos=Boolean(s.positive_token_preserved),neg=Boolean(s.negative_token_preserved),pc=arr(s.positive_chunk_token_ids).map(x=>arr(x).length),nc=arr(s.negative_chunk_token_ids).map(x=>arr(x).length);preservation.className=`attention-state ${pos&&neg?'truth-pass':'truth-fail'}`;preservation.innerHTML=`<strong>TOKEN PRESERVATION · ${pos&&neg?'PASS':'FAIL'}</strong><p>POS ${int(s.positive_input_tokens)} → [${pc.join(', ')}] · ${pos?'exact retained token prefix':'MISMATCH'}<br>NEG ${int(s.negative_input_tokens)} → [${nc.join(', ')}] · ${neg?'exact retained token prefix':'MISMATCH'}</p>`;}
    '''
    text = text[:body_idx] + inject + text[body_idx:]
    path.write_text(text, encoding="utf-8")


def patch_html(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/index.html"
    text = path.read_text(encoding="utf-8")
    anchor = '''      <article class="card">
        <span class="kicker">PROMPT</span><h2>Token / Chunk</h2>
'''
    replacement = '''      <article class="card">
        <span class="kicker">PROMPT</span><h2>Token / Chunk</h2>
        <div id="token-preservation" class="attention-state"><strong>TOKEN PRESERVATION</strong><p>等待本轮真实 token 边界。</p></div>
'''
    text = replace_once(text, anchor, replacement, "token preservation card")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v11_token_truth.py <h6r3-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_text_encoder(root)
    patch_pipeline(root)
    patch_main(root)
    patch_service(root)
    patch_screen(root)
    patch_js(root)
    patch_html(root)
    print("S24U_IMAGE_HARNESS_H6R4_TOKEN_TRUTH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
