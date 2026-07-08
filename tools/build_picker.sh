#!/usr/bin/env bash
set -euo pipefail

compiler="${FINDSURFACE_PICKING_COMPILER:-}"
build_dir=""
config="Release"

usage() {
    cat <<'USAGE'
Usage: tools/build_picker.sh [options]

Options:
  --findsurface-extension-root PATH      Compatibility option; ignored.
  --compiler PATH                        C++ compiler to pass to CMake.
  --build-dir PATH                       CMake build directory. Defaults to build/picker.
  --config NAME                          Build configuration. Defaults to Release.
  -h, --help                             Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --findsurface-extension-root|-FindSurfaceExtensionRoot)
            shift 2
            ;;
        --compiler)
            compiler="${2:?Missing value for $1}"
            shift 2
            ;;
        --build-dir)
            build_dir="${2:?Missing value for $1}"
            shift 2
            ;;
        --config)
            config="${2:?Missing value for $1}"
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

if ! command -v cmake >/dev/null 2>&1; then
    echo "CMake was not found in PATH. Install it, for example: sudo apt install cmake" >&2
    exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd -- "$script_dir/.." && pwd -P)"
source_dir="$project_root/source/native"
if [[ -z "$build_dir" ]]; then
    build_dir="$project_root/build/picker"
fi

configure_args=(-S "$source_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE="$config")
if [[ -n "$compiler" ]]; then
    configure_args+=(-DCMAKE_CXX_COMPILER="$compiler")
fi

cmake "${configure_args[@]}"
cmake --build "$build_dir" --config "$config"

case "$(uname -s)" in
    Linux*)
        output="$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/linux-x86_64/libFindSurfacePicking.so"
        legacy_output="$project_root/FindSurface/lib/libFindSurfacePicking.so"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        output="$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/windows-x86_64/FindSurfacePicking.dll"
        legacy_output="$project_root/FindSurface/bin/FindSurfacePicking.dll"
        ;;
    *)
        echo "Unsupported picker build platform: $(uname -s)" >&2
        exit 1
        ;;
esac

if [[ ! -f "$output" ]]; then
    echo "Picker build did not create expected output: $output" >&2
    exit 1
fi

if [[ "$output" != "$legacy_output" ]]; then
    mkdir -p "$(dirname -- "$legacy_output")"
    cp -f "$output" "$legacy_output"
fi

echo "Built $output"
