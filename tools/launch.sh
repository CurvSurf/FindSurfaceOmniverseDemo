#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/_findsurface_linux.sh"

kit_executable_cli=""
findsurface_extension_root="${FINDSURFACE_EXTENSION_ROOT:-}"
args=()

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
        --)
            shift
            args+=("$@")
            break
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

kit_executable="$(findsurface_select_kit_executable "$kit_executable_cli")"
findsurface_require_kit_executable "$kit_executable"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
root="$(cd -- "$script_dir/.." && pwd -P)"
app_file="$root/source/apps/com.curvsurf.findsurface_omniverse_demo.kit"

if [[ -z "$findsurface_extension_root" ]]; then
    findsurface_extension_root="$(findsurface_default_extension_root "$root")"
fi

ext_folder="$(findsurface_extension_folder "$findsurface_extension_root")"
findsurface_ensure_native_runtime "$root" "$findsurface_extension_root"

exec "$kit_executable" "$app_file" --ext-folder "$ext_folder" "${args[@]}"
