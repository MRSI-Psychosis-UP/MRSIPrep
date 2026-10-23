# Limitations and scope

MRSIPrep is a BIDS App for whole-brain quantified MRSI derivatives, not a
general-purpose neuroimaging pipeline. In particular:

- It has no fieldmap/BOLD/functional-MRI handling: those are out of scope
  entirely, since the inputs are already-quantified MRSI metabolite maps
  rather than raw k-space or functional time series.
- Registration can use ANTs (default, rigid+affine+SyN, generally most
  accurate) or FSL via `--registration-backend fsl` (FLIRT+FNIRT deformable
  by default; pass `--no-fsl-deformable` for FLIRT-only, faster but less
  accurate); there is no TemplateFlow catalog, and normalization targets are
  limited to MNI152 (`MNI152NLin2009cAsym`) plus native T1w/MRSI space, see
  [MNI Normalization Usage](usage_normalization.md).
- `--longitudinal` builds one ANTs subject-template across sessions
  (requires `--registration-backend ants`), see
  [Longitudinal (Subject-Template) Normalization](usage_longitudinal.md); it
  does not otherwise change per-session processing, and assumes reasonably
  stable anatomy across a subject's sessions.
- Chimera parcellation requires FreeSurfer and a valid `FS_LICENSE`; the
  default `--parcellation-mode synthseg` does not.
