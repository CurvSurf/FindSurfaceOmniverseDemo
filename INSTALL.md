# Windows installation and removal

Run `Start_Demo.bat` from a recursive source clone or a Windows thin release
package. It reuses a compatible Kit 110.1.2 runtime and an existing FindSurface
DLL when available. Reused dependencies are recorded as **external** and are
never deleted by `Remove_Demo.bat`.

Kit discovery checks `-KitRoot`, `KIT_ROOT`, the package's `kit` directory, and
the source checkout's `_build/windows-x86_64/release/kit`. Version metadata and
required executable files are checked; the SDK is also loaded with Kit Python
before launch. A compatible GPU driver is still required. This script does not
install Git, update drivers, or pull application changes.

## Missing dependencies

The default installation base is
`%LOCALAPPDATA%\CurvSurf\FindSurfaceOmniverseDemo`. You can choose another base
when prompted. Each checkout gets a separate `fsod-<UUID>` directory, an owner
marker, and a local `.installation/manifest.json` recording exact paths and
ownership. No global PATH or environment settings are changed.

- A source checkout copies build inputs into its private workspace and runs
  NVIDIA's `repo.bat build` there. Git metadata, DLLs and user defaults are not
  copied. An automatic GitHub source ZIP lacks the extension submodule; use a
  recursive clone or an assembled thin release instead.
- A thin package copies its installer inputs into a private workspace and runs
  `pull_kit_sdk.bat` there.
- Packman, pip and uv cache paths are directed into the private root. Inherited
  Packman bootstrap variables are cleared for setup and restored afterwards.
- A missing DLL is downloaded over HTTPS into the private root, verified against
  the configured release's pinned SHA-256, and passed through the child process's
  `FINDSURFACE_APP_SDK_PATH`. DLLs are not stored in Git. A new SDK release requires
  updating its tag and verified digest together.

NVIDIA's applicable license terms must be accepted before downloading runtime
dependencies. Download failures retain partial files for diagnosis; verified
download caches can be reused. An incomplete runtime build is retained rather
than silently reused: inspect it, remove the private installation, then retry.

```powershell
.\Start_Demo.bat -PrepareOnly
.\Start_Demo.bat -KitRoot "D:\ExistingKit"
.\Start_Demo.bat -InstallBase "D:\DemoDependencies"
```

`-PrepareOnly` validates/prepares dependencies without opening the app. Ordinary
developer `repo.bat` commands remain available and retain their existing cache
behavior; they are not automatically adopted as owned installations.

## Safe removal

Close all Kit apps, then run `Remove_Demo.bat`. Review the exact private folder
and the external dependencies that will be preserved, then type `REMOVE` to
confirm permanent deletion. Only the recorded private root and its installation
manifest are removed. The checkout, user data, reused Kit/DLL files and shared
NVIDIA caches/settings remain untouched.

Removal refuses a missing/mismatched owner marker, another checkout's record,
a broad directory, running Kit processes, or unknown/external junction targets.
Internal build links are checked and unlinked without following their targets
before deleting the owned directory. Concurrent operations on the same checkout
are blocked. Do not manually remove ownership records before using the remover.
Other software can still reference any private directory by absolute path;
check such references before confirming deletion.

## Existing users and upgrades

Existing clones can pull the update and reuse their supported runtime without
reinstalling. Installations without ownership records remain external: neither
old `_build` contents nor shared Packman caches are automatically deleted.
For ZIP upgrades, extract into a new directory. If reusing a runtime from an old
ZIP folder, keep that folder until all references have been checked; do not
delete it just because the new version runs. A moved checkout's old ownership
record is intentionally rejected. Restore its original location to remove the
private installation, or inspect the record manually before any cleanup.

## Validation boundary

Ownership/removal safety tests, existing-runtime preparation, SDK loading and
an actual Kit UI smoke test have been run. Fresh source builds and thin-package
downloads on a clean Windows machine remain release validation gates. Packaging
rules include these scripts, but a newly assembled release ZIP must still be
tested before distribution.
