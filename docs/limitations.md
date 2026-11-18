# Limitations and scope

MRSIPrep starts after spectral reconstruction and quantification. Its inputs
are whole-brain NIfTI metabolite and quality maps plus anatomy. It does not
fit spectra, reconstruct raw k-space, or handle BOLD/functional-MRI data and
fieldmaps. Import helpers arrange supported NIfTI derivatives; they do not
convert native quantification-tool output into metabolite maps.

## Spatial normalization

Supported output spaces are native MRSI, T1w, and MNI152NLin2009cAsym.
There is no general TemplateFlow target catalog exposed through the CLI.
Finer output spacing does not increase acquisition resolution.

ANTs and FSL are supported toolchains, with different transform stages.
The [registration benchmark](registration_benchmark.md) evaluates leakage
and overlays in two subjects, while the [VBA benchmark](vba_benchmark.md)
evaluates focal-signal recovery in synthetic data. Their rankings are
metric- and configuration-specific; they do not establish universal
anatomical accuracy for every acquisition.

`--longitudinal` builds an ANTs subject template across sessions. It requires
the ANTs backend, assumes reasonably stable anatomy, and otherwise retains
ordinary per-session processing. Single-session subjects use direct
normalization. See [Longitudinal processing](usage_longitudinal.md).

## Quantification and regional analyses

Input signal units, SNR definitions, and spectral quality originate upstream.
MRSIPrep does not automatically harmonize concentration calibration or
linewidth units across scanners or quantification methods. The input layout
uses shared SNR/linewidth maps, alongside metabolite-specific CRLB.

Regional tables and Monte Carlo profiles use different masking and weighting
procedures; see [Processing methods](methods.md). Metabolic connectivity
represents profile similarity or distance, not anatomical connections or
temporal correlations. Cross-site regional correlations support relative
pattern replication, not agreement of absolute concentrations.

The current CLI does not expose a fixed seed for Monte Carlo profile
estimation. New computations can differ numerically. Preserve exported
profiles when exact numerical reuse matters.

## Dependencies and experimental features

The supported pipeline runs in Docker. Chimera requires `recon-all` and a
valid FreeSurfer licence; the default SynthSeg mode does not. Anatomical
segmentation still runs when tissue probability estimation/PVC is disabled.

Non-proton acquisitions and T1 saturation correction have narrower validation
than the default workflow. Read [Experimental features](future_development.md)
for prerequisites and unresolved assumptions. A valid configuration and a
completed report still require [recording-level QC review](outputs.md).
