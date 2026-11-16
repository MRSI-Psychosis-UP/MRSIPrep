"""Input layout discovery for MRSIPrep."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mrsiprep.config.defaults import METABOLITE_ALIASES
from mrsiprep.utils.misc import normalize_session, normalize_subject, parse_bids_entities

# Long-form PyBIDS-style entity names accepted in --bids-filter-file,
# mapped to the short-form keys parse_bids_entities() actually returns.
_FILTER_ENTITY_ALIASES = {
    "subject": "sub",
    "session": "ses",
    "acquisition": "acq",
    "run": "run",
    "acq": "acq",
    "sub": "sub",
    "ses": "ses",
}

_SUPPORTED_BIDS_FILTER_KEYS = {"t1w"}


@dataclass(frozen=True)
class Recording:
    subject: str
    session: str | None

    @property
    def prefix(self) -> str:
        if self.session:
            return f"sub-{self.subject}_ses-{self.session}"
        return f"sub-{self.subject}"


def load_bids_filters(path: str | Path | None) -> dict:
    """Parse a --bids-filter-file JSON document.

    Only the "t1w" top-level key is currently supported (the one input
    MRSIPrep has ambiguous-candidate logic for today, in
    BIDSLayout.raw_t1()). Any other top-level key raises immediately rather
    than being silently ignored and  should get fast feedback that
    those aren't supported here yet.
    """
    if path is None:
        return {}
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse --bids-filter-file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"--bids-filter-file {path} must contain a JSON object at the top level.")
    unsupported = set(data) - _SUPPORTED_BIDS_FILTER_KEYS
    if unsupported:
        raise ValueError(
            f"--bids-filter-file {path} has unsupported key(s) {sorted(unsupported)}; "
            f"only {sorted(_SUPPORTED_BIDS_FILTER_KEYS)} is currently supported."
        )
    return data


def _normalize_mrsi_input_dir(mrsi_input_dir: str | Path) -> Path:
    """Resolve --mrsi-input-dir to the bids_dir-equivalent root
    _mrsi_input_roots() expects, accepting either that root directly or the
    mrsi-<space> data folder itself (e.g. a path ending in
    "derivatives/mrsi-orig" or "derivatives/mrsiprep/sub-X/ses-Y/mrsi/orig")
    -- a natural thing to point at, since that is where the files actually
    are. Walks back up past any "mrsi-<space>"/"mrsi"/"derivatives" and
    "sub-*"/"ses-*" path segments it finds at the tail, so either spelling
    resolves to the same root.
    """
    path = Path(mrsi_input_dir).resolve()
    parts = list(path.parts)
    while parts:
        tail = parts[-1]
        if tail == "derivatives" or tail.startswith("mrsi-") or tail == "mrsi" or re.fullmatch(r"(sub|ses)-.+", tail):
            parts.pop()
            continue
        break
    return Path(*parts) if parts else path


class BIDSLayout:
    """Minimal path resolver for the MRSI-Metabolic-Connectome derivative layout."""

    def __init__(
        self,
        bids_dir: str | Path,
        filters: dict | None = None,
        metabolite_aliases: dict | None = None,
        mrsi_input_dir: str | Path | None = None,
    ):
        self.bids_dir = Path(bids_dir).resolve()
        self.derivatives = self.bids_dir / "derivatives"
        # Root that raw MRSI derivatives (derivatives/mrsi-<space>/...) are
        # read from. Defaults to bids_dir, same as the anatomical (T1w) data;
        # set separately when the MRSI acquisition tree lives elsewhere.
        # Accepts either a bids_dir-equivalent root, or the mrsi-<space>
        # data folder itself (e.g. ".../derivatives/mrsi-orig") -- a very
        # natural thing to point at directly, so it's auto-normalized back
        # to the root level _mrsi_input_roots() expects, rather than
        # silently doubling "derivatives/mrsi-<space>" in the looked-up path.
        self.mrsi_root = _normalize_mrsi_input_dir(mrsi_input_dir) if mrsi_input_dir is not None else self.bids_dir
        self.mrsi_derivatives = self.mrsi_root / "derivatives"
        self.filters = filters or {}
        # Alias spellings tried when a metabolite's map isn't found under its
        # requested name. Nucleus-dependent, so callers with a config should
        # use from_config(); the proton table is the standalone default.
        self.metabolite_aliases = METABOLITE_ALIASES if metabolite_aliases is None else metabolite_aliases

    @classmethod
    def from_config(cls, config) -> "BIDSLayout":
        """Build a layout from a run config, carrying its nucleus's aliases."""
        return cls(
            config.bids_dir,
            filters=config.bids_filters,
            metabolite_aliases=config.nucleus_metabolite_aliases(),
            mrsi_input_dir=getattr(config, "mrsi_input_dir", None),
        )

    def discover_recordings(self) -> list[Recording]:
        participants = self.bids_dir / "participants_allsessions.tsv"
        if participants.exists():
            from mrsiprep.utils.misc import read_participant_pairs

            try:
                return [Recording(sub, ses) for sub, ses in read_participant_pairs(participants)]
            except UnicodeDecodeError:
                # Some projects keep this file encrypted at rest (e.g. GPG) for
                # identifying-data protection; fall back to a directory scan
                # rather than treating an unreadable file as a hard error.
                pass

        # Union sessions found under bids_dir (anat) and under mrsi_root
        # (raw MRSI) -- when --mrsi-input-dir points at a separate tree from
        # bids_dir, a subject can have session data on one side but not the
        # other (e.g. anat missing/incomplete on bids_dir while their MRSI
        # data is only under mrsi_root, or vice versa). Scanning only
        # bids_dir would silently report such a subject as sessionless/empty
        # even though real data exists.
        sessions_by_subject: dict[str, set[str | None]] = {}

        for sub_dir in sorted(self.bids_dir.glob("sub-*")):
            if not sub_dir.is_dir():
                continue
            subject = normalize_subject(sub_dir.name)
            ses_dirs = sorted(sub_dir.glob("ses-*"))
            sessions_by_subject.setdefault(subject, set())
            for ses_dir in ses_dirs:
                sessions_by_subject[subject].add(normalize_session(ses_dir.name))

        for mrsi_space_dir in sorted(self.mrsi_derivatives.glob("mrsi-*")):
            if not mrsi_space_dir.is_dir():
                continue
            for sub_dir in sorted(mrsi_space_dir.glob("sub-*")):
                if not sub_dir.is_dir():
                    continue
                subject = normalize_subject(sub_dir.name)
                ses_dirs = sorted(sub_dir.glob("ses-*"))
                sessions_by_subject.setdefault(subject, set())
                for ses_dir in ses_dirs:
                    sessions_by_subject[subject].add(normalize_session(ses_dir.name))

        out: list[Recording] = []
        for subject in sorted(sessions_by_subject):
            sessions = sessions_by_subject[subject]
            if not sessions:
                out.append(Recording(subject, None))
                continue
            for session in sorted(sessions, key=lambda s: (s is None, s)):
                out.append(Recording(subject, session))
        return out

    def raw_t1(self, subject: str, session: str | None, reference_name: str | None = None) -> Path | None:
        anat_dir = self._raw_anat_dir(subject, session)
        if not anat_dir.exists():
            return None
        t1w_filter = self.filters.get("t1w")
        candidates = []
        for path in sorted(anat_dir.glob("*T1w.nii*")):
            if "_desc-" in path.name:
                continue
            entities = parse_bids_entities(path)
            if t1w_filter and not _matches_filter(entities, t1w_filter):
                continue
            if reference_name and reference_name in path.name:
                return path
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

    def _mrsi_input_roots(self, subject: str, session: str | None, space: str) -> list[Path]:
        """Candidate roots for raw MRSI inputs, in priority order.

        The primary convention is a top-level `derivatives/mrsi-<space>/`
        tree (used by real acquisition datasets). When that root is missing
        or empty for this subject/session, fall back to MRSIPrep's own
        output layout (`derivatives/mrsiprep/sub-*/ses-*/mrsi/<space>/`) --
        this lets synthetic/test datasets that pre-populate MRSIPrep's
        output-shaped tree (e.g. synthMRSI) be consumed directly as input
        without a separate mrsi-<space> mirror.
        """
        sub = f"sub-{normalize_subject(subject)}"
        ses = self._ses_dir(session)
        primary = self.mrsi_derivatives / f"mrsi-{space}" / sub / ses
        roots = [primary]
        if not primary.exists() or not any(primary.iterdir()):
            fallback = self.derivatives / "mrsiprep" / sub / ses / "mrsi" / space
            roots.append(fallback)
        return roots

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
        roots = self._mrsi_input_roots(subject, session, space)
        filename = self._mrsi_filename(subject, session, desc, met, option, space, res)
        for root in roots:
            direct = root / filename
            if direct.exists() or (construct and root is roots[0]):
                return direct
            if met:
                for alias in self.metabolite_aliases.get(met, [met]):
                    alias_filename = self._mrsi_filename(subject, session, desc, alias, option, space, res)
                    path = root / alias_filename
                    if path.exists():
                        return path
            if not root.exists():
                continue
            regex = self._mrsi_regex(subject, session, desc, met, option, space, res)
            matches = sorted(path for path in root.glob("*.nii*") if regex.match(path.name))
            if matches:
                return matches[0]
        return None

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


def _matches_filter(entities: dict, filter_dict: dict) -> bool:
    """True if every key in filter_dict matches the corresponding parsed entity.

    Filter keys may use either MRSIPrep's short entity names (acq, run, ses,
    sub) or PyBIDS-style long names (acquisition, session, subject),
    per _FILTER_ENTITY_ALIASES. A filter value of null/None requires the
    entity to be absent from the filename.
    """
    for key, expected in filter_dict.items():
        short_key = _FILTER_ENTITY_ALIASES.get(key, key)
        actual = entities.get(short_key)
        if expected is None:
            if actual is not None:
                return False
        elif actual != str(expected):
            return False
    return True
