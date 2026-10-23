# Command-Line Arguments

```{argparse}
:module: mrsiprep.cli.parser
:func: build_parser
:prog: mrsiprep
```

By default, when a subject/session has more than one candidate raw T1w
acquisition, MRSIPrep picks one heuristically (preferring
`acq-memprage`/`mprage`/`mp2rage` and `run-01`). `--bids-filter-file` lets you
override that choice explicitly:

```json
{"t1w": {"acquisition": "memprage", "run": "01"}}
```

Only the `"t1w"` key is currently supported (any other top-level key is
rejected with an error rather than silently ignored). Filter values use
either MRSIPrep's short BIDS entity names (`acq`, `run`, `ses`, `sub`) or the
long PyBIDS-style names shown above (`acquisition`, `run`, `session`,
`subject`) interchangeably. A value of `null` requires the entity to be
absent from the filename.

See [MNI Normalization Usage](usage_normalization.md) for `--output-spaces`
and `--output-mrsi-t1w`, and
[Longitudinal (Subject-Template) Normalization](usage_longitudinal.md) for
`--longitudinal`.
