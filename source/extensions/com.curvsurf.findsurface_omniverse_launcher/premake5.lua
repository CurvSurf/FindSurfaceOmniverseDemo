local ext = get_current_extension_info()
project_ext(ext)
repo_build.prebuild_link {
    { "config", ext.target_dir.."/config" },
    { "docs", ext.target_dir.."/docs" },
    { "data", ext.target_dir.."/data" },
    { "findsurface_omniverse_launcher", ext.target_dir.."/findsurface_omniverse_launcher" },
}
