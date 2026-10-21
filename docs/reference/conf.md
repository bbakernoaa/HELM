---
type: reference
category: reference
tags: [helm, conf]
---

# CONF: CONF API reference

[Library overview](../libraries/conf.md) · [Tutorial](../tutorials/conf.md) ·
[Error-handling how-to](../how-to/conf.md) · [All libraries](../README.md)

The C++ umbrella header is `<conf/conf.hpp>`. Core declarations are in
[`config.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/include/conf/config.hpp),
[`value.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/include/conf/value.hpp),
and [`error.hpp`](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/include/conf/error.hpp).
CONF parses YAML through yaml-cpp and exposes a typed C++ interface plus C and
Fortran bindings.

## Loading and ownership

Create a `Config` with `Config::from_file(path)` or
`Config::from_string(yaml_text)`. `Config` owns one parsed YAML tree, is
move-only, and releases the tree at destruction. Keep it alive while using any
`Value` returned by `root()` or `at()`; those values are lightweight views and
do not extend the configuration lifetime.

```cpp
#include <conf/conf.hpp>

auto config = conf::Config::from_file("model.yaml");
const auto nx = config.get_int("grid.nx");
const auto title = config.get_or<std::string>("metadata.title", "unnamed");
```

Paths accepted by `Config` scalar and structural accessors are dotted map paths
such as `grid.nx`. Use `root()` and `Value` child access when traversing
sequences or when constructing dynamic paths would be inconvenient.

## Config accessors

| API | Contract |
| --- | --- |
| `has(path)` | True when the path resolves to a defined node |
| `is_map(path)`, `is_sequence(path)` | Check node structure without throwing |
| `size(path)` | Child count for map/sequence nodes; zero for unresolved/scalar nodes |
| `get_int/double/bool/string(path)` | Required typed scalar; throws for missing or non-convertible values |
| `try_int/double/bool/string(path)` | Returns `std::optional`; empty for missing path or conversion failure |
| `get_or<T>(path, fallback)` | Returns fallback on any access/conversion error; supports `int`, `double`, `bool`, `std::string` |
| `get_int_list`, `get_double_list`, `get_string_list` | Convert a sequence to a typed vector |
| `root()`, `at(path)` | Return non-owning `Value` views |

The `try_*` and `get_or` forms intentionally collapse missing keys and wrong
types. Use the throwing `get_*` methods when those cases need different
diagnostics. `get_or` catches every failure, so it is a fallback mechanism, not
a schema validator.

## Value traversal and conversion

`Value::kind()` reports `Undefined`, `Null`, `Scalar`, `Sequence`, or `Map`.
Use `is_defined()` or its explicit boolean conversion to test whether a child
exists. Map and sequence navigation is available through `value["name"]` and
`value[index]`; missing keys and out-of-range indices return an undefined view.
`keys()` lists map keys, while `size()` returns a map or sequence's child count.

Scalar conversion methods are `as_int()`, `as_double()`, `as_bool()`, and
`as_string()`. Their `try_*` counterparts return optionals, and `int_or`,
`double_or`, `bool_or`, and `string_or` provide non-throwing fallbacks. For
sequence conversion, use `as_double_list()` or `as_string_list()`; for the
integer list, use `Config::get_int_list(path)`.

## Errors and boundary handling

The C++ API throws `conf::Conf_Error`, derived from `std::runtime_error`. Its
`code()` is a stable `Error_Code` value:

| Code | Meaning |
| --- | --- |
| `Invalid_Arg` | Invalid caller argument |
| `File_Not_Found` | File could not be opened |
| `Parse_Error` | YAML syntax could not be parsed |
| `Key_Not_Found` | Required path did not resolve |
| `Type_Mismatch` | Existing node could not convert to requested type |
| `Bad_Handle` | Invalid or released handle at a C boundary |
| `Buffer_Too_Small` | Caller-provided string buffer cannot hold the result |
| `Unknown` | Unexpected or uncategorized failure |

Catch `Conf_Error` at the configuration boundary, add the file or field name to
the diagnostic, and decide whether startup can continue. Do not keep a
`Value::from_raw()` view beyond the externally managed YAML node's lifetime.

## C and Fortran interfaces

The C interface uses opaque configuration/value handles and status codes so
errors can cross a language boundary without C++ exceptions. Release handles
with the matching API call and copy string data out before releasing a result
handle. The optional Fortran target mirrors the C error values; those numeric
values are append-only and must not be renumbered.

## Build

CONF requires yaml-cpp 0.8 and exports `HELM::CONF`. CMake options include
`CONF_USE_SYSTEM_YAMLCPP` (select a system package), `CONF_BUILD_FORTRAN`
(build `HELM::CONF_Fortran`), and `CONF_BUILD_TESTING` (enable GTest and
RapidCheck tests). See the
[CMake definition](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/CMakeLists.txt).
