#!/usr/bin/env python3
from pathlib import Path
import sys


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
        '  std::vector<float> fusion_weights;\n};\n',
        '  std::vector<float> fusion_weights;\n'
        '  float latent_delta = 0.0f;\n'
        '  float delta_l2 = 0.0f;\n'
        '  float delta_mean_abs = 0.0f;\n'
        '  float latent_cosine = 0.0f;\n'
        '  float latent_mean = 0.0f;\n'
        '  float latent_std = 0.0f;\n'
        '  int64_t dynamics_unet_ms = 0;\n'
        '  int64_t dynamics_scheduler_ms = 0;\n'
        '};\n',
        'dynamics trace fields',
    )
    anchor = '// S24U H6 conditioning influence metrics. These functions observe the exact\n'
    helper = r'''// S24U H6R3 Process Dynamics. These are derived directly from the latent
// state already resident on CPU before/after the effective scheduler update.
// No CLIP/UNet/VAE/Scheduler call is added for visualization.
inline void computeLatentDynamicsMetrics(
    const xt::xarray<float> &before, const xt::xarray<float> &after,
    float &delta_l2, float &delta_mean_abs, float &latent_cosine,
    float &latent_mean, float &latent_std) {
  delta_l2 = delta_mean_abs = latent_cosine = latent_mean = latent_std = 0.0f;
  if (before.size() == 0 || before.size() != after.size()) return;
  double delta_sq = 0.0, delta_abs = 0.0;
  double before_sq = 0.0, after_sq = 0.0, dot = 0.0;
  double sum = 0.0, sum_sq = 0.0;
  auto b = before.cbegin();
  auto a = after.cbegin();
  for (; b != before.cend(); ++b, ++a) {
    const double bv = static_cast<double>(*b);
    const double av = static_cast<double>(*a);
    const double d = av - bv;
    delta_sq += d * d;
    delta_abs += std::fabs(d);
    before_sq += bv * bv;
    after_sq += av * av;
    dot += bv * av;
    sum += av;
    sum_sq += av * av;
  }
  const double n = static_cast<double>(after.size());
  delta_l2 = static_cast<float>(std::sqrt(delta_sq));
  delta_mean_abs = static_cast<float>(delta_abs / n);
  const double denom = std::sqrt(before_sq) * std::sqrt(after_sq);
  latent_cosine = denom > 1e-12 ? static_cast<float>(dot / denom) : 0.0f;
  const double mean = sum / n;
  const double variance = std::max(0.0, sum_sq / n - mean * mean);
  latent_mean = static_cast<float>(mean);
  latent_std = static_cast<float>(std::sqrt(variance));
}

inline std::string renderLatentDeltaPreview(
    const xt::xarray<float> &before, const xt::xarray<float> &after) {
  try {
    if (before.dimension() != 4 || after.dimension() != 4 ||
        before.shape() != after.shape() || before.shape()[0] < 1)
      return "";
    const int channels = static_cast<int>(before.shape()[1]);
    const int h = static_cast<int>(before.shape()[2]);
    const int w = static_cast<int>(before.shape()[3]);
    if (channels <= 0 || h <= 0 || w <= 0) return "";
    std::vector<float> values(static_cast<size_t>(h) * w, 0.0f);
    float hi = 0.0f;
    for (int y = 0; y < h; ++y) {
      for (int x = 0; x < w; ++x) {
        float v = 0.0f;
        for (int c = 0; c < channels; ++c)
          v += std::fabs(after(0, c, y, x) - before(0, c, y, x));
        v /= static_cast<float>(channels);
        values[static_cast<size_t>(y) * w + x] = v;
        hi = std::max(hi, v);
      }
    }
    hi = std::max(hi, 1e-12f);
    std::vector<uint8_t> rgb(static_cast<size_t>(w) * h * 3, 0);
    for (size_t i = 0; i < values.size(); ++i) {
      const float normalized =
          std::sqrt(std::clamp(values[i] / hi, 0.0f, 1.0f));
      const uint8_t g = static_cast<uint8_t>(normalized * 255.0f);
      rgb[i * 3] = g;
      rgb[i * 3 + 1] = g;
      rgb[i * 3 + 2] = g;
    }
    auto jpg = encodeJPEG(rgb, w, h, 72);
    return base64_encode(std::string(jpg.begin(), jpg.end()));
  } catch (const std::exception &e) {
    QNN_WARN("Latent delta preview failed: %s", e.what());
    return "";
  }
}

'''
    text = replace_once(text, anchor, helper + anchor, 'dynamics helper insertion')
    text = replace_once(
        text,
        '      chunk_predictions.clear();\n\n      auto scheduler_start = std::chrono::high_resolution_clock::now();\n',
        '      chunk_predictions.clear();\n\n'
        '      xt::xarray<float> latents_before_step = xt::eval(latents);\n'
        '      auto scheduler_start = std::chrono::high_resolution_clock::now();\n',
        'pre-step latent snapshot',
    )
    text = replace_once(
        text,
        '''      MicroscopeTraceEvent latent_trace;
      latent_trace.phase = "latent_map";
''',
        '''      float delta_l2 = 0.0f;
      float delta_mean_abs = 0.0f;
      float latent_cosine = 0.0f;
      float latent_mean = 0.0f;
      float latent_std = 0.0f;
      computeLatentDynamicsMetrics(
          latents_before_step, latents, delta_l2, delta_mean_abs,
          latent_cosine, latent_mean, latent_std);
      MicroscopeTraceEvent dynamics_trace;
      dynamics_trace.phase = "latent_delta";
      dynamics_trace.step = current_step;
      dynamics_trace.total_steps = total_run_steps;
      dynamics_trace.diffusion_step = i - start_step + 1;
      dynamics_trace.diffusion_total =
          static_cast<int>(timesteps.size()) - start_step;
      dynamics_trace.timestep = current_ts;
      dynamics_trace.chunk_count = static_cast<int>(conds.size());
      dynamics_trace.latent_width = sample_width;
      dynamics_trace.latent_height = sample_height;
      dynamics_trace.latent_delta = delta_mean_abs;
      dynamics_trace.delta_l2 = delta_l2;
      dynamics_trace.delta_mean_abs = delta_mean_abs;
      dynamics_trace.latent_cosine = latent_cosine;
      dynamics_trace.latent_mean = latent_mean;
      dynamics_trace.latent_std = latent_std;
      dynamics_trace.dynamics_unet_ms = step_dur;
      dynamics_trace.dynamics_scheduler_ms = scheduler_dur;
      dynamics_trace.image_base64 =
          renderLatentDeltaPreview(latents_before_step, latents);
      emit_trace(dynamics_trace);

      MicroscopeTraceEvent latent_trace;
      latent_trace.phase = "latent_map";
''',
        'dynamics event',
    )
    path.write_text(text, encoding="utf-8")


def patch_main(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '                        {"fusion_weights", trace.fusion_weights},\n                        {"image_base64", trace.image_base64}};\n',
        '                        {"fusion_weights", trace.fusion_weights},\n'
        '                        {"latent_delta", trace.latent_delta},\n'
        '                        {"delta_l2", trace.delta_l2},\n'
        '                        {"delta_mean_abs", trace.delta_mean_abs},\n'
        '                        {"latent_cosine", trace.latent_cosine},\n'
        '                        {"latent_mean", trace.latent_mean},\n'
        '                        {"latent_std", trace.latent_std},\n'
        '                        {"dynamics_unet_ms", trace.dynamics_unet_ms},\n'
        '                        {"dynamics_scheduler_ms", trace.dynamics_scheduler_ms},\n'
        '                        {"image_base64", trace.image_base64}};\n',
        'dynamics serialization',
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v8_dynamics_core.py <h6r3-task3-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_pipeline(root)
    patch_main(root)
    print("S24U_IMAGE_HARNESS_H6R3_DYNAMICS_CORE_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
