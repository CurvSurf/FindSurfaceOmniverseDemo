repo_build = require("omni/repo/build")

root = repo_build.get_abs_path(".")

kit = require("_repo/deps/repo_kit_tools/kit-template/premake5-kit")
kit.setup_all({ cppdialect = "C++17" })

repo_build.prebuild_copy {
    { "%{root}/Start_Demo.bat", "%{root}/_build/%{platform}/%{config}/Start_Demo.bat" },
    { "%{root}/Remove_Demo.bat", "%{root}/_build/%{platform}/%{config}/Remove_Demo.bat" },
    { "%{root}/INSTALL.md", "%{root}/_build/%{platform}/%{config}/INSTALL.md" },
    { "%{root}/tools/manage_installation.ps1", "%{root}/_build/%{platform}/%{config}/tools/manage_installation.ps1" },
    { "%{root}/tools/dependency_ownership.ps1", "%{root}/_build/%{platform}/%{config}/tools/dependency_ownership.ps1" },
    { "%{root}/tools/deps/user.toml", "%{root}/_build/deps/user.toml" },
    { "%{root}/source/native", "%{root}/_build/%{platform}/%{config}/source/native" },
}

define_app("com.curvsurf.findsurface_omniverse_demo.kit")
