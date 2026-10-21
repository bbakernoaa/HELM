---
type: howto
category: how_to
tags: [helm, mkdocs, diataxis, documentation]
---

# Build and maintain the documentation

## Preview the MkDocs site

From the repository root, create a Python environment and install the pinned
documentation dependencies:

```bash
python3 -m venv .venv-docs
.venv-docs/bin/python -m pip install -r docs/requirements.txt
.venv-docs/bin/python -m mkdocs serve
```

Open the local URL printed by MkDocs. Edit Markdown in `docs/` and navigation in
`mkdocs.yml`. MkDocs rebuilds the preview after changes.

## Build the static site

```bash
.venv-docs/bin/python -m mkdocs build --strict
```

The generated site is written to `site/`. Strict mode fails on warnings. Building
does not publish the site. Repository source links point to GitHub because code
outside `docs/` is not included in the MkDocs output.

## Use Spec Kit Diátaxis

This documentation follows the metadata and quadrant conventions in
[spec-kit-diataxis-docs](https://github.com/bbakernoaa/spec-kit-diataxis-docs),
reviewed at commit `d5195cf01b79fa1f6c9867e6402e335e012e5eef`.
The project configuration is stored at
`.specify/extensions/spec-kit-diataxis-docs/diataxis-config.yml`.
Applying the writing conventions does not register the extension with Spec Kit.

In a checkout where Spec Kit is installed and initialized, add the extension:

```bash
specify extension add spec-kit-diataxis-docs --from https://github.com/bbakernoaa/spec-kit-diataxis-docs
```

Then use these commands in a supported coding agent:

```text
/speckit.diataxis.update
/speckit.diataxis.review
```

Update an existing guide when it addresses the same reader task. Each library
overview links to separate tutorial, how-to, reference, and explanation pages.
Separate library guides keep distinct interfaces and operational concepts apart.
Link existing library documentation and runnable examples rather than duplicating
them. Source API comments remain the authority for full signatures.

Every managed Markdown page starts with YAML metadata:

```yaml
---
type: tutorial
category: tutorials
tags: [helm, tick]
---
```

Use `howto`/`how_to`, `reference`/`reference`, and
`explanation`/`explanation` for the other core quadrants. Add each new guide to
MkDocs navigation and its library overview. Document example prerequisites and
observable results, then run examples in the HELM development environment.

CF metadata dictionaries are needed when documenting actual dataset-variable
contracts. Do not invent standard names or units for illustrative arrays.
