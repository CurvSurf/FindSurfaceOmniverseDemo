repo_build = require("omni/repo/build")

root = repo_build.get_abs_path(".")

kit = require("_repo/deps/repo_kit_tools/kit-template/premake5-kit")
kit.setup_all({ cppdialect = "C++17" })

repo_build.prebuild_copy {
    { "%{root}/tools/deps/user.toml", "%{root}/_build/deps/user.toml" },
    { "%{root}/source/native", "%{root}/_build/%{platform}/%{config}/source/native" },
}

define_app("com.curvsurf.findsurface_omniverse_demo.kit")
