# Troubleshooting

Start with the preflight inventory and the recording's logbook. Use the
same processing configuration when validating or diagnosing a failed run.
[Batch runs, caching, and logs](running.md) explains log levels and reruns.

## Validate the inputs and environment

```bash
mrsiprep-docker /path/to/bids /path/to/derivatives participant \
  --participant-label S001 --session-label V1 \
  --metabolites CrPCr,GluGln,GPCPCh,NAANAAG,Ins \
  --ref-met CrPCr \
  --validate-only
```

Replace `--validate-only` with `--check-external-libs` to check the binaries
required for that configuration. Input validation and binary availability
are separate checks.

## Match a symptom to a next step

| Symptom | Likely cause / next step |
|---|---|
| Required MRSinMRS metadata not found | Supply `derivatives/mrsi-orig/mrsinmrs.json` or select `--mrsinmrs-file /path/to/metadata.json`. Wrapper paths refer to the host; plain Docker paths must be mounted. An old BIDS-root file must be moved or selected explicitly. |
| Missing T1w or metabolite maps | Check subject/session selection, filename entities, and the [input directory layout](inputs.md). Disambiguate multiple anatomicals with `--t1` or a BIDS filter. |
| Missing quality maps | Default validation requires shared SNR/linewidth and per-metabolite CRLB. Supply them, or set `--quality-metrics` to the metrics your quantification actually provides. Present maps are still thresholded. |
| Shape/affine mismatch or implausible alignment | Compare NIfTI geometry across signal and auxiliary maps. Correct exports/resampling upstream; consider the [orientation correction](usage_normalization.md#mrsi-orientation-correction) only after inspecting the problem. |
| `mri_synthseg` exits with `-9`, or `std::bad_alloc` | Check RAM allocated to Docker and concurrent process load. Allocate at least about 8 GB per concurrent recording, reduce `--nproc`, and consult [hardware requirements](installation.md#minimum-hardware-requirements). |
| CAT12 `p1`/`p2`/`p3` missing | `--tissue-backend existing` needs all three maps. `brain-csf` registration also needs CSF input when the default backend is not generating it. See [tissue settings](processing.md). |
| FreeSurfer licence error | Chimera/`recon-all` needs a valid licence. Pass `--fs-license-file` through the wrapper, or bind-mount it and set `FS_LICENSE` with plain Docker. |
| A long run appears silent | Try `--verbose 2` for stage details, or `3` for external-tool output. Inspect the logbook before assuming the process is stuck. |
| A rerun finishes almost immediately | It may be using cached outputs. Check the logs/runtime information and [recomputation controls](running.md#caching-and-reruns). |
| `--reports-only` says a derivative is missing | Report regeneration requires completed upstream derivatives. Restore them or perform a normal run with the intended processing settings. |
| T1w metabolite files are absent | Full T1w maps are opt-in; use `--output-mrsi-t1w` or request `T1w` in output spaces. The report's own T1w overlay does not imply those files were exported. |
| Reports show poor coverage, excessive repair, or leakage | Review raw signal and both registration overlays, then confirm units, reference metabolite, tissue maps, and masks. Treat these as scientific QC findings even if the run completed. |

## Find the detailed error

The combined run log is:

```text
<output_dir>/mrsiprep/logs/mrsiprep_<timestamp>.log
```

For one recording, inspect:

```text
<output_dir>/mrsiprep/sub-*/[ses-*/]/logs/sub-*[_ses-*]_desc-mrsiprep_log.txt
```

The recording logbook includes the full traceback regardless of console
verbosity. Rerun with `--verbose 3` if you also need the traceback and raw
external-tool output on the console.

By default, processing continues after a recording fails. A mixed batch
can exit successfully when some recordings succeeded, so inspect the final
success/failure summary and per-recording logs. Pass `--stop-on-first-crash`
when debugging a single failing example.

## Report an issue

Use the [issue tracker](https://github.com/MRSI-Psychosis-UP/MRSIPrep/issues)
and include the software version/container identifier, exact command,
failing subject/session, traceback, and relevant resolved configuration.
An anonymized report panel or description of the unexpected alignment can
help explain a processing problem. The [provenance JSON](data_reference.md#qc-tables-and-provenance)
records the run settings and tool paths.
