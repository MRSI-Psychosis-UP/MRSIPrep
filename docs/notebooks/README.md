# Walkthrough notebook

After completing [First run](../usage_basic.md), use this notebook to explore
the stage functions and intermediate results. Read [Processing methods](../methods.md)
for the algorithm overview.

{download}`Download the walkthrough notebook <walkthrough_synthmrsi_sub01.ipynb>`

Save it in a checkout's `docs/notebooks/` directory for the commands below.
The documentation build provides the notebook as a download; it does not
execute the heavy processing stages.

## `walkthrough_synthmrsi_sub01.ipynb`

Walks through MRSIPrep's processing pipeline stage by stage for one subject, calling MRSIPrep's own stage functions directly (not a reimplementation): spike filtering, MRSI-to-T1w registration + resampling, partial-volume correction, regional profile extraction, atlas projection, metabolic connectivity, and HTML report generation all run live against real data from this subject, writing their output to a scratch directory. Anatomical segmentation (SynthSeg) and MNI-space resampling load this subject's already-computed derivatives instead, since those stages are either too heavy to re-run per-notebook-execution (SynthSeg) or depend on a separately-computed template transform (MNI resampling).

**Data:** the public SynthMRSI-Project validation dataset (CC0), [doi:10.5281/zenodo.21477047](https://doi.org/10.5281/zenodo.21477047). Download it and place/symlink it as `SynthMRSI-Project/` next to the notebook (or edit `DATASET_ROOT` in the first code cell).

**Acquisition metadata:** `derivatives/mrsi-orig/mrsinmrs.json` is required. To use
another location, set `MRSINMRS_FILE` in the first code cell. For an older archive
with the file in the dataset root, set it to `DATASET_ROOT / "mrsinmrs.json"`
or move the file into `derivatives/mrsi-orig/` before starting. When running in
Docker, use a path available inside the container.

**Network:** the first code cell's `templateflow` call downloads the MNI152 template once (a few MB) and caches it; needs internet access the first time it runs in a given environment (the Docker image already has it pre-cached).

**Viewing the generated HTML report (Stage 8):** the notebook prints the report's path inside its scratch directory, which it deletes at the end (Cleanup cell) — download the file (and copy out its sibling `reports/figures/`, if present) before that cell runs if you want to keep it, then open it locally. It will not render correctly via GitHub's online `.ipynb`/file viewer, which does not serve the report's sibling assets.

### Option A — Docker (recommended: every stage runs genuinely live)

MRSI-to-T1w registration's default backend (ANTs) and partial-volume correction (PETPVC) need those binaries on `PATH`; the `mrsiup/mrsiprep:cpu` Docker image already bundles them (and `mrsiprep` and `nilearn`; the launch command below adds Jupyter), so this is the only path where *every* stage runs live rather than falling back to a precomputed result.

```bash
docker run --rm -it \
  -p 8888:8888 \
  -v "$(pwd)/docs/notebooks:/notebooks" \
  -v "/path/to/your/SynthMRSI-Project:/notebooks/SynthMRSI-Project:ro" \
  -e PYTHONPATH=/opt/mrsiprep \
  --entrypoint /usr/bin/python3 \
  mrsiup/mrsiprep:cpu -c "
import subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'jupyter', 'ipykernel'], check=True)
# The image's default python3 kernel points at FSL's bundled Python, which
# lacks mrsiprep/nilearn -- re-register python3 to point at the Python that
# actually has them (/usr/bin/python3, the one mrsiprep's own CLI uses).
subprocess.run([sys.executable, '-m', 'ipykernel', 'install', '--user', '--name', 'python3', '--display-name', 'Python 3'], check=True)
subprocess.run([sys.executable, '-m', 'jupyter', 'lab', '--ip=0.0.0.0', '--port=8888',
                 '--no-browser', '--allow-root', '--ServerApp.token=', '--notebook-dir=/notebooks'])
"
```

Then open `http://localhost:8888/lab` and run `walkthrough_synthmrsi_sub01.ipynb`. The `pip install`/kernel-registration step runs once per container start (a few seconds, small packages only); nothing is written back into the image. Verified end-to-end: all live-executed stages (spike filtering, registration, PVC, regional profiles, atlas projection, connectivity, report generation) run via the real binaries, not the fallback paths, and figures render correctly.

`--ServerApp.token=` disables the login token for local convenience; drop it (and set a password instead) if exposing the port beyond `localhost`.

### Option B — Local Python install (faster to start, but two stages fall back)

```bash
cd docs/notebooks
ln -s /path/to/your/SynthMRSI-Project SynthMRSI-Project
pip install -e ../..  # installs mrsiprep and its Python dependencies from the repo root
jupyter notebook walkthrough_synthmrsi_sub01.ipynb
```

This gets `mrsiprep` and all its Python dependencies (`nibabel`, `nilearn`, `pandas`, etc.) via a normal `pip install`, but **not** ANTs, FSL, or PETPVC — none of those are pip-installable (FSL alone is a multi-gigabyte distribution). Without at least one of ANTs/FSL on `PATH`, the registration cell can't run live; without PETPVC, the PVC cell can't either. Both cells detect this and fall back gracefully to this subject's already-computed output, printing which happened — the notebook will not crash, but two of its four "live" stages won't actually be live unless you separately install ANTs or FSL and/or PETPVC yourself.

---

This subject was originally processed without `--parcellation-mode chimera`; the notebook's connectivity stage instead uses `--parcellation-mode atlas` (a pre-bundled MNI-space atlas, `chimera-LFMIHIFIS_scale3`), which needs no FreeSurfer `recon-all` — see Stage 7 for what distinguishes it from a full Chimera run.
