#!/usr/bin/env bash

findsurface_select_kit_executable() {
    local cli_value="${1:-}"
    if [[ -n "$cli_value" ]]; then
        printf '%s\n' "$cli_value"
    elif [[ -n "${KIT_EXECUTABLE:-}" ]]; then
        printf '%s\n' "$KIT_EXECUTABLE"
    else
        printf '%s\n' "${KIT_EXE:-}"
    fi
}

findsurface_require_kit_executable() {
    local kit_executable="$1"
    if [[ -z "$kit_executable" ]]; then
        echo "Set KIT_EXECUTABLE or pass --kit-executable with the path to the Kit executable." >&2
        echo "KIT_EXE and --kit-exe are still accepted as compatibility aliases." >&2
        return 1
    fi
    if [[ ! -x "$kit_executable" ]]; then
        echo "Kit executable was not found or is not executable: $kit_executable" >&2
        return 1
    fi
}

findsurface_default_extension_root() {
    local project_root="$1"
    if [[ -f "$project_root/source/extensions/com.findsurface.bootstrap/config/extension.toml" ]]; then
        printf '%s\n' "$project_root/source/extensions/com.findsurface.bootstrap"
    elif [[ -f "$project_root/FindSurfaceExtension/config/extension.toml" ]]; then
        printf '%s\n' "$project_root/FindSurfaceExtension"
    else
        printf '%s\n' "$project_root"
    fi
}

findsurface_extension_folder() {
    local extension_root="$1"
    if [[ -f "$extension_root/config/extension.toml" ]]; then
        dirname "$extension_root"
    else
        printf '%s\n' "$extension_root/source/extensions"
    fi
}

findsurface_picker_path() {
    local project_root="$1"
    case "$(uname -s)" in
        Linux*)
            if [[ -f "$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/linux-x86_64/libFindSurfacePicking.so" ]]; then
                printf '%s\n' "$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/linux-x86_64/libFindSurfacePicking.so"
            else
                printf '%s\n' "$project_root/FindSurface/lib/libFindSurfacePicking.so"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            if [[ -f "$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/windows-x86_64/FindSurfacePicking.dll" ]]; then
                printf '%s\n' "$project_root/source/extensions/com.curvsurf.findsurface_omniverse/data/native/windows-x86_64/FindSurfacePicking.dll"
            else
                printf '%s\n' "$project_root/FindSurface/bin/FindSurfacePicking.dll"
            fi
            ;;
        *) return 1 ;;
    esac
}

findsurface_core_sdk_path() {
    local extension_root="$1"
    case "$(uname -s)" in
        Linux*)
            if [[ -f "$extension_root/data/native/linux-x86_64/libFindSurface.so" ]] || [[ -f "$extension_root/config/extension.toml" ]]; then
                printf '%s\n' "$extension_root/data/native/linux-x86_64/libFindSurface.so"
            elif [[ -f "$extension_root/source/extensions/com.findsurface.bootstrap/data/native/linux-x86_64/libFindSurface.so" ]]; then
                printf '%s\n' "$extension_root/source/extensions/com.findsurface.bootstrap/data/native/linux-x86_64/libFindSurface.so"
            else
                printf '%s\n' "$extension_root/FindSurface/lib/libFindSurface.so"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            if [[ -f "$extension_root/data/native/windows-x86_64/FindSurface.dll" ]] || [[ -f "$extension_root/config/extension.toml" ]]; then
                printf '%s\n' "$extension_root/data/native/windows-x86_64/FindSurface.dll"
            elif [[ -f "$extension_root/source/extensions/com.findsurface.bootstrap/data/native/windows-x86_64/FindSurface.dll" ]]; then
                printf '%s\n' "$extension_root/source/extensions/com.findsurface.bootstrap/data/native/windows-x86_64/FindSurface.dll"
            else
                printf '%s\n' "$extension_root/FindSurface/bin/FindSurface.dll"
            fi
            ;;
        *) return 1 ;;
    esac
}

findsurface_fetch_core_sdk() {
    local extension_root="$1"
    local asset_key="$2"
    local fetch_tool="$extension_root/tools/fetch_findsurface_sdk.py"
    local python_executable="${PYTHON:-python3}"

    if [[ ! -f "$fetch_tool" ]]; then
        echo "FindSurface SDK acquisition helper was not found: $fetch_tool" >&2
        return 1
    fi

    "$python_executable" "$fetch_tool" --extension-root "$extension_root" --asset-key "$asset_key"
}

findsurface_ensure_native_runtime() {
    local project_root="$1"
    local extension_root="$2"
    local ext_folder
    ext_folder="$(findsurface_extension_folder "$extension_root")"

    if [[ ! -d "$ext_folder" ]]; then
        echo "FindSurface extension folder was not found: $ext_folder" >&2
        return 1
    fi

    local picker_path
    picker_path="$(findsurface_picker_path "$project_root")" || {
        echo "Unsupported platform for FindSurface picker: $(uname -s)" >&2
        return 1
    }

    if [[ ! -f "$picker_path" ]]; then
        echo "FindSurface picker helper was not found; building it now: $picker_path"
        if ! "$project_root/tools/build_picker.sh" --findsurface-extension-root "$extension_root"; then
            cat >&2 <<EOF
Failed to build the FindSurface picker helper.
Install the build dependencies and retry:
  sudo apt install build-essential cmake
  ./tools/build_picker.sh
EOF
            return 1
        fi
    fi

    if [[ ! -f "$picker_path" ]]; then
        echo "FindSurface picker helper is still missing after build: $picker_path" >&2
        return 1
    fi

    if [[ -n "${FINDSURFACE_APP_SDK_PATH:-}" ]]; then
        [[ -f "$FINDSURFACE_APP_SDK_PATH" ]] || {
            echo 'Explicit FINDSURFACE_APP_SDK_PATH does not exist.' >&2
            return 1
        }
        return 0
    fi
    local core_sdk_path
    local core_sdk_asset_key
    core_sdk_path="$(findsurface_core_sdk_path "$extension_root")" || {
        echo "Unsupported platform for FindSurface SDK: $(uname -s)" >&2
        return 1
    }
    case "$(uname -s)" in
        Linux*) core_sdk_asset_key="linux-x86_64" ;;
        MINGW*|MSYS*|CYGWIN*) core_sdk_asset_key="windows-x86_64" ;;
        *) echo "Unsupported platform for FindSurface SDK: $(uname -s)" >&2; return 1 ;;
    esac

    if [[ "$extension_root" == "$(findsurface_default_extension_root "$project_root")" ]]; then
        "${PYTHON:-python3}" "$project_root/tools/update_sdk.py" --sdk-path "$core_sdk_path" --asset-key "$core_sdk_asset_key" || return 1
    elif [[ ! -f "$core_sdk_path" ]]; then
        echo "FindSurface native SDK library was not found; downloading it now: $core_sdk_path"
        findsurface_fetch_core_sdk "$extension_root" "$core_sdk_asset_key" || return 1
    fi

    if [[ ! -f "$core_sdk_path" ]]; then
        echo "FindSurface native SDK library is still missing after download: $core_sdk_path" >&2
        return 1
    fi
}
