---
type: explanation
category: explanation
tags: [helm, conf]
---

# CONF: Why parsing and validation are separate

[Library overview](../libraries/conf.md) · [All libraries](../README.md)

CONF answers a limited question: can this YAML document be parsed, and can a
particular value be converted to the requested C++ type? It deliberately does
not decide whether that value is valid for a model.

For example, CONF can convert `-60` to an integer timestep. The application
must decide that a timestep must be positive. Similarly, a parsed path may be
syntactically valid while the file does not exist. Keeping domain checks near
the code that understands the domain makes errors specific and testable.

| Layer | Question | Example outcome |
| --- | --- | --- |
| YAML parser | Is the document valid YAML? | Reject an unterminated sequence |
| Typed accessor | Can this node be read as an integer? | Reject `"hourly"` as a timestep |
| Application validation | Is the integer allowed by this model? | Reject `-60` as non-positive |
| Resource initialization | Can the configured input actually be opened? | Report a missing dataset path |

Keeping these checks separate avoids reporting a scientifically invalid value
as a YAML syntax error or hiding a file-system failure behind conversion code.

## Error policy is part of the API

Throwing accessors make required input failures visible. Optional accessors
collapse absent and unconvertible values into an empty optional. Defaulted
accessors collapse both cases into a fallback. These are intentionally different
policies; choose one based on what the application should do.

A default is convenient for optional tuning values, but dangerous for required
controls when it could silently mask a typo. For critical parameters, report
the missing key or type error and stop initialization.

## Ownership keeps parsing local

Each Config owns its own parsed document rather than relying on a global tree.
This avoids hidden shared state when different components read separate files.
Value provides convenient navigation without copying every node; that convenience
means it must not outlive the Config that owns the data.

CONF can be used by DAGR to read pipeline YAML, but graph invariants remain
DAGR's responsibility.
