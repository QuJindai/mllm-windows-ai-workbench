#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::string get_env(const char* name, const std::string& fallback = {}) {
    const char* value = std::getenv(name);
    return value == nullptr ? fallback : std::string(value);
}

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

std::string normalize_for_compare(const fs::path& value) {
    std::string text = value.lexically_normal().string();
    std::replace(text.begin(), text.end(), '/', '\\');
    return lower(text);
}

fs::path dream_root() {
    return fs::path(get_env("DREAM_HOME", "E:\\Dream"));
}

bool is_under_root(const fs::path& candidate, const fs::path& root) {
    const std::string candidate_text = normalize_for_compare(candidate);
    std::string root_text = normalize_for_compare(root);
    while (!root_text.empty() && root_text.back() == '\\') {
        root_text.pop_back();
    }
    return candidate_text == root_text ||
           (candidate_text.size() > root_text.size() &&
            candidate_text.compare(0, root_text.size(), root_text) == 0 &&
            candidate_text[root_text.size()] == '\\');
}

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (const char c : value) {
        switch (c) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default: out << c; break;
        }
    }
    return out.str();
}

void emit_error(const std::string& code, const std::string& message) {
    std::cout << "{\"ok\":false,\"code\":\"" << json_escape(code)
              << "\",\"message\":\"" << json_escape(message) << "\"}" << std::endl;
}

void print_help() {
    std::cout << "dream-core 0.1.0\n"
              << "Usage:\n"
              << "  dream-core --version\n"
              << "  dream-core hardware\n"
              << "  dream-core generate --model <id> --prompt <text> --negative <text>"
                 " --seed <int> --steps <int> --cfg <float> --width <int> --height <int>"
                 " --output <E-drive-png> --metadata <E-drive-json>\n";
}

bool find_option(const std::vector<std::string>& args, const std::string& name, std::string& value) {
    for (size_t index = 0; index + 1 < args.size(); ++index) {
        if (args[index] == name) {
            value = args[index + 1];
            return true;
        }
    }
    return false;
}

bool parse_positive_int(const std::string& value, int& parsed) {
    try {
        size_t consumed = 0;
        parsed = std::stoi(value, &consumed);
        return consumed == value.size() && parsed > 0;
    } catch (...) {
        return false;
    }
}

bool parse_float(const std::string& value, float& parsed) {
    try {
        size_t consumed = 0;
        parsed = std::stof(value, &consumed);
        return consumed == value.size() && parsed >= 0.0F;
    } catch (...) {
        return false;
    }
}

bool read_text(const fs::path& path, std::string& text) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return false;
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    text = buffer.str();
    return true;
}

std::string shell_quote(const std::string& value) {
    std::string quoted = "\"";
    for (const char c : value) {
        if (c == '"') {
            quoted += "\\\"";
        } else {
            quoted += c;
        }
    }
    quoted += "\"";
    return quoted;
}

std::string json_string_after(const std::string& text, const std::string& key, size_t start) {
    const size_t key_position = text.find(key, start);
    if (key_position == std::string::npos) {
        return {};
    }
    const size_t first_quote = text.find('"', key_position + key.size());
    if (first_quote == std::string::npos) {
        return {};
    }
    const size_t second_quote = text.find('"', first_quote + 1);
    if (second_quote == std::string::npos) {
        return {};
    }
    return text.substr(first_quote + 1, second_quote - first_quote - 1);
}

int command_hardware() {
    const fs::path path = dream_root() / "data" / "hardware.json";
    std::string hardware;
    if (!read_text(path, hardware)) {
        emit_error("DREAM_HARDWARE_MISSING", "Persisted hardware.json was not found under DREAM_HOME");
        return 2;
    }
    std::cout << hardware << std::endl;
    return 0;
}

int command_generate(const std::vector<std::string>& args) {
    const std::vector<std::string> required = {
        "--model", "--prompt", "--negative", "--seed", "--steps", "--cfg",
        "--width", "--height", "--output", "--metadata"
    };
    std::vector<std::string> values;
    for (const std::string& option : required) {
        std::string value;
        if (!find_option(args, option, value) || value.empty()) {
            emit_error("GENERATION_ARGUMENT_MISSING", "Required generation option is missing: " + option);
            return 2;
        }
        values.push_back(value);
    }

    int seed = 0;
    int steps = 0;
    int width = 0;
    int height = 0;
    float cfg = 0.0F;
    if (!parse_positive_int(values[3], seed) || !parse_positive_int(values[4], steps) ||
        !parse_float(values[5], cfg) || !parse_positive_int(values[6], width) ||
        !parse_positive_int(values[7], height)) {
        emit_error("GENERATION_ARGUMENT_INVALID", "seed, steps, cfg, width, and height must be valid positive values");
        return 2;
    }
    (void)seed;
    (void)steps;
    (void)cfg;
    (void)width;
    (void)height;

    const fs::path root = dream_root();
    const fs::path output = fs::path(values[8]);
    const fs::path metadata = fs::path(values[9]);
    if (!is_under_root(output, root) || !is_under_root(metadata, root)) {
        emit_error("E_DRIVE_OUTPUT_REQUIRED", "PNG and metadata outputs must be below DREAM_HOME");
        return 2;
    }
    if (lower(output.extension().string()) != ".png" || lower(metadata.extension().string()) != ".json") {
        emit_error("GENERATION_OUTPUT_INVALID", "Generation output must be a PNG and metadata must be JSON");
        return 2;
    }

    const fs::path registry_path = fs::path(get_env("DREAM_MODEL_REGISTRY", (root / "config" / "dream" / "model-registry.json").string()));
    std::string registry;
    if (!read_text(registry_path, registry)) {
        emit_error("MODEL_REGISTRY_MISSING", "Model registry was not found on E:");
        return 3;
    }
    const std::string model_id = values[0];
    const std::string model_key = "\"model_id\": \"" + model_id + "\"";
    const size_t model_position = registry.find(model_key);
    if (model_position == std::string::npos) {
        emit_error("MODEL_NOT_REGISTERED", "Requested model is not present in the registry: " + model_id);
        return 3;
    }
    const std::string status = json_string_after(registry, "\"status\":", model_position);
    if (status == "uninstalled") {
        emit_error("MODEL_UNINSTALLED", "Registered model is explicitly uninstalled; W1 generation is blocked");
        return 3;
    }
    if (status != "installed") {
        emit_error("MODEL_STATUS_INVALID", "Registered model does not have installed status");
        return 3;
    }

    const std::string engine_value = get_env("DREAM_STABLE_DIFFUSION_CPP_EXE");
    if (engine_value.empty() || !fs::exists(fs::path(engine_value))) {
        emit_error("DREAM_DEPENDENCY_MISSING", "stable-diffusion.cpp CUDA executable is not configured and present");
        return 3;
    }
    const std::string wrapper_value = get_env("DREAM_SDCPP_GENERATE_WRAPPER");
    if (wrapper_value.empty() || !fs::exists(fs::path(wrapper_value))) {
        emit_error("DREAM_DEPENDENCY_MISSING", "A verified stable-diffusion.cpp generation wrapper is not configured");
        return 3;
    }

    const size_t windows_position = registry.find("\"windows\"", model_position);
    const std::string model_path_text = json_string_after(registry, "\"path\":", windows_position);
    const fs::path model_path = fs::path(model_path_text);
    if (model_path_text.empty() || !is_under_root(model_path, root) || !fs::exists(model_path)) {
        emit_error("MODEL_FILE_MISSING", "Installed registry entry does not point to an existing E-drive GGUF");
        return 3;
    }

    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    const auto stamp = std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
    const fs::path request_path = root / "temp" / ("dream-core-request-" + std::to_string(stamp) + ".json");
    const fs::path log_path = root / "logs" / "w1" / ("dream-core-wrapper-" + std::to_string(stamp) + ".log");
    std::error_code filesystem_error;
    fs::create_directories(request_path.parent_path(), filesystem_error);
    fs::create_directories(log_path.parent_path(), filesystem_error);
    if (!is_under_root(request_path, root) || !is_under_root(log_path, root)) {
        emit_error("E_DRIVE_OUTPUT_REQUIRED", "Native request and log paths must be below DREAM_HOME");
        return 2;
    }

    std::ofstream request(request_path, std::ios::binary);
    if (!request) {
        emit_error("NATIVE_REQUEST_WRITE_FAILED", "Could not write the native request under E:\\Dream");
        return 4;
    }
    request << "{\"model_id\":\"" << json_escape(model_id)
            << "\",\"model_path\":\"" << json_escape(model_path.string())
            << "\",\"prompt\":\"" << json_escape(values[1])
            << "\",\"negative\":\"" << json_escape(values[2])
            << "\",\"seed\":" << seed
            << ",\"steps\":" << steps
            << ",\"cfg\":" << cfg
            << ",\"width\":" << width
            << ",\"height\":" << height
            << ",\"output\":\"" << json_escape(output.string())
            << "\",\"metadata\":\"" << json_escape(metadata.string())
            << "\"}" << std::endl;
    request.close();

    // The wrapper is the only native-backend invocation point. It receives a
    // validated E-drive request, invokes the exact stable-diffusion.cpp build,
    // and must return non-zero on any backend failure.
    const std::string command = shell_quote(wrapper_value) + " --request " + shell_quote(request_path.string()) +
                                " > " + shell_quote(log_path.string()) + " 2>&1";
    const auto start = std::chrono::steady_clock::now();
    const int native_exit = std::system(command.c_str());
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count();
    if (native_exit != 0) {
        emit_error("NATIVE_BACKEND_FAILED", "stable-diffusion.cpp wrapper failed; see E-drive wrapper log");
        std::cout << "{\"wrapper_log\":\"" << json_escape(log_path.string())
                  << "\",\"exit_code\":" << native_exit << "}" << std::endl;
        return 4;
    }
    if (!fs::exists(output) || !fs::exists(metadata)) {
        emit_error("NATIVE_BACKEND_OUTPUT_MISSING", "Native wrapper returned success without both PNG and metadata");
        return 4;
    }
    std::cout << "{\"ok\":true,\"output\":\"" << json_escape(output.string())
              << "\",\"metadata\":\"" << json_escape(metadata.string())
              << "\",\"wrapper_log\":\"" << json_escape(log_path.string())
              << "\",\"generation_time_ms\":" << elapsed << "}" << std::endl;
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        print_help();
        return 2;
    }

    std::vector<std::string> args(argv + 1, argv + argc);
    if (args[0] == "--help" || args[0] == "-h") {
        print_help();
        return 0;
    }
    if (args[0] == "--version") {
        std::cout << "dream-core 0.1.0 backend=stable-diffusion.cpp+CUDA" << std::endl;
        return 0;
    }
    if (args[0] == "hardware") {
        return command_hardware();
    }
    if (args[0] == "generate") {
        return command_generate(std::vector<std::string>(args.begin() + 1, args.end()));
    }

    emit_error("UNKNOWN_COMMAND", "Unsupported command: " + args[0]);
    return 2;
}
