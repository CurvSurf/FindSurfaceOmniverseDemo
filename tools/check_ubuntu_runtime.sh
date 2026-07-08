#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/_findsurface_linux.sh"

kit_executable_cli=""
findsurface_extension_root="${FINDSURFACE_EXTENSION_ROOT:-}"

usage() {
    cat <<'USAGE'
Usage: tools/check_ubuntu_runtime.sh [options]

Options:
  --kit-executable PATH                  Linux Kit executable.
  --kit-exe PATH                         Compatibility alias for --kit-executable.
  --findsurface-extension-root PATH      Repository root containing source/extensions. Defaults to this project.
  -h, --help                             Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit-executable|--kit-exe|-KitExe)
            kit_executable_cli="${2:?Missing value for $1}"
            shift 2
            ;;
        --findsurface-extension-root|-FindSurfaceExtensionRoot)
            findsurface_extension_root="${2:?Missing value for $1}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd -- "$script_dir/.." && pwd -P)"
if [[ -z "$findsurface_extension_root" ]]; then
    findsurface_extension_root="$project_root"
fi

kit_executable="$(findsurface_select_kit_executable "$kit_executable_cli")"

status=0
check_file() {
    local label="$1"
    local path="$2"
    if [[ -f "$path" ]]; then
        echo "OK: $label: $path"
    else
        echo "MISSING: $label: $path" >&2
        status=1
    fi
}

check_dir() {
    local label="$1"
    local path="$2"
    if [[ -d "$path" ]]; then
        echo "OK: $label: $path"
    else
        echo "MISSING: $label: $path" >&2
        status=1
    fi
}

if [[ -n "$kit_executable" && -x "$kit_executable" ]]; then
    echo "OK: Kit executable: $kit_executable"
else
    echo "MISSING: Kit executable. Set KIT_EXECUTABLE or pass --kit-executable." >&2
    status=1
fi

check_file "FindSurface app" "$project_root/source/apps/com.curvsurf.findsurface_omniverse_demo.kit"
check_dir "FindSurface extension folder" "$findsurface_extension_root/source/extensions"
core_sdk_path="$(findsurface_core_sdk_path "$findsurface_extension_root")"
check_file "FindSurface core SDK" "$core_sdk_path"

picker_path="$(findsurface_picker_path "$project_root")"
if [[ -f "$picker_path" ]]; then
    echo "OK: FindSurface picker helper: $picker_path"
else
    echo "MISSING: FindSurface picker helper: $picker_path"
    echo "Attempting to build picker helper..."
    if "$project_root/tools/build_picker.sh" --findsurface-extension-root "$findsurface_extension_root"; then
        check_file "FindSurface picker helper" "$picker_path"
    else
        echo "FAILED: picker helper build. Install dependencies: sudo apt install build-essential cmake" >&2
        status=1
    fi
fi

if command -v cmake >/dev/null 2>&1; then
    echo "OK: cmake: $(command -v cmake)"
else
    echo "WARN: cmake was not found; needed only when rebuilding the picker helper."
fi

if command -v g++ >/dev/null 2>&1; then
    echo "OK: g++: $(command -v g++)"
else
    echo "WARN: g++ was not found; needed only when rebuilding the picker helper."
fi

if command -v nvidia-smi >/dev/null 2>&1; then
    echo "OK: nvidia-smi is available"
else
    echo "WARN: nvidia-smi was not found; verify the NVIDIA driver on the target machine."
fi

if command -v vulkaninfo >/dev/null 2>&1; then
    echo "OK: vulkaninfo is available"
else
    echo "WARN: vulkaninfo was not found; install vulkan-tools if Kit reports Vulkan issues."
fi

exit "$status"
