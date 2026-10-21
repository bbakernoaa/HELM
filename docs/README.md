---
type: reference
category: reference
tags: [helm, navigation]
---

# HELM documentation

Choose a library below, then choose the kind of help you need. These pages follow
[Diátaxis](https://diataxis.fr/): tutorials teach through a guided exercise,
how-to guides solve a specific task, reference describes interfaces and options,
and explanation discusses design and tradeoffs.

| Library | Use it for |
| --- | --- |
| [AMIO](libraries/amio.md) | Asynchronous scientific input and output |
| [AXIS](libraries/axis.md) | Spatial interpolation and regridding |
| [BLEND](libraries/blend.md) | Element-wise weighted blending and step selection |
| [CONF](libraries/conf.md) | YAML configuration and typed value access |
| [DAGR](libraries/dagr.md) | Dependency graphs and asynchronous orchestration |
| [HALO](libraries/halo.md) | MPI communication and halo exchange |
| [LOGS](libraries/logs.md) | MPI-aware logging and operational status |
| [SPAN](libraries/span.md) | Non-owning array views and host/device coherency |
| [TICK](libraries/tick.md) | Calendars, durations, alarms, and coupling periods |

## Prepare a development environment

You need a complete HELM checkout, Docker, and Docker Compose. From the repository
root, build and enter the development environment:

```bash
docker compose up -d --build
docker compose exec helm-dev bash
cd /workspace/helm-project
```

Library build commands start at the repository root inside this container unless
the page says otherwise. Run each command in order. CMake configuration must
succeed before building. A successful CTest run reports that all selected tests
passed; use `--no-tests=error` to detect an empty selection.

For a native toolchain, consult each library's prerequisites and CMake dependency
discovery. The libraries have separate CMake projects; configure the relevant
`libs/<name>` directory. AMIO and DAGR also need sibling libraries as described on
their pages. Installed dependency prefixes can be supplied with
`-DCMAKE_PREFIX_PATH=/path/to/prefix`.

## Architectural background

Read the [project charter](architecture/project_charter.md) for HELM's tier model
and design goals. The library pages describe their individual responsibilities.
See also the [AMIO migration guide](MIGRATION-amio.md).

## Maintaining these pages

Keep each section focused on its reader's goal. A tutorial needs prerequisites,
ordered steps, and an observable result. A how-to needs a concrete task and a
procedure. Reference should link to the maintained source of interface details.
Explanation should describe why the design works and its limits.

Link to existing guides and runnable examples instead of duplicating them. When
changing an interface, check its page, example, build options, and relative links
together. These pages were prepared against `develop` commit
`a3e36e69e4d2c4426a21a11bde2d1cd2a8a70e0d`; commands require validation in the
project's development environment before being treated as tested recipes.
