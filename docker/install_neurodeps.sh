#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[mrsiprep-docker] %s\n' "$*" >&2
}

fetch_source() {
  local name="$1"
  local url="$2"
  local local_path="$3"
  local out_path="$4"

  if [[ -n "${local_path}" && -s "${local_path}" ]]; then
    log "Using local ${name} archive: ${local_path}"
    cp "${local_path}" "${out_path}"
    return 0
  fi

  if [[ -n "${url}" ]]; then
    log "Downloading ${name} from configured private URL"
    curl -fL --retry 3 --connect-timeout 30 "${url}" -o "${out_path}"
    return 0
  fi

  return 1
}

unpack_archive() {
  local archive="$1"
  local dest="$2"
  local strip="${3:-1}"

  mkdir -p "${dest}"
  if tar -tzf "${archive}" >/dev/null 2>&1; then
    tar -xzf "${archive}" -C "${dest}" --strip-components="${strip}"
  elif tar -tjf "${archive}" >/dev/null 2>&1; then
    tar -xjf "${archive}" -C "${dest}" --strip-components="${strip}"
  elif tar -tJf "${archive}" >/dev/null 2>&1; then
    tar -xJf "${archive}" -C "${dest}" --strip-components="${strip}"
  elif unzip -tq "${archive}" >/dev/null 2>&1; then
    local tmpdir
    tmpdir="$(mktemp -d)"
    unzip -q "${archive}" -d "${tmpdir}"
    local first
    first="$(find "${tmpdir}" -mindepth 1 -maxdepth 1 | head -n 1)"
    if [[ "${strip}" == "0" ]]; then
      cp -a "${tmpdir}/." "${dest}/"
    else
      cp -a "${first}/." "${dest}/"
    fi
    rm -rf "${tmpdir}"
  else
    log "Unsupported or corrupt archive: ${archive}"
    return 1
  fi
}

install_archive_dep() {
  local name="$1"
  local url="$2"
  local local_path="$3"
  local dest="$4"
  local required="$5"
  local strip="${6:-1}"
  local archive="/tmp/${name}.archive"

  if fetch_source "${name}" "${url}" "${local_path}" "${archive}"; then
    rm -rf "${dest}"
    unpack_archive "${archive}" "${dest}" "${strip}"
    rm -f "${archive}"
    log "Installed ${name} into ${dest}"
  elif [[ "${required}" == "required" ]]; then
    log "Missing required ${name}. Provide ${name^^}_URL or ${name^^}_TARBALL."
    exit 20
  else
    log "Skipping optional ${name}; provide ${name^^}_URL or ${name^^}_TARBALL to enable it."
  fi
}

install_fsl() {
  local archive="/tmp/fsl.archive"
  if fetch_source "fsl" "${FSL_URL:-}" "${FSL_TARBALL:-}" "${archive}"; then
    rm -rf /opt/fsl
    unpack_archive "${archive}" /opt/fsl 1
    rm -f "${archive}"
    log "Installed FSL archive into /opt/fsl"
    return
  fi

  if [[ -n "${FSL_INSTALLER_URL:-}" ]]; then
    log "Running FSL installer from configured private URL"
    rm -rf /opt/fsl
    if [[ "${FSL_INSTALLER_URL}" == *.sh ]]; then
      curl -fL --retry 3 "${FSL_INSTALLER_URL}" -o /tmp/fslinstaller.sh
      sh /tmp/fslinstaller.sh /opt/fsl
      rm -f /tmp/fslinstaller.sh
    else
      curl -fL --retry 3 "${FSL_INSTALLER_URL}" -o /tmp/fslinstaller.py
      /usr/bin/python3 /tmp/fslinstaller.py --dest /opt/fsl
      rm -f /tmp/fslinstaller.py
    fi
    return
  fi

  if [[ "${FSL_REQUIREMENT:-required}" == "required" ]]; then
    log "Missing required FSL. Provide FSL_URL/FSL_TARBALL or FSL_INSTALLER_URL."
    exit 20
  fi
  log "Skipping FSL for manual installation."
}

install_freesurfer() {
  local requirement="${FREESURFER_REQUIREMENT:-required}"
  local archive="/tmp/freesurfer.deb"
  if [[ "${FREESURFER_URL:-}" == *.deb || "${FREESURFER_TARBALL:-}" == *.deb ]]; then
    if fetch_source "freesurfer" "${FREESURFER_URL:-}" "${FREESURFER_TARBALL:-}" "${archive}"; then
      apt-get update
      apt-get install -y "${archive}"
      rm -f "${archive}"
      local fs_root=""
      for candidate in /usr/local/freesurfer/8.2.0 /usr/local/freesurfer; do
        if [[ -x "${candidate}/bin/mri_synthseg" ]]; then
          fs_root="${candidate}"
          break
        fi
      done
      if [[ -z "${fs_root}" ]]; then
        log "FreeSurfer package installed but mri_synthseg was not found."
        exit 20
      fi
      rm -rf /opt/freesurfer
      ln -s "${fs_root}" /opt/freesurfer
      return
    fi
  fi
  install_archive_dep "freesurfer" "${FREESURFER_URL:-}" "${FREESURFER_TARBALL:-}" /opt/freesurfer "${requirement}" 1
}

install_ants() {
  install_archive_dep "ants" "${ANTS_URL:-}" "${ANTS_TARBALL:-}" /opt/ants required 1
}

install_petpvc() {
  install_archive_dep "petpvc" "${PETPVC_URL:-}" "${PETPVC_TARBALL:-}" /opt/petpvc "${PETPVC_REQUIREMENT:-optional}" 1
}

install_chimera() {
  install_archive_dep "chimera" "${CHIMERA_URL:-}" "${CHIMERA_TARBALL:-}" /opt/chimera "${CHIMERA_REQUIREMENT:-optional}" 1
}

install_ants
install_fsl
install_freesurfer
install_petpvc
install_chimera

log "Dependency installation complete."
