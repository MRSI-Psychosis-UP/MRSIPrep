"""Reference-template provider.

The point of these is the space contract: MRSIPrep stamps
``space-MNI152NLin2009cAsym`` on its outputs, and that is only honest if the
image it resamples into really is that template.
"""

import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.config import templates as T


def _img(shape=(4, 4, 4), value=1.0, zoom=1.0, dtype=np.float32):
    affine = np.diag([zoom, zoom, zoom, 1.0])
    return nib.Nifti1Image(np.full(shape, value, dtype=dtype), affine)


class SupportedTemplateTests(unittest.TestCase):
    def test_default_is_the_space_outputs_are_labelled_with(self):
        # If these ever disagree, every space- entity in the output tree is a lie.
        self.assertEqual(T.DEFAULT_TEMPLATE, "MNI152NLin2009cAsym")
        self.assertIn(T.DEFAULT_TEMPLATE, T.SUPPORTED_TEMPLATES)

    def test_available_templates_returns_a_copy(self):
        got = T.available_templates()
        got.append("bogus")
        self.assertNotIn("bogus", T.available_templates())

    def test_unsupported_space_raises_naming_the_file_to_extend(self):
        with self.assertRaises(T.TemplateError) as ctx:
            T.template_t1w(1, space="MNI152NLin6Asym")
        message = str(ctx.exception)
        self.assertIn("MNI152NLin6Asym", message)
        self.assertIn("MNI152NLin2009cAsym", message)
        self.assertIn("templates.py", message)


class ResolutionTests(unittest.TestCase):
    def test_native_resolution_is_returned_untouched(self):
        source = _img(zoom=1.0)
        self.assertIs(T._to_resolution(source, 1, "continuous"), source)
        self.assertIs(T._to_resolution(source, None, "continuous"), source)

    def test_other_resolutions_are_resampled_to_isotropic_voxels(self):
        varied = nib.Nifti1Image(
            np.arange(20 * 20 * 20, dtype=np.float32).reshape(20, 20, 20), np.eye(4)
        )
        out = T._to_resolution(varied, 5, "continuous")
        np.testing.assert_allclose(np.abs(np.diag(out.affine)[:3]), [5.0, 5.0, 5.0])

    def test_masks_resample_without_inventing_fractional_edges(self):
        # A binary mask through continuous interpolation acquires values
        # between 0 and 1 at the boundary, which then threshold inconsistently.
        data = np.zeros((20, 20, 20), dtype=np.float32)
        data[5:15, 5:15, 5:15] = 1.0
        mask = nib.Nifti1Image(data, np.eye(4))

        nearest = T._to_resolution(mask, 3, "nearest")
        self.assertEqual(set(np.unique(np.asarray(nearest.dataobj))), {0.0, 1.0})


class FetchTests(unittest.TestCase):
    def _api(self, result):
        """Stub templateflow without importing it.

        Importing the real package can reach for its remote skeleton on a
        cold cache, which would make these unit tests network-dependent.
        """
        pkg = ModuleType("templateflow")
        api = ModuleType("templateflow.api")
        api.get = lambda *a, **k: result
        pkg.api = api
        return patch.dict("sys.modules", {"templateflow": pkg, "templateflow.api": api})

    def test_single_path_result_is_accepted(self):
        T._fetch.cache_clear()
        with self._api(Path("/tpl/x.nii.gz")):
            self.assertEqual(T._fetch("MNI152NLin2009cAsym", 1, None, "T1w"), Path("/tpl/x.nii.gz"))
        T._fetch.cache_clear()

    def test_list_result_takes_the_first(self):
        T._fetch.cache_clear()
        with self._api([Path("/tpl/a.nii.gz"), Path("/tpl/b.nii.gz")]):
            self.assertEqual(T._fetch("MNI152NLin2009cAsym", 1, None, "T1w"), Path("/tpl/a.nii.gz"))
        T._fetch.cache_clear()

    def test_empty_result_raises_pointing_at_the_prefetch_step(self):
        T._fetch.cache_clear()
        with self._api([]):
            with self.assertRaises(T.TemplateError) as ctx:
                T._fetch("MNI152NLin2009cAsym", 1, None, "T1w")
        T._fetch.cache_clear()
        self.assertIn("Dockerfile", str(ctx.exception))

    def test_unsupported_space_is_rejected_before_any_fetch(self):
        with self.assertRaises(T.TemplateError):
            T._fetch("NotATemplate", 1, None, "T1w")


class TissueProbsegTests(unittest.TestCase):
    def test_unknown_label_is_rejected(self):
        with self.assertRaises(T.TemplateError) as ctx:
            T.template_tissue_probseg("BONE")
        self.assertIn("BONE", str(ctx.exception))
        self.assertIn("GM", str(ctx.exception))

    def test_requests_templateflow_by_label_not_desc(self):
        # TemplateFlow keys tissue maps by `label`, so passing GM as `desc`
        # would silently resolve to the wrong file (or none at all).
        with patch.object(T, "_fetch", return_value=Path("/tpl/gm.nii.gz")) as fetch, patch.object(
            T.nib, "load", return_value=_img()
        ):
            T.template_tissue_probseg("GM")
        self.assertEqual(fetch.call_args.args[3], "probseg")
        self.assertEqual(fetch.call_args.args[4], "GM")

    def test_interpolates_continuously_unlike_the_binary_mask(self):
        # These are probabilities, not a binary mask: nearest-neighbour would
        # throw away the partial-volume information the GM/WM QC compares.
        with patch.object(T, "_fetch", return_value=Path("/tpl/gm.nii.gz")), patch.object(
            T.nib, "load", return_value=_img()
        ), patch.object(T, "_to_resolution") as to_res:
            T.template_tissue_probseg("GM", 3)
        self.assertEqual(to_res.call_args.args[2], "continuous")


class ProviderTests(unittest.TestCase):
    """The three provider entry points, with TemplateFlow itself stubbed."""

    def _patched(self, head=None, mask=None):
        head = head if head is not None else _img(value=100.0)
        mask = mask if mask is not None else _img(value=1.0)

        def fetch(space, resolution, desc, suffix):
            return Path(f"/tpl/{suffix}-{desc}.nii.gz")

        def load(path):
            return mask if "mask" in str(path) else head

        return (
            patch.object(T, "_fetch", side_effect=fetch),
            patch.object(T.nib, "load", side_effect=load),
        )

    def test_t1w_target_is_brain_extracted(self):
        head = _img(shape=(2, 2, 2), value=100.0)
        mask = nib.Nifti1Image(np.array([[[1, 0], [0, 0]]] * 2, dtype=np.float32), np.eye(4))
        f, l = self._patched(head=head, mask=mask)
        with f, l:
            brain = T.template_t1w(1)
        data = np.asarray(brain.dataobj)
        # Skull/background voxels are zeroed by the brain mask.
        self.assertEqual(data[0, 0, 0], 100.0)
        self.assertEqual(data[0, 0, 1], 0.0)

    def test_head_is_not_brain_extracted(self):
        f, l = self._patched()
        with f, l:
            head = T.template_head(1)
        self.assertTrue(np.all(np.asarray(head.dataobj) == 100.0))

    def test_brain_mask_is_returned_as_is_at_native_resolution(self):
        f, l = self._patched()
        with f, l:
            mask = T.template_brain_mask(1)
        self.assertTrue(np.all(np.asarray(mask.dataobj) == 1.0))

    def test_each_entry_point_rejects_an_unsupported_space(self):
        for fn in (T.template_t1w, T.template_head, T.template_brain_mask):
            with self.assertRaises(T.TemplateError, msg=fn.__name__):
                fn(1, space="MNI152NLin6Asym")


if __name__ == "__main__":
    unittest.main()
