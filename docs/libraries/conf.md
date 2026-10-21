---
type: reference
category: reference
tags: [helm, conf, navigation]
---

# CONF — Configuration Object & Notation Framework

CONF parses YAML into an owning `conf::Config` and supplies typed access
through dotted paths or `conf::Value` views. Use it to separate parsing and
conversion from application policy.

Create configurations with `Config::from_file` or `Config::from_string`.
Required values can be read using `get_int`, `get_double`, `get_bool`, or
`get_string`. Dotted paths navigate nested maps. Sequence helpers retrieve
lists; `at` and `root` return lightweight views for structured values.

The `try_*` methods return empty optionals for missing keys and conversion
failures. `get_or` returns its fallback for either case. Use those only when
a missing and malformed value should receive the same treatment. Otherwise,
use the throwing accessors and handle `conf::Conf_Error`.

Config is move-only and owns its parse tree; keep it alive while using Value
views. CONF cannot tell whether a converted value is scientifically valid:
the caller must check constraints such as positive timesteps.

Choose accessors according to the error policy the application needs:

| Input role | Access pattern | Behavior |
| --- | --- | --- |
| Required control | `get_*` | Report missing or unconvertible values |
| Optional value | `try_*` | Treat missing and unconvertible values as absent |
| Optional tuning with one fallback | `get_or<T>` | Use fallback for missing and conversion failures |

If absence and a misspelled or malformed value require different messages,
check `has(path)` before using the throwing accessor.

Include `<conf/conf.hpp>` and link `HELM::CONF`. yaml-cpp 0.8 is required;
CMake can fetch it or use a system install via `CONF_USE_SYSTEM_YAMLCPP`.
`CONF_BUILD_FORTRAN` enables `conf_mod`; `CONF_BUILD_TESTING` enables tests.

Follow the [configuration tutorial](../tutorials/conf.md), use
[the validation recipe](../how-to/conf.md), check [signatures and errors](../reference/conf.md),
and read [parsing versus policy](../explanation/conf.md).
