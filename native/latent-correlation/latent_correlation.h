#ifndef __SD_CLI_LATENT_CORRELATION_H__
#define __SD_CLI_LATENT_CORRELATION_H__

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

namespace sd_latent {

// Input is contiguous [batch][channel][spatial]. NaN represents an undefined
// Pearson coefficient; the JSON writer serializes it as null.
inline std::vector<std::vector<double>> channel_correlation(const float* values,
                                                           size_t plane,
                                                           size_t channels,
                                                           size_t batch) {
    const double undefined = std::numeric_limits<double>::quiet_NaN();
    std::vector<std::vector<double>> result(channels, std::vector<double>(channels, undefined));
    if (!values || plane == 0 || batch == 0) return result;
    std::vector<double> means(channels, 0.0);
    std::vector<double> squares(channels, 0.0);
    std::vector<bool> valid(channels, true);
    for (size_t channel = 0; channel < channels; ++channel) {
        for (size_t b = 0; b < batch; ++b) {
            const size_t offset = (b * channels + channel) * plane;
            for (size_t p = 0; p < plane; ++p) {
                const double value = values[offset + p];
                if (!std::isfinite(value)) valid[channel] = false;
                else means[channel] += value;
            }
        }
        means[channel] /= static_cast<double>(plane) * static_cast<double>(batch);
        if (!valid[channel]) continue;
        // Center before squaring: E[x*x]-E[x]^2 loses small variance at large offsets.
        for (size_t b = 0; b < batch; ++b) {
            const size_t offset = (b * channels + channel) * plane;
            for (size_t p = 0; p < plane; ++p) {
                const double centered = static_cast<double>(values[offset + p]) - means[channel];
                squares[channel] += centered * centered;
            }
        }
        valid[channel] = squares[channel] > 0.0 && std::isfinite(squares[channel]);
    }
    for (size_t left = 0; left < channels; ++left) {
        if (!valid[left]) continue;
        result[left][left] = 1.0;
        for (size_t right = left + 1; right < channels; ++right) {
            if (!valid[right]) continue;
            double cross = 0.0;
            for (size_t b = 0; b < batch; ++b) {
                const size_t left_offset = (b * channels + left) * plane;
                const size_t right_offset = (b * channels + right) * plane;
                for (size_t p = 0; p < plane; ++p) {
                    cross += (static_cast<double>(values[left_offset + p]) - means[left]) *
                             (static_cast<double>(values[right_offset + p]) - means[right]);
                }
            }
            const double coefficient = cross / std::sqrt(squares[left]) / std::sqrt(squares[right]);
            if (std::isfinite(coefficient)) {
                result[left][right] = result[right][left] = std::clamp(coefficient, -1.0, 1.0);
            }
        }
    }
    return result;
}

}  // namespace sd_latent
#endif
