# Contributing and building the docs

For development setup, coding conventions, tests, and pull requests, read
the repository's [contribution guide](https://github.com/MRSI-Psychosis-UP/MRSIPrep/blob/main/CONTRIBUTING.md).
[Architecture](architecture.md), [Extending MRSIPrep](extending.md), and
the [API reference](api.md) describe the pipeline's extension points.

## Build documentation locally

From the repository root, use a Python 3.12 environment matching
`.readthedocs.yaml`:

```bash
python -m pip install -r docs/requirements.txt
python -m sphinx -b html -j auto -W --keep-going docs docs/_build/html
```

Open `docs/_build/html/index.html` to inspect the result. The build imports
the local CLI and API definitions; it does not execute preprocessing or
require the neuroimaging binaries. The Python dependencies listed in
`docs/requirements.txt` are needed for API imports.

## Keep navigation and examples usable

Add new pages to the appropriate toctree in `docs/index.md`, or to an
existing guide's child toctree. Keep onboarding sequential, place advanced
recipes in the user guide, and keep algorithm explanations separate from
developer architecture. Experimental features should state their current
validation scope rather than imply a release commitment.

Build from a clean checkout before publishing so ignored local pages or
figures cannot hide missing files. Generated API stubs and HTML build
outputs are excluded from version control. Preserve published page paths
and useful anchors when moving content; update internal links and provide
a pointer from the original page when a topic moves.
