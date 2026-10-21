---
type: tutorial
category: tutorials
tags: [helm, amio]
---

# AMIO: write and inspect a temperature dataset

[Library overview](../libraries/amio.md) · [All libraries](../README.md)

You will configure a NetCDF-4 backend, write a small synthetic temperature field,
reuse the input buffer after staging, and inspect the completed file. This
exercise uses the public C API and checks the status of every lifecycle call.

Allow 45–60 minutes after dependencies are installed. You need CMake, a C/C++20
toolchain, a Fortran compiler for the current AMIO project, NetCDF-4, and AMIO's
CONF, HALO, LOGS, and mdspan dependencies. Use the
[development environment](../README.md#prepare-a-development-environment) and
[AMIO prerequisite guide](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/docs/site/getting-started/installation.md).
Install ncdump and Python's netCDF4 package for the inspection steps.

## 1. Build AMIO with installed sibling dependencies

From the HELM root, configure using the prefix where the sibling packages and
external dependencies are installed:

```bash
cmake -S libs/amio -B libs/amio/build -DCMAKE_PREFIX_PATH=/path/to/dependency-prefix
cmake --build libs/amio/build --parallel
cmake --install libs/amio/build --prefix /tmp/helm-amio-install
```

Replace the dependency prefix with your actual installation. If CMake reports
missing CONF, HALO, or LOGS, resolve that dependency before building. The AMIO
CMake project discovers installed packages; a sibling source directory alone
does not satisfy find_package.

**Checkpoint:** installation produces AMIO's headers, libraries, and CMake
package files under /tmp/helm-amio-install.

## 2. Create an isolated output directory

```bash
mkdir -p /tmp/helm-amio-tutorial
cd /tmp/helm-amio-tutorial
```

Save this as manifest.yaml. It follows the flat-key structure of the repository's
[NetCDF-4 manifest](https://github.com/NOAA-EMC/HELM/blob/develop/libs/amio/examples/manifests/netcdf4_manifest.yaml):

```yaml
backend: netcdf4
path: tutorial-temperature.nc
data_model: classic
staging_pool:
  buffer_count: 4
  buffer_capacity_bytes: 1048576
worker_pool:
  threads: 1
prefetch:
  depth: 1
  read_timeout_s: 60
staging_timeout_ms: 10000
```

The output path is relative to the process working directory. Keep the program
and inspection commands in this temporary directory to make that location
unambiguous. No scientific metadata standard name is implied by this toy array.

## 3. Write a complete C application

Save this as main.c:

```c
#include <amio/amio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void check(amio_status_t status, const char *operation) {
    if (status != AMIO_OK) {
        fprintf(stderr, "%s: %s\n", operation, amio_strerror(status));
        exit(EXIT_FAILURE);
    }
}

int main(void) {
    amio_core_handle core = NULL;
    amio_dataset_handle dataset = NULL;
    amio_io_handle io = NULL;
    float temperature[20];
    for (int i = 0; i < 20; ++i) temperature[i] = 270.0f + (float)i;

    check(amio_init("manifest.yaml", &core), "initialize");
    check(amio_open_dataset(core, "manifest.yaml", AMIO_MODE_WRITE, &dataset),
          "open dataset");
    amio_shape_t shape;
    memset(&shape, 0, sizeof(shape));
    shape.rank = 2;
    shape.extents[0] = 4;
    shape.extents[1] = 5;
    check(amio_write(dataset, "temperature", temperature,
                     AMIO_DTYPE_F32, &shape, &io), "enqueue write");

    /* The successful write call has copied input into AMIO staging. */
    for (int i = 0; i < 20; ++i) temperature[i] = -999.0f;

    check(amio_wait(io, 0), "wait for write");
    check(amio_flush(dataset, 0), "flush dataset");
    check(amio_close_dataset(dataset), "close dataset");
    check(amio_finalize(core), "finalize");
    puts("Wrote 20 temperature values.");
    return EXIT_SUCCESS;
}
```

The status helper exits immediately on failure to keep the learning example
small. A production application should also clean up resources acquired before
a failure. A successful enqueue does not by itself establish a successful
backend write; wait and flush check completion.

## 4. Link through AMIO's package

Save this CMakeLists.txt in the same directory:

```cmake
cmake_minimum_required(VERSION 3.21)
project(amio_tutorial LANGUAGES C CXX)
find_package(AMIO REQUIRED)
add_executable(amio_tutorial main.c)
target_link_libraries(amio_tutorial PRIVATE AMIO::amio_core)
set_property(TARGET amio_tutorial PROPERTY LINKER_LANGUAGE CXX)
```

Configure with both the AMIO installation and the original dependency prefix:

```bash
cmake -S . -B build -DCMAKE_PREFIX_PATH="/tmp/helm-amio-install;/path/to/dependency-prefix"
cmake --build build --parallel
./build/amio_tutorial
```

**Checkpoint:** the program prints Wrote 20 temperature values and creates
tutorial-temperature.nc. If a shared dependency cannot be loaded, use your
platform's configured runtime library environment for its installation prefix.

## 5. Inspect dimensions and values

Inspect the header and field:

```bash
ncdump -h tutorial-temperature.nc
ncdump -v temperature tutorial-temperature.nc
```

Look for a floating-point variable named temperature with two dimensions whose
product is 20. Dimension naming and displayed dimension order are backend
details; the contiguous sequence should contain values 270 through 289.

Check the payload independently:

```python
from netCDF4 import Dataset
import numpy as np

with Dataset("tutorial-temperature.nc") as dataset:
    values = np.asarray(dataset.variables["temperature"][:])
    assert values.size == 20
    np.testing.assert_array_equal(
        np.sort(values.reshape(-1)), np.arange(270, 290, dtype=np.float32)
    )
    assert not np.any(values == -999)
    print("Verified 20 original values; staging protected the input.")
```

Save this as verify.py and run python3 verify.py.
The -999 values were written only into the caller's buffer after staging.
Their absence from the file is the observable ownership checkpoint.

## 6. Change one input and repeat

Change the starting temperature from 270 to 280 in main.c. Update the independent
check to expect 280 through 299. Change the manifest output path to
tutorial-temperature-second.nc and update the inspection filename accordingly.
Rebuild the executable, run it, and verify the new file.

Next, make the manifest path passed to amio_init nonexistent. Confirm that the
program reports an initialization error instead of printing the success message.
Restore the valid path.

## If you get stuck

| Symptom | Check |
| --- | --- |
| AMIO package not found | Include the install prefix in CMAKE_PREFIX_PATH |
| Manifest not found | Run from /tmp/helm-amio-tutorial |
| NetCDF backend unavailable | Inspect AMIO configuration output for NetCDF discovery |
| File contains too few values | Shape extents must agree with the allocated input size |
| Success message absent | Read the first operation-specific status error |
| Python inspection import fails | Install netCDF4 and NumPy in your inspection environment |

## Practice

Increase the field to 30 values and use extents 5 and 6. Update allocation,
initialization, shape, and independent checks together. Keep the buffer small
enough for the configured staging capacity.

Continue to [AMIO's how-to guide](../how-to/amio.md) for backend selection and
the [reference](../reference/amio.md) for lifecycle and read-view contracts.
