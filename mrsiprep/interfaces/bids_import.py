"""BIDS import helpers cropped from the MRSI-Metabolic-Connectome GUI utility."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

import nibabel as nib

from mrsiprep.utils.misc import normalize_session, parse_bids_entities

SESSION_PATTERN = re.compile(r"^(?P<sub>.+?)[_-](?P<session>[TtVv]\d+)$")
SUB_SES_PATTERN = re.compile(r"sub-(?P<sub>[^_]+).*ses-(?P<ses>[^_]+)", re.IGNORECASE)
LOOSE_SUB_SES_PATTERN = re.compile(r"(?P<sub>[A-Za-z0-9]+)[_-](?P<ses>[TtVv]\d+)")
CAT12_PREFIX_PATTERN = re.compile(r"^(?P<desc>(?:mwp|wp|p)\d+)", re.IGNORECASE)
MRI_CAT12_ALLOWED_PATTERN = re.compile(r"^(?P<desc>p\d+)_", re.IGNORECASE)

ACQ_MAPPING = {
    "conc": "signal",
    "crlb": "crlb",
    "snr": "snr",
    "fwhm": "fwhm",
}
DEFAULT_MRSI_METABOLITES = ["FWHM", "SNR", "Ins", "GPC+PCh", "Cr+PCr", "NAA+NAAG", "Glu+Gln"]
DEFAULT_MRSI_OTHERS = ["FWHM", "SNR", "brainmask", "WaterSignal"]


def parse_subject_session_folder(folder_name: str) -> dict | None:
    name = str(folder_name or "")
    if name.startswith("Results_"):
        name = name[len("Results_") :]
    match = SESSION_PATTERN.match(name)
    if not match:
        return None
    session = normalize_session(match.group("session"))
    return {"sub": match.group("sub"), "session": match.group("session"), "new_session": session}


def infer_anat_acq(filename: str) -> str:
    lower = filename.lower()
    if "mp2rage" in lower:
        return "mp2rage"
    if "mprage" in lower:
        return "mprage"
    if "memprage" in lower:
        return "memprage"
    return "unknown"


def find_mrsi_nifti_dir(folder_path: str | Path, input_subdir: str | None = None) -> Path | None:
    folder_path = Path(folder_path)
    folder_name = folder_path.name
    candidates = [folder_path / "MRSI_NIFTI"]
    if input_subdir:
        candidates.extend(
            [
                folder_path / input_subdir / f"Results_{folder_name}" / "MRSI_NIFTI",
                folder_path / input_subdir / "MRSI_NIFTI",
            ]
        )
    candidates.append(folder_path / f"Results_{folder_name}" / "MRSI_NIFTI")
    return next((path for path in candidates if path.is_dir()), None)


def find_matching_mrsi_files(mrs_dir: str | Path, include_metabolites: list[str] | None = None) -> list[Path]:
    mrs_dir = Path(mrs_dir)
    include_metabolites = include_metabolites or DEFAULT_MRSI_METABOLITES
    files = sorted(list(mrs_dir.glob("*.nii")) + list(mrs_dir.glob("*.nii.gz")))
    out: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        for token in include_metabolites:
            if f"_{token}_" in path.name and path not in seen:
                out.append(path)
                seen.add(path)
        for token in DEFAULT_MRSI_OTHERS:
            if f"_{token}." in path.name and path not in seen:
                out.append(path)
                seen.add(path)
    return out


def parse_mrsi_filename(path: str | Path) -> dict[str, str | None]:
    fname = Path(path).name
    new_met = None
    new_desc = None

    if re.search(r"brain[_]?mask", fname, re.IGNORECASE):
        new_desc = "brainmask"
    elif re.search(r"watersignal", fname, re.IGNORECASE):
        new_met = "water"
        new_desc = "signal"
    else:
        base = fname[:-7] if fname.endswith(".nii.gz") else Path(fname).stem
        if base.startswith("OrigRes_"):
            base = base[len("OrigRes_") :]
        parts = [part for part in base.split("_") if part]
        if not parts:
            raise ValueError(f"Unexpected MRSI filename: {fname}")
        if len(parts) == 1:
            acq = parts[0].lower()
        else:
            new_met = parts[0].replace("+", "").strip() or None
            acq = parts[1].lower()
            if "_".join(parts[1:]).lower() in ACQ_MAPPING:
                acq = "_".join(parts[1:]).lower()
        if acq not in ACQ_MAPPING:
            if "metabnorm" in acq:
                raise RuntimeError(f"Unsupported metabnorm file: {fname}")
            raise ValueError(f"Unknown MRSI acquisition token '{acq}' in {fname}")
        new_desc = ACQ_MAPPING[acq]
        if new_met and new_met.lower() == "voxel":
            new_met = None
    return {"met": new_met, "desc": new_desc}


def build_mrsi_destination(path: str | Path, bids_dir: str | Path, subject: str, session: str, met_override=None, desc_override=None) -> Path:
    parsed = parse_mrsi_filename(path)
    met = str(met_override).strip() if met_override else parsed["met"]
    desc = str(desc_override).strip() if desc_override else parsed["desc"]
    if not desc:
        raise ValueError(f"Could not determine desc for {path}")
    base = f"sub-{subject}_ses-{normalize_session(session)}_space-orig"
    if met:
        base += f"_met-{met}"
    base += f"_desc-{desc}_mrsi.nii.gz"
    return Path(bids_dir) / "derivatives" / "mrsi-orig" / f"sub-{subject}" / f"ses-{normalize_session(session)}" / base


def migrate_mrsi_file(path: str | Path, bids_dir: str | Path, subject: str, session: str, overwrite: bool = False, met_override=None, desc_override=None) -> tuple[Path, str]:
    out = build_mrsi_destination(path, bids_dir, subject, session, met_override, desc_override)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        return out, "skipped"
    nib.save(nib.load(str(path)), str(out))
    return out, "copied"


def migrate_anatomical_file(path: str | Path, bids_dir: str | Path, subject: str, session: str, overwrite: bool = False, acq: str | None = None) -> tuple[Path, str]:
    path = Path(path)
    acq = acq or infer_anat_acq(path.name)
    ses = normalize_session(session)
    out_dir = Path(bids_dir) / f"sub-{subject}" / f"ses-{ses}" / "anat"
    out = out_dir / f"sub-{subject}_ses-{ses}_acq-{acq}_T1w.nii.gz"
    out_dir.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        return out, "skipped"
    nib.save(nib.load(str(path)), str(out))
    return out, "copied"


def detect_cat12_file(path: str | Path) -> dict | None:
    path = Path(path)
    in_mri_folder = any(part.lower() == "mri" for part in path.parts)
    allowed_mri_match = MRI_CAT12_ALLOWED_PATTERN.match(path.name)
    prefix_match = CAT12_PREFIX_PATTERN.match(path.name)
    if not prefix_match:
        return None
    if in_mri_folder and not allowed_mri_match:
        return None
    subject, session = guess_subject_session(path)
    if not subject or not session:
        entities = parse_bids_entities(path)
        subject = subject or entities.get("sub") or ""
        session = session or normalize_session(entities.get("ses"))
    return {"source": path, "desc": prefix_match.group("desc").lower(), "sub": subject, "ses": session}


def guess_subject_session(path: Path) -> tuple[str, str | None]:
    candidates = [path.name, path.stem] + [parent.name for parent in path.parents]
    for candidate in candidates:
        match = SUB_SES_PATTERN.search(candidate)
        if match:
            return match.group("sub"), normalize_session(match.group("ses"))
    for candidate in candidates:
        if candidate.startswith("Results_"):
            candidate = candidate[len("Results_") :]
        match = LOOSE_SUB_SES_PATTERN.search(candidate)
        if match:
            return match.group("sub"), normalize_session(match.group("ses"))
    return "", None


def migrate_cat12_file(match: dict, bids_dir: str | Path, overwrite: bool = False) -> tuple[Path, str]:
    subject = match["sub"]
    session = normalize_session(match["ses"])
    desc = match["desc"]
    out = Path(bids_dir) / "derivatives" / "cat12" / f"sub-{subject}" / f"ses-{session}" / f"sub-{subject}_ses-{session}_desc-{desc}_T1w.nii.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        return out, "skipped"
    src = Path(match["source"])
    if src.name.endswith(".nii.gz"):
        shutil.copy2(src, out)
    else:
        nib.save(nib.load(str(src)), str(out))
    return out, "copied"


def migrate_session_folder(
    source: str | Path,
    bids_dir: str | Path,
    input_subdir: str | None = None,
    subject: str | None = None,
    session: str | None = None,
    overwrite: bool = False,
) -> dict:
    source = Path(source)
    meta = parse_subject_session_folder(source.name)
    subject = subject or (meta["sub"] if meta else None)
    session = normalize_session(session or (meta["new_session"] if meta else None))
    summary = {"mrsi": [], "t1": [], "cat12": [], "skipped": [], "errors": []}
    if not subject or not session:
        raise ValueError("Subject and session are required for import.")

    mrsi_dir = find_mrsi_nifti_dir(source, input_subdir)
    if mrsi_dir:
        for path in find_matching_mrsi_files(mrsi_dir):
            try:
                out, status = migrate_mrsi_file(path, bids_dir, subject, session, overwrite=overwrite)
                summary["mrsi"].append(str(out)) if status != "skipped" else summary["skipped"].append(str(out))
            except RuntimeError:
                continue
            except Exception as exc:
                summary["errors"].append(f"{path}: {exc}")

    for path in sorted(source.rglob("*.nii*")):
        if "MRSI_NIFTI" in path.parts:
            continue
        cat = detect_cat12_file(path)
        try:
            if cat:
                cat["sub"] = subject
                cat["ses"] = session
                out, status = migrate_cat12_file(cat, bids_dir, overwrite=overwrite)
                summary["cat12"].append(str(out)) if status != "skipped" else summary["skipped"].append(str(out))
            elif "t1" in path.name.lower() or "mprage" in path.name.lower():
                out, status = migrate_anatomical_file(path, bids_dir, subject, session, overwrite=overwrite)
                summary["t1"].append(str(out)) if status != "skipped" else summary["skipped"].append(str(out))
        except Exception as exc:
            summary["errors"].append(f"{path}: {exc}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import MRSI/T1/CAT12 files into the expected BIDS derivative layout.")
    parser.add_argument("source")
    parser.add_argument("bids_dir")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--input-subdir", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    summary = migrate_session_folder(args.source, args.bids_dir, args.input_subdir, args.subject, args.session, args.overwrite)
    for key, values in summary.items():
        print(f"{key}: {len(values)}")
    if summary["errors"]:
        for err in summary["errors"]:
            print(f"ERROR: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
