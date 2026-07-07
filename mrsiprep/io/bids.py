"""Input layout discovery for MRSIPrep."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mrsiprep.config.defaults import METABOLITE_ALIASES
from mrsiprep.utils.misc import normalize_session, normalize_subject, parse_bids_entities


@dataclass(frozen=True)
class Recording:
    subject: str
    session: str | None

    @property
    def prefix(self) -> str:
        if self.session:
            return f"sub-{self.subject}_ses-{self.session}"
        return f"sub-{self.subject}"


class BIDSLayout:
    """Minimal path resolver for the MRSI-Metabolic-Connectome derivative layout."""

    def __init__(self, bids_dir: str | Path):
        self.bids_dir = Path(bids_dir).resolve()
        self.derivatives = self.bids_dir / "derivatives"

    def discover_recordings(self) -> list[Recording]:
        participants = self.bids_dir / "participants_allsessions.tsv"
        if participants.exists():
            from mrsiprep.utils.misc import read_participant_pairs

            return [Recording(sub, ses) for sub, ses in read_participant_pairs(participants)]

        out: list[Recording] = []
        for sub_dir in sorted(self.bids_dir.glob("sub-*")):
            if not sub_dir.is_dir():
                continue
            subject = normalize_subject(sub_dir.name)
            ses_dirs = sorted(sub_dir.glob("ses-*"))
            if not ses_dirs:
                out.append(Recording(subject, None))
            for ses_dir in ses_dirs:
                out.append(Recording(subject, normalize_session(ses_dir.name)))
        return out

    def raw_t1(self, subject: str, session: str | None, reference_name: str | None = None) -> Path | None:
        anat_dir = self._raw_anat_dir(subject, session)
        if not anat_dir.exists():
            return None
        candidates = []
        for path in sorted(anat_dir.glob("*T1w.nii*")):
            if "_desc-" in path.name:
                continue
            if reference_name and reference_name in path.name:
                return path
            entities = parse_bids_entities(path)
            score = 0
            if entities.get("acq") in {"memprage", "mprage", "mp2rage"}:
                score += 2
            if entities.get("run") == "01":
                score += 1
            candidates.append((score, path))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1].name))
        return candidates[0][1]

    def t1(self, subject: str, session: str | None, pattern: str = "desc-brain_T1w") -> Path | None:
        if pattern and Path(pattern).exists():
            return Path(pattern).resolve()
        roots = [
            self.derivatives / "skullstrip" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session),
            self._raw_anat_dir(subject, session),
        ]
        for root in roots:
            if not root.exists():
                continue
            matches = sorted(path for path in root.glob("*.nii*") if pattern in path.name)
            if matches:
                return matches[0]
        return self.raw_t1(subject, session)

    def brain_mask(self, subject: str, session: str | None) -> Path | None:
        root = self.derivatives / "skullstrip" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session)
        if not root.exists():
            return None
        patterns = ["*desc-brainmask*T1w.nii*", "*desc-brain_mask.nii*", "*desc-brainmask.nii*"]
        for pattern in patterns:
            matches = sorted(root.glob(pattern))
            if matches:
                return matches[0]
        return None

    def cat12_probseg(self, subject: str, session: str | None, index: int) -> Path | None:
        root = self.derivatives / "cat12" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session)
        if not root.exists():
            return None
        matches = sorted(root.glob(f"*desc-p{index}_T1w.nii*"))
        return matches[0] if matches else None

    def mrsi_map(
        self,
        subject: str,
        session: str | None,
        desc: str,
        met: str | None = None,
        option: str | None = None,
        space: str = "orig",
        res: str | int | None = None,
        construct: bool = False,
    ) -> Path | None:
        root = self.derivatives / f"mrsi-{space}" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session)
        filename = self._mrsi_filename(subject, session, desc, met, option, space, res)
        direct = root / filename
        if direct.exists() or construct:
            return direct
        if met:
            for alias in METABOLITE_ALIASES.get(met, [met]):
                filename = self._mrsi_filename(subject, session, desc, alias, option, space, res)
                path = root / filename
                if path.exists():
                    return path
        if not root.exists():
            return None
        regex = self._mrsi_regex(subject, session, desc, met, option, space, res)
        matches = sorted(path for path in root.glob("*.nii*") if regex.match(path.name))
        return matches[0] if matches else None

    def all_mrsi_maps(self, subject: str, session: str | None, desc: str = "signal", space: str = "orig") -> list[Path]:
        root = self.derivatives / f"mrsi-{space}" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session)
        if not root.exists():
            return []
        return sorted(root.glob(f"{self._prefix(subject, session)}_space-{space}_met-*_desc-{desc}*_mrsi.nii*"))

    def transform(self, subject: str, session: str | None, stage: str, direction: str = "forward") -> list[Path]:
        sub = f"sub-{normalize_subject(subject)}"
        ses = self._ses_dir(session)
        base = self.derivatives / "mrsiprep" / sub
        if stage == "mrsi":
            path = base / ses / "transforms" / "mrsi"
            prefix = f"{sub}_{ses}_desc-mrsi_to_t1w"
            has_inv_affine = True
        elif stage in {"anat", "t1w"}:
            path = base / ses / "transforms" / "anat"
            prefix = f"{sub}_{ses}_desc-t1w_to_mni"
            has_inv_affine = True
        elif stage in {"t1-template", "template"}:
            path = base / ses / "transforms" / "anat"
            prefix = f"{sub}_{ses}_desc-t1w_to_template"
            has_inv_affine = False
        elif stage in {"template-mni", "ses-all"}:
            path = base / "ses-all" / "transforms" / "anat"
            prefix = f"{sub}_ses-all_desc-template_to_mni"
            has_inv_affine = False
        else:
            raise ValueError(f"Unsupported transform stage: {stage}")

        if direction == "forward":
            return [path / f"{prefix}.syn.nii.gz", path / f"{prefix}.affine.mat"]
        affine_inv = path / f"{prefix}.affine_inv.mat"
        paths = []
        if has_inv_affine or affine_inv.exists():
            paths.append(affine_inv)
        paths.append(path / f"{prefix}.syn_inv.nii.gz")
        return paths

    def chimera_atlas(self, subject: str, session: str | None, scheme: str, scale: int, grow: int = 2, space: str = "orig") -> Path | None:
        root = self.derivatives / "chimera-atlases" / f"sub-{normalize_subject(subject)}" / self._ses_dir(session) / "anat"
        if not root.exists():
            return None
        space_token = "orig" if space.lower() in {"t1w", "anat"} else space
        pattern = f"{self._prefix(subject, session)}*space-{space_token}_atlas-chimera{scheme}_desc-scale{scale}grow{grow}mm_dseg.nii*"
        matches = sorted(root.glob(pattern))
        return matches[0] if matches else None

    def _raw_anat_dir(self, subject: str, session: str | None) -> Path:
        path = self.bids_dir / f"sub-{normalize_subject(subject)}"
        ses = normalize_session(session)
        if ses:
            path = path / f"ses-{ses}"
        return path / "anat"

    def _ses_dir(self, session: str | None) -> str:
        ses = normalize_session(session)
        return f"ses-{ses}" if ses else ""

    def _prefix(self, subject: str, session: str | None) -> str:
        sub = f"sub-{normalize_subject(subject)}"
        ses = normalize_session(session)
        return f"{sub}_ses-{ses}" if ses else sub

    def _mrsi_filename(self, subject: str, session: str | None, desc: str, met: str | None, option: str | None, space: str, res: str | int | None) -> str:
        parts = [self._prefix(subject, session), f"space-{space}"]
        if res is not None:
            res_str = str(res)
            if not res_str.endswith("mm"):
                res_str = f"{res_str}mm"
            parts.append(f"res-{res_str}")
        if met:
            parts.append(f"met-{met}")
        parts.append(f"desc-{desc}")
        if option:
            parts.append(str(option))
        return "_".join(parts) + "_mrsi.nii.gz"

    def _mrsi_regex(self, subject: str, session: str | None, desc: str, met: str | None, option: str | None, space: str, res: str | int | None):
        prefix = re.escape(self._prefix(subject, session))
        met_part = rf"_met-{re.escape(met)}" if met else ""
        res_part = r"_res-[^_]+" if res is not None else r"(?:_res-[^_]+)?"
        option_part = rf"_{re.escape(option)}" if option else r"(?:_[^_]+)?"
        return re.compile(rf"^{prefix}_space-{re.escape(space)}{res_part}{met_part}_desc-{re.escape(desc)}{option_part}_mrsi\.nii(\.gz)?$")
