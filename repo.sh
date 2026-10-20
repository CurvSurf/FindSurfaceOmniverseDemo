#!/bin/bash

set -e

# Set OMNI_REPO_ROOT early so `repo` bootstrapping can target the repository
# root when writing out Python dependencies.
export OMNI_REPO_ROOT="$( cd "$(dirname "$0")" ; pwd -P )"
export PATH="${OMNI_REPO_ROOT}/tools/bin:${PATH}"

# Keep repo tooling independent of the host locale when it reads UTF-8 config
# files from Packman packages or this repository.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# By default custom caching is disabled in repo_man. But if a repo-cache.json
# caching configuration file is generated via the `repo cache` command, it's
# presence will trigger the configuration of custom caching.
if [[ -f "${OMNI_REPO_ROOT}/repo-cache.json" ]]; then
    PM_PACKAGES_ROOT=$(grep '"PM_PACKAGES_ROOT"' "${OMNI_REPO_ROOT}/repo-cache.json" | sed 's/.*"PM_PACKAGES_ROOT": "\(.*\)".*/\1/')

    # PM_PACKAGES_ROOT is present in the config file. We set this early
    # so Packman will reference our cached package repository.
    if [[ -n "${PM_PACKAGES_ROOT}" ]]; then
        # Use eval to resolve ~ and perform parameter expansion
        RESOLVED_PACKAGES_ROOT=$(eval echo "$PM_PACKAGES_ROOT")

        if [[ "${RESOLVED_PACKAGES_ROOT}" != /* ]]; then
            # PM_PACKAGES_ROOT is not an abs path, assumption is then
            # that it is a relative path to the repository root.
            PM_PACKAGES_ROOT="${OMNI_REPO_ROOT}/${RESOLVED_PACKAGES_ROOT}"
        else
            PM_PACKAGES_ROOT=${RESOLVED_PACKAGES_ROOT}
        fi
        export PM_PACKAGES_ROOT
    fi
fi

if [[ "${1:-}" == "launch" && -z "${FINDSURFACE_APP_SDK_PATH:-}" ]]; then
    sdk_root="${OMNI_REPO_ROOT}/source/extensions/com.findsurface.bootstrap"
    if [[ ! -f "$sdk_root/config/extension.toml" ]]; then
        echo 'Initialize submodules and build the app before launching.' >&2
        exit 1
    fi
    "${OMNI_REPO_ROOT}/tools/packman/python.sh" "${OMNI_REPO_ROOT}/tools/update_sdk.py" \
        --sdk-path "$sdk_root/data/native/linux-x86_64/libFindSurface.so" --asset-key linux-x86_64
fi

if [[ "${1:-}" == "launch" && "$#" -eq 1 ]]; then
    set -- launch com.curvsurf.findsurface_omniverse_demo.kit
fi

# Use "exec" to ensure that environment variables don't accidentally affect other processes.
exec "${OMNI_REPO_ROOT}/tools/packman/python.sh" "${OMNI_REPO_ROOT}/tools/repoman/repoman.py" "$@"
