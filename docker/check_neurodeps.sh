#!/usr/bin/env bash
set -euo pipefail

failures=0
MRSIPREP_PYTHON="${MRSIPREP_PYTHON:-/usr/bin/python3}"

check_command() {
  local command="$1"
  if path="$(command -v "${command}" 2>/dev/null)"; then
    printf '[OK] %-26s %s\n' "${command}" "${path}"
  else
    printf '[MISSING] %s\n' "${command}" >&2
    failures=$((failures + 1))
  fi
}

check_python_import() {
  local module="$1"
  if "${MRSIPREP_PYTHON}" -c "import ${module}" >/dev/null 2>&1; then
    printf '[OK] python import %-12s\n' "${module}"
  else
    printf '[MISSING] python import %s\n' "${module}" >&2
    failures=$((failures + 1))
  fi
}

check_file() {
  local path="$1"
  if [[ -r "${path}" ]]; then
    printf '[OK] file %-23s %s\n' "$(basename "${path}")" "${path}"
  else
    printf '[MISSING] file %s\n' "${path}" >&2
    failures=$((failures + 1))
  fi
}

printf '%s\n' 'MRSIPrep dependency verification'
printf '%s\n' '--------------------------------'
printf '[OK] %-26s %s\n' 'MRSIPrep Python' "${MRSIPREP_PYTHON}"

# Winning tissue method. FSL/FreeSurfer may be intentionally absent in the
# bootstrap image before manual installation.
if [[ "${REQUIRE_FREESURFER:-1}" == "1" ]]; then
  check_command mri_synthseg
  check_file "${FREESURFER_HOME:-/opt/freesurfer}/models/synthseg_robust_2.0.h5"
  check_file "${FREESURFER_HOME:-/opt/freesurfer}/subjects/fsaverage/mri/orig.mgz"
fi
if [[ "${REQUIRE_FSL:-1}" == "1" ]]; then
  check_command fast
  if command -v fast >/dev/null 2>&1 && ldd "$(command -v fast)" 2>/dev/null | grep -q 'not found'; then
    printf '[MISSING] FAST shared-library dependency\n' >&2
    failures=$((failures + 1))
  fi
fi
# ANTsPy default plus command-line fallback.
check_command antsRegistrationSyN.sh
check_command antsRegistration
check_command antsApplyTransforms
check_command N4BiasFieldCorrection

# --longitudinal subject-template construction (registration/subject_template.py).
check_command antsMultivariateTemplateConstruction2.sh
check_command antsAI
check_command AverageAffineTransform
check_command AverageAffineTransformNoRigid
check_command AverageImages
check_command ImageMath
check_command MultiplyImages
check_command ImageSetStatistics
check_command MeasureMinMaxMean

if [[ "${REQUIRE_PETPVC:-1}" == "1" ]]; then
  check_command petpvc
fi

if [[ "${REQUIRE_CHIMERA:-1}" == "1" ]]; then
  check_command chimera
  if [[ "${REQUIRE_FREESURFER:-1}" == "1" ]]; then
    check_command recon-all
    check_command mri_vol2vol
  fi
fi

for module in numpy scipy pandas nibabel nilearn matplotlib skimage rich ants; do
  check_python_import "${module}"
done

# nipype is pure-Python and installed at the thin app layer (Dockerfile), not
# the deps layer, so existing dependency images built before it was added
# still get it without a full deps rebuild (see Dockerfile's comment). Only
# require it here when explicitly requested (the app-layer build/test can set
# REQUIRE_NIPYPE=1 once it's actually expected to be present).
if [[ "${REQUIRE_NIPYPE:-0}" == "1" ]]; then
  check_python_import nipype
fi

if [[ "${failures}" -ne 0 ]]; then
  printf '\nDependency verification failed: %d missing item(s).\n' "${failures}" >&2
  exit 1
fi

printf '\nAll requested dependencies are installed.\n'
