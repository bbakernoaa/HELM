---
type: howto
category: how_to
tags: [helm, conf]
---

# CONF: Choose required, optional, and defaulted configuration reads

[Library overview](../libraries/conf.md) · [All libraries](../README.md)

CONF offers different access patterns because a required value, an optional
value and a defaulted value have different failure policies.

## Required value

Use a throwing accessor for a required setting and validate its application
meaning after conversion:

~~~cpp
auto config = conf::Config::from_file("model.yaml");
const int seconds = config.get_int("model.timestep");
if (seconds <= 0) {
    throw std::invalid_argument("model.timestep must be positive");
}
~~~

Missing keys and values that cannot convert produce `conf::Conf_Error`.
Catch it at the configuration boundary and report the path and source file.

## Optional value

Use a `try_*` accessor when either a missing key or a conversion failure means
“not provided”:

~~~cpp
if (const auto retries = config.try_int("model.retries")) {
    configure_retries(*retries);
} else {
    use_retry_policy_from_environment();
}
~~~

If missing and malformed input need different treatment, first test
`config.has(path)`, then use the throwing accessor when the key exists.

## Defaulted value

Use `get_or<T>(path, fallback)` only when one fallback is appropriate for
both failure cases:

~~~cpp
const int retries = config.get_or<int>("model.retries", 3);
~~~

The fallback path is intentionally non-throwing. It can conceal a typo or bad
type, so do not use it for required safety-critical controls.

## Navigate structured YAML

Use `at` or `root` for node traversal and keep the owning Config alive:

~~~cpp
const auto output = config.at("output");
if (output) {
    const auto path = output["path"].try_string();
    if (path) open_output(*path);
}
~~~

A Value is a view tied to the Config lifetime. It does not extend the lifetime
of its parsed document. For list-valued scalars, use the typed list helpers on
Config or the sequence accessors on Value.

## Build with system yaml-cpp

By default, CONF can fetch yaml-cpp. To use a preinstalled package:

~~~bash
cmake -S libs/conf -B libs/conf/build -DCONF_USE_SYSTEM_YAMLCPP=ON
~~~

Supply its prefix through `CMAKE_PREFIX_PATH` if CMake cannot locate it.
The accessors and ownership rules are defined in
[config.hpp](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/include/conf/config.hpp)
and [value.hpp](https://github.com/NOAA-EMC/HELM/blob/develop/libs/conf/include/conf/value.hpp).
