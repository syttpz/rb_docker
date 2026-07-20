####
# Author : Sarthak Tickoo (NYU IT HSRN)
# Corelink C++ Client Library
####

# specify the minimum cmake version required.
cmake_minimum_required(VERSION 3.20)

# specify project details. this is not fixed, and will change in the future.
project(corelink-client VERSION 1.0.0
        LANGUAGES C CXX)

if (EXISTS "${PROJECT_SOURCE_DIR}/CMakeListsUser.txt")
    include("${PROJECT_SOURCE_DIR}/CMakeListsUser.txt")
endif ()

# Sarthak: This is a MSVC Specific problem. The error here is well understood and accounted for
# however, since the warning levels are set to the highest, it flags it and inundates the build logs
if (WIN32)
    add_definitions("/wd4251")
endif ()

# we use C++11 as a minimum.
# The client has been compiled with C++ 11, 14 and 17 with warning set as errors.
# It is being made more robust cross platform as we speak
set(CMAKE_CXX_STANDARD_REQUIRED True)

# set the C++ standard we want to use
# set(CMAKE_CXX_STANDARD 11)

# specify the target name as a variable
set(CORELINK_TARGET corelinkclient)

file(GLOB_RECURSE CORELINK_SOURCES "src/**/*.cc")

# prepare the target for build
add_library(${CORELINK_TARGET} SHARED ${CORELINK_SOURCES})

#add_executable(${CORELINK_TARGET} )

# force treatment of warnings as errors. this saves lives. trust me.
target_compile_options(${CORELINK_TARGET} PRIVATE
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /WX>
        $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wall -Wextra -Wpedantic -Werror -Wno-deprecated-declarations>
)

target_compile_definitions(${CORELINK_TARGET} PUBLIC
        CORELINK_ENABLE_ALL_FEATURES
        CORELINK_USE_CONCURRENT_QUEUE
        CORELINK_USE_UDP
        CORELINK_USE_TCP
        CORELINK_USE_WEBSOCKET
)

# Add the include paths that are needed
target_include_directories(${CORELINK_TARGET}
        PUBLIC "include"
        PUBLIC "${CORELINK_ASIO_CPP_PATH}"
        PUBLIC "${CORELINK_RAPID_JSON_CPP_PATH}"
        PUBLIC "${CORELINK_LWS_INCLUDE_PATH}"
        PUBLIC "${CORELINK_OPENSSL_INCLUDE_PATH}"
)
# Add the paths for libraries to be linked
target_link_directories(${CORELINK_TARGET}
        PUBLIC "${CORELINK_LWS_LIB_PATH}"
        PUBLIC "${CORELINK_OPENSSL_LIB_PATH}"
        PUBLIC "${CORELINK_OPENSSL_BIN_PATH}"
)
# set the dynamic library extension and prefix. This is dumb but works for now.
set(DYNA_LIB_EXT so)
set(LWS_PREFIX lib)
if (APPLE)
    set(DYNA_LIB_EXT dylib)
endif (APPLE)
if (WIN32)
    set(DYNA_LIB_EXT dll)
    set(LWS_PREFIX "")
endif (WIN32)
# specify which libraries need to be linked against our target
target_link_libraries(${CORELINK_TARGET} ${LWS_PREFIX}websockets.${DYNA_LIB_EXT} libssl.${DYNA_LIB_EXT} libcrypto.${DYNA_LIB_EXT})