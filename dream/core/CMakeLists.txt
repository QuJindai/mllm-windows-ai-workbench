cmake_minimum_required(VERSION 3.20)

project(dream_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(dream-core src/main.cpp)

if (MSVC)
  target_compile_options(dream-core PRIVATE /W4 /EHsc)
else()
  target_compile_options(dream-core PRIVATE -Wall -Wextra -Wpedantic)
endif()
