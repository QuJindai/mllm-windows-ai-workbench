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
        "#include <iostream>\n#include <memory>\n",
        "#include <iostream>\n#include <limits>\n#include <memory>\n",
        "numeric_limits include",
    )
    text = replace_once(
        text,
        '''  int64_t dynamics_unet_ms = 0;
  int64_t dynamics_scheduler_ms = 0;
};
''',
        '''  int64_t dynamics_unet_ms = 0;
  int64_t dynamics_scheduler_ms = 0;
  std::vector<float> channel_stats;
  std::vector<float> channel_correlation;
  std::vector<float> channel_histograms;
};
''',
        "latent inspector trace fields",
    )
    anchor = "// S24U H6R3 Process Dynamics. These are derived directly from the latent\n"
    helper = r'''inline constexpr int kLatentHistogramBins = 32;

// S24U H6R3 Latent State Inspector. Compact statistics are derived from the
// exact four scheduler latent channels already resident on CPU. The existing
// 2x2 JPEG is retained as one overview payload; individual channel panels crop
// its quadrants in WebView, so no extra image/model pass is introduced.
inline void computeLatentChannelInspector(
    const xt::xarray<float> &latents, std::vector<float> &channel_stats,
    std::vector<float> &channel_correlation,
    std::vector<float> &channel_histograms) {
  channel_stats.clear();
  channel_correlation.clear();
  channel_histograms.clear();
  if (latents.dimension() != 4 || latents.shape()[0] < 1 ||
      latents.shape()[1] < 4)
    return;
  const int h = static_cast<int>(latents.shape()[2]);
  const int w = static_cast<int>(latents.shape()[3]);
  if (h <= 0 || w <= 0) return;
  constexpr int channels = 4;
  const double n = static_cast<double>(h) * w;
  channel_stats.resize(channels * 5, 0.0f);  // min,max,mean,std,l2
  channel_correlation.resize(channels * channels, 0.0f);
  channel_histograms.resize(channels * kLatentHistogramBins, 0.0f);
  std::vector<double> means(channels, 0.0), stds(channels, 0.0);

  for (int c = 0; c < channels; ++c) {
    double sum = 0.0, sum_sq = 0.0;
    float lo = std::numeric_limits<float>::infinity();
    float hi = -std::numeric_limits<float>::infinity();
    for (int y = 0; y < h; ++y) {
      for (int x = 0; x < w; ++x) {
        const float v = latents(0, c, y, x);
        lo = std::min(lo, v);
        hi = std::max(hi, v);
        sum += v;
        sum_sq += static_cast<double>(v) * v;
      }
    }
    const double mean = sum / n;
    const double variance = std::max(0.0, sum_sq / n - mean * mean);
    const double stddev = std::sqrt(variance);
    means[c] = mean;
    stds[c] = stddev;
    channel_stats[c * 5 + 0] = lo;
    channel_stats[c * 5 + 1] = hi;
    channel_stats[c * 5 + 2] = static_cast<float>(mean);
    channel_stats[c * 5 + 3] = static_cast<float>(stddev);
    channel_stats[c * 5 + 4] = static_cast<float>(std::sqrt(sum_sq));
    const float span = std::max(hi - lo, 1e-12f);
    for (int y = 0; y < h; ++y) {
      for (int x = 0; x < w; ++x) {
        const float normalized = std::clamp(
            (latents(0, c, y, x) - lo) / span, 0.0f, 0.999999f);
        const int bin = std::min(
            kLatentHistogramBins - 1,
            static_cast<int>(normalized * kLatentHistogramBins));
        channel_histograms[c * kLatentHistogramBins + bin] += 1.0f;
      }
    }
    for (int b = 0; b < kLatentHistogramBins; ++b)
      channel_histograms[c * kLatentHistogramBins + b] /=
          static_cast<float>(n);
  }

  for (int a = 0; a < channels; ++a) {
    for (int b = 0; b < channels; ++b) {
      double covariance = 0.0;
      for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
          covariance += (latents(0, a, y, x) - means[a]) *
                        (latents(0, b, y, x) - means[b]);
        }
      }
      const double denom = n * stds[a] * stds[b];
      channel_correlation[a * channels + b] =
          denom > 1e-12 ? static_cast<float>(covariance / denom)
                        : (a == b ? 1.0f : 0.0f);
    }
  }
}

'''
    text = replace_once(text, anchor, helper + anchor, "latent inspector helper")
    text = replace_once(
        text,
        '''      latent_trace.latent_height = sample_height;
      latent_trace.image_base64 = renderLatentChannelsPreview(latents);
      emit_trace(latent_trace);
''',
        '''      latent_trace.latent_height = sample_height;
      computeLatentChannelInspector(
          latents, latent_trace.channel_stats,
          latent_trace.channel_correlation,
          latent_trace.channel_histograms);
      latent_trace.image_base64 = renderLatentChannelsPreview(latents);
      emit_trace(latent_trace);
''',
        "latent inspector event",
    )
    path.write_text(text, encoding="utf-8")


def patch_main(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                        {"dynamics_scheduler_ms", trace.dynamics_scheduler_ms},
                        {"image_base64", trace.image_base64}};
''',
        '''                        {"dynamics_scheduler_ms", trace.dynamics_scheduler_ms},
                        {"channel_stats", trace.channel_stats},
                        {"channel_correlation", trace.channel_correlation},
                        {"channel_histograms", trace.channel_histograms},
                        {"image_base64", trace.image_base64}};
''',
        "latent inspector serialization",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v9_latent_core.py <h6r3-task4-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_pipeline(root)
    patch_main(root)
    print("S24U_IMAGE_HARNESS_H6R3_LATENT_CORE_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
