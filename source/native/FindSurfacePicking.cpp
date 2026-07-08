#include <cstdint>
#include <cmath>
#include <algorithm>
#include <limits>
#include <vector>

#if defined(_WIN32)
#define FS_PICK_API extern "C" __declspec(dllexport)
#else
#define FS_PICK_API extern "C" __attribute__((visibility("default")))
#endif

namespace {
struct Vec3 {
    float x;
    float y;
    float z;
};

float dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3 sub(const Vec3& a, const Vec3& b) {
    return Vec3{a.x - b.x, a.y - b.y, a.z - b.z};
}

Vec3 add(const Vec3& a, const Vec3& b) {
    return Vec3{a.x + b.x, a.y + b.y, a.z + b.z};
}

Vec3 mul(const Vec3& value, float scale) {
    return Vec3{value.x * scale, value.y * scale, value.z * scale};
}

Vec3 load_vec3(const float* values) {
    return Vec3{values[0], values[1], values[2]};
}

float length_sq(const Vec3& value) {
    return dot(value, value);
}

Vec3 normalize(const Vec3& value, const Vec3& fallback) {
    const float size_sq = length_sq(value);
    if (size_sq <= 1.0e-16f) {
        return fallback;
    }
    return mul(value, 1.0f / std::sqrt(size_sq));
}

struct HistogramResult {
    int count;
    int source_count;
    int excluded_count;
    int bin_count;
    int negative_count;
    int zero_count;
    int positive_count;
    int max_bin_count;
    double minimum;
    double maximum;
    double mean;
    double sigma;
    double source_sigma;
    double range_min;
    double range_max;
    double mean_fraction;
    double zero_fraction;
};

struct Vec3d {
    double x;
    double y;
    double z;
};

Vec3d load_vec3d(const double* values) {
    return Vec3d{values[0], values[1], values[2]};
}

Vec3d to_vec3d(const float* values) {
    return Vec3d{static_cast<double>(values[0]), static_cast<double>(values[1]), static_cast<double>(values[2])};
}

double dotd(const Vec3d& a, const Vec3d& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3d subd(const Vec3d& a, const Vec3d& b) {
    return Vec3d{a.x - b.x, a.y - b.y, a.z - b.z};
}

Vec3d muld(const Vec3d& value, double scale) {
    return Vec3d{value.x * scale, value.y * scale, value.z * scale};
}

double lengthd(const Vec3d& value) {
    return std::sqrt(dotd(value, value));
}

Vec3d normalized(const Vec3d& value, const Vec3d& fallback) {
    const double size = lengthd(value);
    if (size <= 1.0e-12) {
        return fallback;
    }
    return muld(value, 1.0 / size);
}

double standard_deviation(const std::vector<double>& values) {
    if (values.empty()) {
        return 0.0;
    }
    double sum = 0.0;
    for (double value : values) {
        sum += value;
    }
    const double mean = sum / static_cast<double>(values.size());
    double variance = 0.0;
    for (double value : values) {
        const double delta = value - mean;
        variance += delta * delta;
    }
    variance /= static_cast<double>(values.size());
    return std::sqrt(std::max(0.0, variance));
}

int normalized_bin_count(int bin_count) {
    constexpr int min_bins = 23;
    constexpr int max_bins = 47;
    if (bin_count <= 0) {
        bin_count = 35;
    }
    bin_count = std::max(min_bins, std::min(max_bins, bin_count));
    if ((bin_count % 2) == 0) {
        bin_count += bin_count < max_bins ? 1 : -1;
    }
    return bin_count;
}

double surface_distance(int surface_type, const double* params, const Vec3d& point) {
    if (surface_type == 1) {
        const Vec3d origin = load_vec3d(params);
        const Vec3d normal = normalized(load_vec3d(params + 3), Vec3d{0.0, 0.0, 1.0});
        return dotd(subd(point, origin), normal);
    }
    if (surface_type == 2) {
        const Vec3d center = load_vec3d(params);
        const double radius = params[3];
        return lengthd(subd(point, center)) - radius;
    }
    if (surface_type == 3) {
        const Vec3d start = load_vec3d(params);
        const Vec3d end = load_vec3d(params + 3);
        const double radius = params[6];
        const Vec3d axis = normalized(subd(end, start), Vec3d{0.0, 0.0, 1.0});
        const Vec3d offset = subd(point, start);
        const double axial = dotd(offset, axis);
        const double radial = lengthd(subd(offset, muld(axis, axial)));
        return radial - radius;
    }
    if (surface_type == 4) {
        const Vec3d start = load_vec3d(params);
        const Vec3d end = load_vec3d(params + 3);
        const double start_radius = params[6];
        const double end_radius = params[7];
        const Vec3d axis_delta = subd(end, start);
        const double height = std::max(lengthd(axis_delta), 1.0e-12);
        const Vec3d axis = normalized(axis_delta, Vec3d{0.0, 0.0, 1.0});
        const double slope = (end_radius - start_radius) / height;
        const double denominator = std::sqrt(slope * slope + 1.0);
        const Vec3d offset = subd(point, start);
        const double axial = dotd(offset, axis);
        const double radial = lengthd(subd(offset, muld(axis, axial)));
        return (radial - (slope * axial + start_radius)) / denominator;
    }
    if (surface_type == 5) {
        const Vec3d center = load_vec3d(params);
        const Vec3d axis = normalized(load_vec3d(params + 3), Vec3d{0.0, 0.0, 1.0});
        const double major_radius = std::fabs(params[6]);
        const double tube_radius = std::fabs(params[7]);
        const Vec3d offset = subd(point, center);
        const double axial = dotd(offset, axis);
        const double radial = lengthd(subd(offset, muld(axis, axial)));
        return std::sqrt((radial - major_radius) * (radial - major_radius) + axial * axial) - tube_radius;
    }
    return std::numeric_limits<double>::quiet_NaN();
}
}  // namespace

FS_PICK_API int fs_pick_point_orthographic(
    const float* points,
    const std::uint8_t* active_mask,
    int point_count,
    const float* camera_position_values,
    const float* camera_center_values,
    const float* camera_right_values,
    const float* camera_up_values,
    const float* camera_forward_values,
    float viewport_width,
    float viewport_height,
    float screen_x,
    float screen_y,
    float probe_radius_px,
    float pixel_scale,
    int fallback_to_nearest) {
    if (!points || point_count <= 0 || viewport_width <= 0.0f || viewport_height <= 0.0f || pixel_scale <= 0.0f) {
        return -1;
    }

    const Vec3 camera_position = load_vec3(camera_position_values);
    const Vec3 camera_center = load_vec3(camera_center_values);
    const Vec3 camera_right = load_vec3(camera_right_values);
    const Vec3 camera_up = load_vec3(camera_up_values);
    const Vec3 camera_forward = load_vec3(camera_forward_values);
    const float radius_sq = probe_radius_px * probe_radius_px;
    const float half_width = viewport_width * 0.5f;
    const float half_height = viewport_height * 0.5f;

    int best_index = -1;
    float best_depth = 3.402823466e+38F;
    int nearest_index = -1;
    float nearest_screen_dist_sq = 3.402823466e+38F;
    float nearest_depth = 3.402823466e+38F;
    for (int index = 0; index < point_count; ++index) {
        if (active_mask && !active_mask[index]) {
            continue;
        }
        const float* point_values = points + index * 3;
        const Vec3 point{point_values[0], point_values[1], point_values[2]};
        const Vec3 center_rel = sub(point, camera_center);
        const float px = half_width + dot(center_rel, camera_right) * pixel_scale;
        const float py = half_height - dot(center_rel, camera_up) * pixel_scale;
        const float dx = px - screen_x;
        const float dy = py - screen_y;
        const float screen_dist_sq = dx * dx + dy * dy;

        const float depth = dot(sub(point, camera_position), camera_forward);
        if (depth < 0.0f) {
            continue;
        }
        if (fallback_to_nearest &&
            (screen_dist_sq < nearest_screen_dist_sq ||
             (std::fabs(screen_dist_sq - nearest_screen_dist_sq) <= 1.0e-8f && depth < nearest_depth))) {
            nearest_screen_dist_sq = screen_dist_sq;
            nearest_depth = depth;
            nearest_index = index;
        }
        if (screen_dist_sq > radius_sq) {
            continue;
        }
        if (depth < best_depth) {
            best_depth = depth;
            best_index = index;
        }
    }
    return best_index >= 0 ? best_index : nearest_index;
}

FS_PICK_API int fs_pick_point_perspective(
    const float* points,
    const std::uint8_t* active_mask,
    int point_count,
    const float* camera_position_values,
    const float* camera_right_values,
    const float* camera_up_values,
    const float* camera_forward_values,
    float viewport_width,
    float viewport_height,
    float screen_x,
    float screen_y,
    float probe_radius_px,
    float focal_px,
    int fallback_to_nearest) {
    if (!points || point_count <= 0 || viewport_width <= 0.0f || viewport_height <= 0.0f || focal_px <= 0.0f) {
        return -1;
    }

    const Vec3 camera_position = load_vec3(camera_position_values);
    const Vec3 camera_right = load_vec3(camera_right_values);
    const Vec3 camera_up = load_vec3(camera_up_values);
    const Vec3 camera_forward = load_vec3(camera_forward_values);
    const float radius_sq = probe_radius_px * probe_radius_px;
    const float half_width = viewport_width * 0.5f;
    const float half_height = viewport_height * 0.5f;

    int best_index = -1;
    float best_depth = 3.402823466e+38F;
    float best_screen_dist_sq = 3.402823466e+38F;
    int nearest_index = -1;
    float nearest_ray_dist_sq = 3.402823466e+38F;
    float nearest_ray_depth = 3.402823466e+38F;
    const Vec3 ray_direction = normalize(
        add(
            add(camera_forward, mul(camera_right, (screen_x - half_width) / focal_px)),
            mul(camera_up, (half_height - screen_y) / focal_px)),
        camera_forward);
    for (int index = 0; index < point_count; ++index) {
        if (active_mask && !active_mask[index]) {
            continue;
        }
        const float* point_values = points + index * 3;
        const Vec3 point{point_values[0], point_values[1], point_values[2]};
        const Vec3 rel = sub(point, camera_position);
        const float depth = dot(rel, camera_forward);
        if (depth <= 1.0e-8f) {
            continue;
        }
        if (fallback_to_nearest) {
            const float ray_depth = dot(rel, ray_direction);
            if (ray_depth > 1.0e-8f) {
                const Vec3 ray_offset = sub(rel, mul(ray_direction, ray_depth));
                const float ray_dist_sq = length_sq(ray_offset);
                if (ray_dist_sq < nearest_ray_dist_sq ||
                    (std::fabs(ray_dist_sq - nearest_ray_dist_sq) <= 1.0e-8f && ray_depth < nearest_ray_depth)) {
                    nearest_ray_dist_sq = ray_dist_sq;
                    nearest_ray_depth = ray_depth;
                    nearest_index = index;
                }
            }
        }

        const float px = half_width + dot(rel, camera_right) * focal_px / depth;
        const float py = half_height - dot(rel, camera_up) * focal_px / depth;
        const float dx = px - screen_x;
        const float dy = py - screen_y;
        const float screen_dist_sq = dx * dx + dy * dy;
        if (screen_dist_sq > radius_sq) {
            continue;
        }
        if (screen_dist_sq < best_screen_dist_sq ||
            (screen_dist_sq - best_screen_dist_sq <= 1.0e-8f &&
             best_screen_dist_sq - screen_dist_sq <= 1.0e-8f && depth < best_depth)) {
            best_screen_dist_sq = screen_dist_sq;
            best_depth = depth;
            best_index = index;
        }
    }
    return best_index >= 0 ? best_index : nearest_index;
}

FS_PICK_API int fs_build_inlier_distance_histogram(
    const float* points,
    int point_count,
    const int* inlier_indices,
    int inlier_count,
    int surface_type,
    const double* surface_params,
    int requested_bin_count,
    double measurement_accuracy,
    double rms_error,
    HistogramResult* out_result,
    int* out_counts,
    double* out_starts,
    double* out_ends,
    double* out_centers,
    double* out_fractions,
    double* out_percents,
    double* out_sigma_offsets,
    std::uint8_t* out_sigma_offset_valid) {
    if (!points || point_count <= 0 || !inlier_indices || inlier_count <= 0 || !surface_params || !out_result ||
        !out_counts || !out_starts || !out_ends || !out_centers || !out_fractions || !out_percents ||
        !out_sigma_offsets || !out_sigma_offset_valid) {
        return 0;
    }

    std::vector<double> distances;
    distances.reserve(static_cast<std::size_t>(inlier_count));
    for (int i = 0; i < inlier_count; ++i) {
        const int index = inlier_indices[i];
        if (index < 0 || index >= point_count) {
            continue;
        }
        const Vec3d point = to_vec3d(points + index * 3);
        const double distance = surface_distance(surface_type, surface_params, point);
        if (std::isfinite(distance)) {
            distances.push_back(distance);
        }
    }
    if (distances.empty()) {
        return 0;
    }

    const int bin_count = normalized_bin_count(requested_bin_count);
    const int source_count = static_cast<int>(distances.size());
    const double source_sigma = standard_deviation(distances);
    double sigma = source_sigma;
    if (sigma <= 1.0e-12) {
        sigma = std::max(
            std::max(std::fabs(measurement_accuracy), std::fabs(rms_error)),
            1.0e-6);
    }
    const double half_range = 3.0 * sigma;
    const double range_min = -half_range;
    const double range_max = half_range;

    std::vector<double> histogram_distances;
    histogram_distances.reserve(distances.size());
    for (double distance : distances) {
        if (range_min <= distance && distance <= range_max) {
            histogram_distances.push_back(distance);
        }
    }

    const int count = static_cast<int>(histogram_distances.size());
    const int excluded_count = source_count - count;
    double sum = 0.0;
    for (double distance : histogram_distances) {
        sum += distance;
    }
    const double mean = count ? sum / static_cast<double>(count) : 0.0;
    double minimum = 0.0;
    double maximum = 0.0;
    if (count) {
        const auto minmax = std::minmax_element(histogram_distances.begin(), histogram_distances.end());
        minimum = *minmax.first;
        maximum = *minmax.second;
    }
    const double epsilon = count ? std::max(std::fabs(maximum - minimum) * 1.0e-12, 1.0e-12) : 1.0e-12;
    int negative_count = 0;
    int positive_count = 0;
    for (double distance : histogram_distances) {
        if (distance < -epsilon) {
            ++negative_count;
        } else if (distance > epsilon) {
            ++positive_count;
        }
    }
    const int zero_count = count - negative_count - positive_count;
    const double width = (range_max - range_min) / static_cast<double>(bin_count);
    for (int bin_index = 0; bin_index < bin_count; ++bin_index) {
        const double start = range_min + width * static_cast<double>(bin_index);
        const double end = start + width;
        const double center = start + width * 0.5;
        out_counts[bin_index] = 0;
        out_starts[bin_index] = start;
        out_ends[bin_index] = end;
        out_centers[bin_index] = center;
        out_fractions[bin_index] = 0.0;
        out_percents[bin_index] = 0.0;
        out_sigma_offsets[bin_index] = 0.0;
        out_sigma_offset_valid[bin_index] = 0;
    }

    for (double distance : histogram_distances) {
        int bin_index = 0;
        if (distance <= range_min) {
            bin_index = 0;
        } else if (distance >= range_max) {
            bin_index = bin_count - 1;
        } else {
            bin_index = static_cast<int>((distance - range_min) / width);
            bin_index = std::max(0, std::min(bin_count - 1, bin_index));
        }
        out_counts[bin_index] += 1;
    }

    int max_bin_count = 0;
    for (int bin_index = 0; bin_index < bin_count; ++bin_index) {
        max_bin_count = std::max(max_bin_count, out_counts[bin_index]);
    }
    for (int bin_index = 0; bin_index < bin_count; ++bin_index) {
        out_fractions[bin_index] = max_bin_count ? static_cast<double>(out_counts[bin_index]) / max_bin_count : 0.0;
        out_percents[bin_index] = source_count ? static_cast<double>(out_counts[bin_index]) * 100.0 / source_count : 0.0;
        if (sigma > 1.0e-12) {
            out_sigma_offsets[bin_index] = out_centers[bin_index] / sigma;
            out_sigma_offset_valid[bin_index] = 1;
        }
    }

    double mean_fraction = 0.5;
    double zero_fraction = 0.5;
    if (range_max > range_min) {
        mean_fraction = std::max(0.0, std::min(1.0, (mean - range_min) / (range_max - range_min)));
        zero_fraction = std::max(0.0, std::min(1.0, (0.0 - range_min) / (range_max - range_min)));
    }

    *out_result = HistogramResult{
        count,
        source_count,
        excluded_count,
        bin_count,
        negative_count,
        zero_count,
        positive_count,
        max_bin_count,
        minimum,
        maximum,
        mean,
        sigma,
        source_sigma,
        range_min,
        range_max,
        mean_fraction,
        zero_fraction,
    };
    return 1;
}
