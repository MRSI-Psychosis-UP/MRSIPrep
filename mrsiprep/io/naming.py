"""BIDS-like naming helpers."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.utils.misc import normalize_session, normalize_subject


def prefix(subject: str, session: str | None = None) -> str:
    parts = [f"sub-{normalize_subject(subject)}"]
    ses = normalize_session(session)
    if ses:
        parts.append(f"ses-{ses}")
    return "_".join(parts)


def subject_session_dir(root: Path, subject: str, session: str | None, suffix: str) -> Path:
    sub_dir = root / f"sub-{normalize_subject(subject)}"
    ses = normalize_session(session)
    return sub_dir / f"ses-{ses}" / suffix if ses else sub_dir / suffix


_SYNTHSEG_DESC_PREFIXES = ("synthsegBrain", "synthsegFastInput", "synthsegParc", "brainCSF")


def anat_derivative(root: Path, subject: str, session: str | None, **entities) -> Path:
    return _derivative(root, subject, session, _anat_folder(entities), "T1w", **entities)


def _anat_folder(entities: dict) -> str:
    desc = entities.get("desc")
    if entities.get("label") in {"GM", "WM", "CSF"}:
        return "anat/tissue"
    if desc is not None and any(str(desc).startswith(p) for p in _SYNTHSEG_DESC_PREFIXES):
        return "anat/synthseg"
    return "anat"


def mrsi_derivative(root: Path, subject: str, session: str | None, **entities) -> Path:
    return _derivative(root, subject, session, _mrsi_folder(entities), "mrsi", **entities)


def parcellation_derivative(root: Path, subject: str, session: str | None, **entities) -> Path:
    return _derivative(root, subject, session, "anat/synthseg", "dseg", **entities)


def mrsi_parcel_dir(root: Path, subject: str, session: str | None) -> Path:
    return subject_session_dir(root, subject, session, "mrsi/parcel")


def chimera_derivative(root: Path, subject: str, session: str | None, **entities) -> Path:
    sub_dir = root / "chimera-atlases" / f"sub-{normalize_subject(subject)}"
    ses = normalize_session(session)
    out_dir = sub_dir / f"ses-{ses}" / "anat" if ses else sub_dir / "anat"
    suffix = entities.pop("suffix_override", "dseg")
    name_parts = [prefix(subject, session)]
    for key in ("space", "atlas", "scale", "desc"):
        value = entities.get(key)
        if value is not None:
            value = _format_entity_value(key, value)
            name_parts.append(f"{key}-{value}")
    ext = f"_{suffix}.nii.gz" if suffix in {"dseg", "mask", "probseg"} else f".{suffix}"
    return out_dir / ("_".join(name_parts) + ext)


def connectome_derivative(root: Path, subject: str, session: str | None, suffix: str, **entities) -> Path:
    return _derivative(root, subject, session, "connectomics", suffix, **entities)


def coverage_report_dir(root: Path, subject: str, session: str | None) -> Path:
    return subject_session_dir(root, subject, session, "reports") / "coverage"


def coverage_figure_derivative(root: Path, subject: str, session: str | None, extension: str = "png", **entities) -> Path:
    out_dir = coverage_report_dir(root, subject, session) / "figures"
    suffix = entities.pop("suffix_override", extension)
    return _named(out_dir, subject, session, suffix, **entities)


def coverage_report_html(root: Path, subject: str, session: str | None) -> Path:
    return coverage_report_dir(root, subject, session) / f"{prefix(subject, session)}_desc-report.html"


def qc_report_derivative(root: Path, subject: str, session: str | None, step: str, extension: str = "html") -> Path:
    out_dir = subject_session_dir(root, subject, session, "reports") / "qc-reports"
    return out_dir / f"{prefix(subject, session)}_step-{step}.{extension}"


def provenance_derivative(root: Path, subject: str, session: str | None) -> Path:
    return subject_session_dir(root, subject, session, "reports") / f"{prefix(subject, session)}_desc-provenance.json"


def resampling_work_path(work_dir: Path, subject: str, session: str | None, **entities) -> Path:
    """Scratch location (under --work-dir) for resampled maps needed only to
    render a report, not intended as a permanent BIDS derivative."""
    return _derivative(work_dir, subject, session, "resampling", "mrsi", **entities)


def _mrsi_folder(entities: dict) -> str:
    desc = entities.get("desc")
    suffix = entities.get("suffix_override")
    space = entities.get("space")
    if entities.get("label") in {"GM", "WM", "CSF"}:
        return "anat/tissue"
    if desc == "pvc":
        return "mrsi/orig-pvc"
    if desc in {"brain", "mrsiqc", "qcmask", "spikemask"} or suffix == "mask":
        return "qmasks"
    if space == "MNI152NLin2009cAsym":
        return "mrsi/mni"
    if space == "T1w":
        return "mrsi/t1w"
    return "mrsi/orig"


def _named(out_dir: Path, subject: str, session: str | None, suffix: str, **entities) -> Path:
    suffix = entities.pop("suffix_override", suffix)
    name_parts = [prefix(subject, session)]
    order = [
        "space",
        "res",
        "met",
        "label",
        "atlas",
        "scale",
        "from_",
        "to",
        "mode",
        "desc",
    ]
    for key in order:
        if key not in entities:
            continue
        value = entities[key]
        if value is None:
            continue
        entity = "from" if key == "from_" else key
        value = _format_entity_value(entity, value)
        name_parts.append(f"{entity}-{value}")
    ext = suffix if suffix.startswith(".") else f"_{suffix}.nii.gz" if suffix in {"T1w", "mrsi", "dseg", "mask", "probseg"} else f".{suffix}"
    filename = "_".join(name_parts) + ext
    return out_dir / filename


def _derivative(root: Path, subject: str, session: str | None, folder: str, suffix: str, **entities) -> Path:
    out_dir = subject_session_dir(root, subject, session, folder)
    return _named(out_dir, subject, session, suffix, **entities)


def _format_entity_value(entity: str, value) -> str:
    if entity == "space" and value == "MRSI":
        return "mrsi"
    return str(value)


def transform_path(root: Path, subject: str, session: str | None, from_space: str, to_space: str, desc: str | None = None, ext: str = ".h5") -> Path:
    out_dir = subject_session_dir(root, subject, session, "anat" if from_space == "T1w" else "mrsi")
    parts = [prefix(subject, session), f"from-{from_space}", f"to-{to_space}"]
    if desc:
        parts.append(f"desc-{desc}")
    parts.append("xfm")
    return out_dir / ("_".join(parts) + ext)
