#!/usr/bin/env bash
# MRSIPrep entrypoint. Runs as root (required by recon-all/ANTs/chimera in
# some configurations), then, unless disabled, fixes ownership/permissions on
# the output directory so files written into a bind-mounted host volume are
# owned by the invoking host user rather than left root-owned and read-only
# to them.
#
# The output directory is the second positional CLI argument (bids_dir output_dir
# analysis_level ...), matching mrsiprep's own argument order.
#
# Controlled by:
#   HOST_UID / HOST_GID   - chown the output tree to this uid:gid afterward
#                            (defaults to the output directory's own owner if
#                            unset, so `-v host_dir:/out` where host_dir is
#                            already owned by the host user works with no
#                            extra flags).
#   MRSIPREP_NO_FIXPERMS=1 - skip the chown/chmod step entirely.
#
# Timestamps (console, logbook, provenance) use the container's clock, which
# defaults to UTC regardless of the host's timezone. Pass -e TZ=<host tz>
# (e.g. -e TZ=$(cat /etc/timezone) on Linux) to align them with the host.
set -euo pipefail

if [[ -n "${TZ:-}" && -f "/usr/share/zoneinfo/${TZ}" ]]; then
  ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
  echo "${TZ}" > /etc/timezone
fi

/usr/bin/python3 -m mrsiprep.cli.run "$@"
status=$?

if [[ "${MRSIPREP_NO_FIXPERMS:-0}" != "1" ]]; then
  out_dir="${2:-}"
  if [[ -n "${out_dir}" && -d "${out_dir}" ]]; then
    uid="${HOST_UID:-}"
    gid="${HOST_GID:-}"
    if [[ -z "${uid}" || -z "${gid}" ]]; then
      uid="$(stat -c '%u' "${out_dir}")"
      gid="$(stat -c '%g' "${out_dir}")"
    fi
    chown -R "${uid}:${gid}" "${out_dir}" 2>/dev/null || true
    chmod -R u+rwX,go+rX "${out_dir}" 2>/dev/null || true
  fi
fi

exit "${status}"
