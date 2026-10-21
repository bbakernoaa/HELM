---
type: tutorial
category: tutorials
tags: [helm, conf]
---

# CONF: load and validate a model configuration

[Library overview](../libraries/conf.md) · [All libraries](../README.md)

You will read a YAML file, extract required and optional settings, inspect a
sequence, and handle invalid configuration. The final program prints a short
model configuration summary and fails clearly when a required value is wrong.

Allow about 30 minutes. You need C++20, CMake 3.21+, and yaml-cpp 0.8 or network
access for CMake to fetch it. Complete the
[development setup](../README.md#prepare-a-development-environment) first.
The exercise disables the optional Fortran interface.

## 1. Create the tutorial project

Create a directory outside the HELM checkout:

```bash
mkdir -p /tmp/helm-conf-tutorial
cd /tmp/helm-conf-tutorial
```

Save this as `CMakeLists.txt`, replacing the absolute checkout path:

```cmake
cmake_minimum_required(VERSION 3.21)
project(conf_tutorial LANGUAGES CXX)
set(CONF_BUILD_FORTRAN OFF CACHE BOOL "" FORCE)
add_subdirectory(/path/to/HELM/libs/conf conf-build)
add_executable(conf_tutorial main.cpp)
target_link_libraries(conf_tutorial PRIVATE HELM::CONF)
```

## 2. Read one value from an in-memory document

Save this complete `main.cpp`:

```cpp
#include <conf/conf.hpp>
#include <iostream>

int main() {
    auto config = conf::Config::from_string("model:\n  timestep: 60\n");
    std::cout << config.get_int("model.timestep") << '\n';
}
```

Configure, build, and run from the tutorial directory:

```bash
cmake -S . -B build
cmake --build build --parallel
./build/conf_tutorial
```

**Checkpoint:** the output is `60`. The dot in `model.timestep` navigates
from the outer mapping to the nested scalar.

## 3. Move the settings into a YAML file

Save `model.yaml` in the tutorial directory:

```yaml
model:
  name: atmosphere
  timestep: 60
  enabled: true
  levels: [1000, 850, 500]
output:
  path: tutorial-output.nc
```

Replace `main.cpp` with this complete program:

```cpp
#include <conf/conf.hpp>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
    const std::string path = argc > 1 ? argv[1] : "model.yaml";
    try {
        auto config = conf::Config::from_file(path);
        const auto name = config.get_string("model.name");
        const auto timestep = config.get_int("model.timestep");
        if (timestep <= 0) {
            throw std::invalid_argument("model.timestep must be positive");
        }
        const auto retries = config.get_or<int>("model.retries", 3);
        const auto levels = config.get_int_list("model.levels");
        std::cout << "model=" << name << '\n'
                  << "timestep=" << timestep << '\n'
                  << "enabled=" << config.get_bool("model.enabled") << '\n'
                  << "retries=" << retries << '\n'
                  << "levels=" << levels.size() << '\n';
        const auto output = config.at("output");
        std::cout << "output=" << output["path"].as_string() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Configuration failed: " << error.what() << '\n';
        return 1;
    }
}
```

Rebuild and run:

```bash
cmake --build build --parallel
./build/conf_tutorial model.yaml
```

**Checkpoint:**

```text
model=atmosphere
timestep=60
enabled=1
retries=3
levels=3
output=tutorial-output.nc
```

The file has no retries key, so the program uses the fallback. The `output`
node is a view into the configuration; its owner remains alive while it is used.

## 4. Add an optional value

Add `retries: 5` under the `model` mapping, alongside timestep.
Run the executable again without rebuilding.

**Checkpoint:** retries changes from 3 to 5. Changing a data file does not require
recompiling the application.

Now change that value to `retries: many`. Run again: retries returns to 3.
The fallback applies to conversion failures as well as missing keys. This is
appropriate only when either condition should select the same default.

## 5. Distinguish conversion and application validation

Change timestep to `sixty`. Run:

```bash
./build/conf_tutorial model.yaml
echo $?
```

**Checkpoint:** the program reports a configuration error and returns 1.
The exact error wording comes from CONF.

Change timestep to `-60` and repeat. Integer conversion succeeds, but our
application rejects the negative value with `model.timestep must be positive`.
Restore 60 before continuing.

Finally, pass a nonexistent filename. Confirm that the same error boundary reports
a file failure rather than continuing with an uninitialized configuration.

## 6. Handle an optional value explicitly

After reading timestep, insert:

```cpp
const auto optional_retries = config.try_int("model.retries");
if (!optional_retries) {
    std::cout << "No usable retries value; applying policy default\n";
}
```

Keep retries set to `many`, rebuild, and run. You now observe the missing
conversion rather than hiding it inside the fallback call.

## If you get stuck

| Symptom | Check |
| --- | --- |
| yaml-cpp download fails | Install yaml-cpp 0.8 and configure with `-DCONF_USE_SYSTEM_YAMLCPP=ON` |
| File not found | Run from the directory containing model.yaml or pass its absolute path |
| Unexpected missing key | Check YAML indentation and dotted-path spelling |
| Fortran compiler requested | Set CONF_BUILD_FORTRAN OFF before add_subdirectory, as above |

## Practice

Add a required `output.frequency` integer and reject zero or negative values.
Add a sequence of two output variable names and retrieve it with
`get_string_list`. Predict the behavior of a missing key before running.

Continue with the [CONF reference](../reference/conf.md). To use configuration
for task dependencies, work through the [DAGR tutorial](dagr.md).
