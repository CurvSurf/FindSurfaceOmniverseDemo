# Native FindSurface SDK Setup

The demo app uses the native FindSurface SDK for surface detection. The native
SDK binaries are not tracked in this Git repository.

On Windows, `Start_Demo.bat` reuses an existing DLL as external or downloads a
hash-verified DLL into its private installation. It supplies the path only to
the launched process through `FINDSURFACE_APP_SDK_PATH`. The removal script never
deletes external DLLs. See [INSTALL.md](INSTALL.md) for this ownership-aware path;
the legacy in-app download behavior described below remains available when
launching without the manager.

When the app starts and the native SDK library is missing, it tries to download
the matching binary from the release configured by the bootstrap extension. If
the download fails because the computer is offline or the release asset does not
exist, the app still opens but FindSurface detection is disabled.

## Automatic Download

The release source of truth is:

```text
source/extensions/com.findsurface.bootstrap/config/sdk_release.json
```

That file defines the GitHub release base URL, the release tag, and the asset
names for Windows and Linux. Update that file when the native SDK release tag
changes. The demo app setup guide link is configured separately here:

```text
source/extensions/com.curvsurf.findsurface_omniverse/data/release.json
```

Expected asset names:

```text
Windows: FindSurface.dll
Linux:   libFindSurface.so
```

Set `FINDSURFACE_SDK_AUTO_DOWNLOAD=0` to disable automatic download.

## Manual Install

If automatic download fails, download the correct file manually from the
configured [GitHub release](https://github.com/CurvSurf/FindSurfaceOmniverseExtension/releases) and place it in the matching folder.

Development checkout paths:

```text
Windows:
source/extensions/com.findsurface.bootstrap/data/native/windows-x86_64/FindSurface.dll

Linux:
source/extensions/com.findsurface.bootstrap/data/native/linux-x86_64/libFindSurface.so
```

Thin package paths:

```text
Windows:
exts/com.findsurface.bootstrap/data/native/windows-x86_64/FindSurface.dll

Linux:
exts/com.findsurface.bootstrap/data/native/linux-x86_64/libFindSurface.so
```

After placing the file, restart the demo app. If the file is present but still
cannot be loaded, confirm that the binary matches the operating system,
architecture, and any required runtime dependencies.
