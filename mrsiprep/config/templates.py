"""Spatial reference templates, sourced from TemplateFlow.

Every image MRSIPrep normalizes into comes from here, so the space a run
resamples to is decided in one place rather than at each call site. That is
what makes the ``space-`` entity stamped on output filenames trustworthy, and
what a future non-MNI target would need to hook into.

**Why TemplateFlow.** MRSIPrep previously took its target from
``nilearn.datasets.load_mni152_template()`` while labelling outputs
``MNI152NLin2009cAsym``. Nilearn's template is ICBM152 2009 release *a* (its
own documentation says so, and directs users to TemplateFlow for the release
fMRIPrep uses), so the label named a release the data was not in. Sourcing
from TemplateFlow makes the label true, and makes MRSIPrep's derivatives
genuinely combinable with fMRIPrep's and with TemplateFlow atlases.

TemplateFlow normally downloads on demand. MRSIPrep pre-fetches the templates
it supports at image build time and pins ``TEMPLATEFLOW_HOME`` (see the
Dockerfile), so runs stay offline and reproducible; a missing template raises
with instructions rather than silently reaching for the network mid-run.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import nibabel as nib
import numpy as np

#: Templates MRSIPrep supports as an ``--output-spaces`` target. Adding one
#: means adding it here *and* to the Dockerfile's pre-fetch list, so the image
#: stays self-contained. See docs/extending.md.
SUPPORTED_TEMPLATES = ("MNI152NLin2009cAsym",)

DEFAULT_TEMPLATE = "MNI152NLin2009cAsym"


class TemplateError(RuntimeError):
    """Raised when a requested template or resolution cannot be provided."""


def available_templates() -> list[str]:
    return list(SUPPORTED_TEMPLATES)


def _check_supported(space: str) -> str:
    if space not in SUPPORTED_TEMPLATES:
        raise TemplateError(
            f"Unsupported template space {space!r}. Supported: {', '.join(SUPPORTED_TEMPLATES)}. "
            "To add another, extend SUPPORTED_TEMPLATES in mrsiprep/config/templates.py and the "
            "Dockerfile's TemplateFlow pre-fetch -- see docs/extending.md."
        )
    return space


@lru_cache(maxsize=32)
def _fetch(space: str, resolution: int, desc: str | None, suffix: str) -> Path:
    """Locate one TemplateFlow file, at TemplateFlow's own native resolutions."""
    _check_supported(space)
    try:
        from templateflow import api
    except ImportError as exc:  # pragma: no cover - templateflow ships in the image
        raise TemplateError(
            "templateflow is required to resolve reference templates but is not installed."
        ) from exc

    result = api.get(space, resolution=resolution, desc=desc, suffix=suffix, extension=".nii.gz")
    paths = [result] if isinstance(result, (str, Path)) else list(result)
    if not paths:
        raise TemplateError(
            f"TemplateFlow has no {suffix} (desc={desc}) for {space} at res-{resolution:02d}. "
            "If this image was built without pre-fetching it, rebuild with the Dockerfile's "
            "TemplateFlow step."
        )
    return Path(paths[0])


def _to_resolution(img, resolution_mm: int | None, interpolation: str):
    """Resample an image to an isotropic ``resolution_mm`` grid.

    TemplateFlow publishes only 1mm and 2mm, but ``--mni-resolution`` resolves
    to arbitrary integer millimetres (commonly the MRSI native resolution, e.g.
    5mm), so anything else is resampled here. This mirrors what
    ``nilearn.load_mni152_template(resolution)`` did before, keeping the
    resolution semantics of the flag unchanged -- only the underlying template
    release differs.

    ``interpolation`` must be ``"nearest"`` for label/mask images: continuous
    interpolation of a binary mask invents fractional values at the boundary.
    """
    if resolution_mm is None or resolution_mm == 1:
        return img
    from nilearn import image

    return image.resample_img(
        img,
        target_affine=np.diag([float(resolution_mm)] * 3),
        interpolation=interpolation,
        force_resample=True,
        copy_header=True,
    )


def _resampled(path: Path, resolution_mm: int | None, interpolation: str = "continuous"):
    return _to_resolution(nib.load(str(path)), resolution_mm, interpolation)


def template_t1w(resolution_mm: int | None = None, space: str = DEFAULT_TEMPLATE):
    """Skull-stripped template brain: the registration and resampling target."""
    _check_supported(space)
    head_img = nib.load(str(_fetch(space, 1, None, "T1w")))
    mask_img = nib.load(str(_fetch(space, 1, "brain", "mask")))

    # Plain array maths rather than nilearn's math_img(): that takes the
    # expression as a string and evaluates it, which is both harder to read
    # here and flagged by static analysis as dynamic-code evaluation.
    data = np.asarray(head_img.dataobj, dtype=np.float32) * (np.asarray(mask_img.dataobj) > 0)
    brain = nib.Nifti1Image(data, head_img.affine, head_img.header)
    return _to_resolution(brain, resolution_mm, "continuous")


def template_head(resolution_mm: int | None = None, space: str = DEFAULT_TEMPLATE):
    """Whole-head template, used as the QC report's overlay background."""
    return _resampled(_fetch(_check_supported(space), 1, None, "T1w"), resolution_mm)


def template_brain_mask(resolution_mm: int | None = None, space: str = DEFAULT_TEMPLATE):
    """Template brain mask, used by the signal-leakage QC.

    Comes from the same template as the resampling target, so "signal outside
    the brain" is measured against the space the data is actually in. It
    previously came from FSL's MNI152 (a different template lineage,
    NLin6Asym), which made the check subtly inconsistent with the output space.
    """
    # nearest: a brain mask is binary, and continuous interpolation would
    # produce fractional edge voxels that then threshold inconsistently.
    return _resampled(_fetch(_check_supported(space), 1, "brain", "mask"), resolution_mm, "nearest")
