cmake_minimum_required(VERSION 3.16)

project(FindSurfacePicking LANGUAGES CXX)

get_filename_component(FINDSURFACE_APP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)

add_library(FindSurfacePicking SHARED FindSurfacePicking.cpp)
target_compile_features(FindSurfacePicking PRIVATE cxx_std_17)
set_target_properties(FindSurfacePicking PROPERTIES
    CXX_EXTENSIONS OFF
    OUTPUT_NAME "FindSurfacePicking"
)

if(WIN32)
    set_target_properties(FindSurfacePicking PROPERTIES
        PREFIX ""
    )
else()
    set_target_properties(FindSurfacePicking PROPERTIES
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN YES
        POSITION_INDEPENDENT_CODE ON
    )
endif()

if(WIN32)
    if(MINGW)
        target_link_options(FindSurfacePicking PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
    set(FS_PICKER_DEFAULT_OUTPUT_DIR "${FINDSURFACE_APP_ROOT}/source/extensions/com.curvsurf.findsurface_omniverse/data/native/windows-x86_64")
else()
    set(FS_PICKER_DEFAULT_OUTPUT_DIR "${FINDSURFACE_APP_ROOT}/source/extensions/com.curvsurf.findsurface_omniverse/data/native/linux-x86_64")
endif()

if(NOT DEFINED FS_PICKER_OUTPUT_DIR)
    set(FS_PICKER_OUTPUT_DIR "${FS_PICKER_DEFAULT_OUTPUT_DIR}")
endif()

set_target_properties(FindSurfacePicking PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${FS_PICKER_OUTPUT_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${FS_PICKER_OUTPUT_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${FS_PICKER_OUTPUT_DIR}"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(FindSurfacePicking PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${FS_PICKER_OUTPUT_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${FS_PICKER_OUTPUT_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${FS_PICKER_OUTPUT_DIR}"
    )
endforeach()
