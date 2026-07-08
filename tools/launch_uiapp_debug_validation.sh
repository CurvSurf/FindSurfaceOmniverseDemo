#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/_findsurface_linux.sh"

kit_executable_cli=""
args=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit-executable|--kit-exe|-KitExe)
            kit_executable_cli="${2:?Missing value for $1}"
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
app_file="$root/source/apps/uiapp.debug-validation.kit"

exec "$kit_executable" "$app_file" "${args[@]}"
