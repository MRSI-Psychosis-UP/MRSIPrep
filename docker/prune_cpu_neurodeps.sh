#!/usr/bin/env bash
set -euo pipefail

FSL_ROOT="${FSLDIR:-/opt/fsl}"
FS_ROOT="$(readlink -f "${FREESURFER_HOME:-/opt/freesurfer}")"
ANTS_ROOT="${ANTSPATH:-/opt/ants/bin}"
ANTS_ROOT="$(dirname "${ANTS_ROOT}")"

if [[ ! -x "${FSL_ROOT}/bin/fast" ]]; then
  printf 'FAST was not found at %s/bin/fast\n' "${FSL_ROOT}" >&2
  exit 1
fi
if [[ ! -x "${FS_ROOT}/bin/recon-all" || ! -x "${FS_ROOT}/bin/mri_synthseg" ]]; then
  printf 'A full FreeSurfer installation was not found at %s\n' "${FS_ROOT}" >&2
  exit 1
fi

printf 'Installed sizes before pruning:\n'
du -sh "${FSL_ROOT}" "${FS_ROOT}" "${ANTS_ROOT}" 2>/dev/null || true

# FAST is the only FSL program called by MRSIPrep. Build a fresh FSL tree with
# the executable and every FSL/conda library resolved by the dynamic loader.
fsl_runtime="$(mktemp -d /opt/fsl-runtime.XXXXXX)"
mkdir -p "${fsl_runtime}/bin" "${fsl_runtime}/lib"
cp -a "${FSL_ROOT}/bin/fast" "${fsl_runtime}/bin/fast"

while IFS= read -r library; do
  [[ -n "${library}" ]] || continue
  cp -L "${library}" "${fsl_runtime}/lib/$(basename "${library}")"
done < <(ldd "${FSL_ROOT}/bin/fast" | awk -v root="${FSL_ROOT}/" '$3 ~ "^" root {print $3}')

for license_file in LICENCE.FSL LICENSE COPYING; do
  if [[ -f "${FSL_ROOT}/${license_file}" ]]; then
    cp -a "${FSL_ROOT}/${license_file}" "${fsl_runtime}/${license_file}"
  fi
done

rm -rf "${FSL_ROOT}"
mv "${fsl_runtime}" "${FSL_ROOT}"

# MRSIPrep only ever shells out to antsRegistrationSyN.sh and
# antsApplyTransforms (interfaces/ants.py), and only as a fallback when
# antspyx's Python bindings are unavailable; antspyx itself ships its own
# bundled libs and has no dependency on /opt/ants. antsRegistrationSyN.sh is
# a shell script that itself calls antsRegistration, antsApplyTransforms,
# and PrintHeader internally (confirmed by grepping the script for every
# ANTs bin/ name) - PrintHeader was missed in an earlier pass of this prune
# and broke every registration that goes through the CLI fallback path with
# "PrintHeader: command not found". N4BiasFieldCorrection is kept too even
# though nothing currently shells out to it, since utils/provenance.py's
# required_external_tools() (and this same check_neurodeps.sh) treat it as
# a required tool. Plus any resolved /opt/ants/lib dependency, mirroring
# the FSL pattern above.
if [[ -d "${ANTS_ROOT}" ]]; then
  ants_runtime="$(mktemp -d /opt/ants-runtime.XXXXXX)"
  mkdir -p "${ants_runtime}/bin"
  cp -a "${ANTS_ROOT}/bin/antsRegistrationSyN.sh" "${ants_runtime}/bin/"
  cp -a "${ANTS_ROOT}/bin/antsRegistration" "${ants_runtime}/bin/"
  cp -a "${ANTS_ROOT}/bin/antsApplyTransforms" "${ants_runtime}/bin/"
  cp -a "${ANTS_ROOT}/bin/N4BiasFieldCorrection" "${ants_runtime}/bin/"
  cp -a "${ANTS_ROOT}/bin/PrintHeader" "${ants_runtime}/bin/"

  while IFS= read -r library; do
    [[ -n "${library}" ]] || continue
    mkdir -p "${ants_runtime}/lib"
    cp -L "${library}" "${ants_runtime}/lib/$(basename "${library}")"
  done < <(ldd "${ANTS_ROOT}/bin/antsRegistration" "${ANTS_ROOT}/bin/antsApplyTransforms" "${ANTS_ROOT}/bin/N4BiasFieldCorrection" "${ANTS_ROOT}/bin/PrintHeader" | awk -v root="${ANTS_ROOT}/" '$3 ~ "^" root {print $3}')

  rm -rf "${ANTS_ROOT}"
  mv "${ants_runtime}" "${ANTS_ROOT}"
fi

# Keep the complete recon-all executable/library/atlas runtime. These are the
# same high-confidence exclusions used by established neuroimaging images and
# do not participate in MRSIPrep's recon-all, mri_vol2vol, or SynthSeg paths.
rm -rf \
  "${FS_ROOT}/diffusion" \
  "${FS_ROOT}/docs" \
  "${FS_ROOT}/fsfast" \
  "${FS_ROOT}/matlab" \
  "${FS_ROOT}/trctrain" \
  "${FS_ROOT}/lib/cuda" \
  "${FS_ROOT}/lib/qt" \
  "${FS_ROOT}/mni/share/man"

for subject_template in \
  fsaverage3 fsaverage4 fsaverage5 fsaverage6 fsaverage_sym \
  cvs_avg35 cvs_avg35_inMNI152 lh.EC_average rh.EC_average V1_average; do
  rm -rf "${FS_ROOT}/subjects/${subject_template}"
done
rm -f "${FS_ROOT}/subjects"/sample-*.mgz

# MRSIPrep invokes `mri_synthseg --parc [--fast|--robust]` and `recon-all -all`
# with no extra optional-module flags, but FreeSurfer 8's V8 default expert
# options (etc/global-expert-options.v8.txt) make `recon-all -all` pull in
# SynthStrip, SynthMorph, and the vsinus/mca-dura fixer models on every run,
# so those must be kept. Everything below still backs tools or recon-all
# add-on modules that are never reached on MRSIPrep's call paths: EasyReg,
# SynthSurf surface placement, photo reconstruction, claustrum/thalamic-nuclei
# /pineal-gland segmentation, SynthSR super-resolution, SynthSeg's QC scorer
# (no --qc flag is passed), TopoFit/JOSA surface placement, and ex-vivo atlases.
rm -f \
  "${FS_ROOT}/models/easyreg_"*.h5 \
  "${FS_ROOT}/models/synthsurf_"*.h5 \
  "${FS_ROOT}/models/synthseg_photo_"*.h5 \
  "${FS_ROOT}/models/claustrum_seg_"*.h5 \
  "${FS_ROOT}/models/thalseg_"*.h5 \
  "${FS_ROOT}/models/synthsr_"*.h5 \
  "${FS_ROOT}/models/synthseg_qc_"*.h5 \
  "${FS_ROOT}/models/exvivo."*.h5 \
  "${FS_ROOT}/models/mris_register_josa_"*.h5 \
  "${FS_ROOT}/models/sclimbic."*.h5
rm -rf \
  "${FS_ROOT}/models/pglands_seg" \
  "${FS_ROOT}/models/topofit"

# The source image may predate the SynthSeg-only extraction workflow. Remove
# HD-BET and its dedicated inference stack before flattening the runtime.
/usr/bin/python3 -m pip uninstall -y \
  HD-BET nnunetv2 batchgenerators batchgeneratorsv2 \
  dynamic-network-architectures acvl-utils SimpleITK \
  torch torchvision timm 2>/dev/null || true

# NOTE: torch inside FreeSurfer's bundled fspython environment
# (python/lib/python3.8/site-packages) was investigated as a pruning
# candidate (mri_synthseg's own script never imports it) but is NOT
# removable: recon-all -all's V8 default pipeline directly invokes
# mri_synthstrip (see recon-all's `mri_synthstrip --threads ... -i ... -o
# ...` call), and mri_synthstrip's script imports torch/torch.nn directly.
# Removing it broke recon-all in this build; left in place.

# Build and package caches are not runtime dependencies.
rm -rf \
  /root/.cache \
  /root/.conda \
  /root/.npm \
  /tmp/* \
  /var/tmp/* \
  /var/lib/apt/lists/* \
  /var/cache/apt/*
python_lib_dir="$(/usr/bin/python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
find "${python_lib_dir}" /opt/petpvc -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "${python_lib_dir}" /opt/petpvc -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true

printf 'Installed sizes after pruning:\n'
du -sh "${FSL_ROOT}" "${FS_ROOT}" "${ANTS_ROOT}" 2>/dev/null || true

if ldd "${FSL_ROOT}/bin/fast" | grep -q 'not found'; then
  printf 'FAST has unresolved shared-library dependencies after pruning.\n' >&2
  exit 1
fi
if [[ -x "${ANTS_ROOT}/bin/antsRegistration" ]] && ldd "${ANTS_ROOT}/bin/antsRegistration" | grep -q 'not found'; then
  printf 'antsRegistration has unresolved shared-library dependencies after pruning.\n' >&2
  exit 1
fi
command -v recon-all >/dev/null
command -v mri_synthseg >/dev/null
command -v mri_vol2vol >/dev/null
command -v antsRegistrationSyN.sh >/dev/null
command -v antsApplyTransforms >/dev/null
