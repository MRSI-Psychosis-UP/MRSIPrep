# About MRSIPrep

MRSIPrep preprocesses already-quantified whole-brain MRSI maps for voxelwise,
regional, and metabolic-similarity analyses. It is derived from
`MRSI-Metabolic-Connectome` and distributed under the CHUV academic
non-commercial research license.

## What it uses

Every dependency below is pinned to a fixed version inside the
distributed Docker image (`mrsiprep`'s own version and each external
tool's resolved binary path are recorded in the per-recording provenance
output):

- **[Nipype](https://nipype.readthedocs.io/)** (v1.11.0) as the workflow engine: each
  subject/session is a cached, per-step Nipype workflow, so a rerun of an
  already-processed recording skips finished steps instead of recomputing
  them.
- **[ANTs](http://stnava.github.io/ANTs/)** (v2.6.5) for MRSI↔T1w and T1w↔MNI registration.
- **[FreeSurfer](https://surfer.nmr.mgh.harvard.edu/)** (v8.2.0; `mri_synthseg`, `recon-all`, `mri_vol2vol`) for brain
  extraction, cortical/subcortical parcellation, and surface reconstruction.
- **[FSL](https://fsl.fmrib.ox.ac.uk/fsl/fslwiki) FAST** (v6.0.7.22) for tissue-class probability segmentation.
- **[PETPVC](https://github.com/UCL/PETPVC)** for partial-volume correction of MRSI maps.
- **[Chimera](https://github.com/connectomicslab/chimera)** (v0.3.1) for multi-atlas cortical/subcortical parcellation
  fusion.
- **[TemplateFlow](https://www.templateflow.org/)** for the
  MNI152NLin2009cAsym reference template MRSIPrep normalizes into
  (pre-fetched into the container, so runs stay offline).


## Design Principles

MRSIPrep was designed according to four main principles: reproducibility,
modularity, transparency, and analysis agnosticism.

### Reproducibility

The framework is distributed as open-source software and can be executed in
containerized environments to minimize differences across computing
platforms.

### Modularity

Each processing stage is implemented as an independent module, allowing
users to enable, disable, or replace specific steps according to their
acquisition protocol and scientific question.

### Transparency

MRSIPrep generates automated quality-control reports summarizing spatial
registration, metabolite coverage, voxel-level quality metrics, tissue
composition, and atlas projection.

### Analysis Agnosticism

MRSIPrep does not impose a specific downstream analysis. Instead, it
generates standardized derivatives that can be used for voxelwise analyses,
regional analyses, metabolic connectomics, gradient mapping, or
machine-learning workflows.


## License

MRSIPrep is distributed under the CHUV academic non-commercial research
license; see [LICENSE](https://github.com/MRSI-Psychosis-UP/mrsiprep/blob/main/LICENSE) for the full text.


## Acknowledgments

Substantial implementation logic is cropped and refactored by Federico
Lucchetti and Edgar Céléreau from `MRSI-Metabolic-Connectome`. MRSIPrep
builds on the work of the ANTs, FreeSurfer, FSL, PETPVC, Chimera, and
TemplateFlow projects.


## Publications

Code derived from this pipeline has been used in the following peer-reviewed
publications:

- Lucchetti, F., Céléreau, E., Steullet, P., Alemán-Gómez, Y., Hagmann, P.,
  Klauser, A., & Klauser, P. (2025). Constructing the human brain metabolic
  connectome with MR spectroscopic imaging reveals cerebral biochemical
  organization. *Nature Communications*, 16.
  [doi:10.1038/s41467-025-66124-w](https://doi.org/10.1038/s41467-025-66124-w)
- Céléreau, E., Lucchetti, F., Alemán-Gómez, Y., Dwir, D., Cleusix, M.,
  Ledoux, J.-B., Jenni, R., Conchon, C., Bach Cuadra, M., Schilliger, Z.,
  Solida, A., Armando, M., Plessen, K. J., Hagmann, P., Conus, P., Klauser,
  A., & Klauser, P. (2026). High-resolution whole-brain magnetic resonance
  spectroscopic imaging in youth at risk for psychosis. *Imaging
  Neuroscience*, 4.
  [doi:10.1162/imag.a.1276](https://doi.org/10.1162/imag.a.1276)
