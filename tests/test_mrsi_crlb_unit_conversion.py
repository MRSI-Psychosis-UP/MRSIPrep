import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.workflows.mrsi import _copy_native_maps, run_mrsi_load_workflow


def _save(path: Path, values) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.asarray(values, dtype=np.float32).reshape(2, 2, 2), np.eye(4)), path)
    return path


def _read(path: Path):
    return np.asanyarray(nib.load(str(path)).dataobj)


def _config(root: Path, crlb_unit: str):
    return SimpleNamespace(derivative_dir=root / "out", crlb_unit=crlb_unit, correct_mrsi_orientation=False, mrsinmrs=None)


def _derivative_crlb(config):
    return mrsi_derivative(config.derivative_dir, "P001", "V1", space="orig", met="NAA", desc="crlb", suffix_override="mrsi")


class CopyNativeMapsCRLBUnitTests(unittest.TestCase):
    def _inputs(self, root: Path) -> MRSIInputs:
        return MRSIInputs(
            metabolite_maps={"NAA": _save(root / "in" / "naa.nii.gz", range(8))},
            crlb_maps={"NAA": _save(root / "in" / "crlb.nii.gz", [99, 150, 200, 9999, 50, 60, 70, 80])},
        )

    def test_permille_crlb_is_written_as_percent_and_input_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._inputs(root)
            config = _config(root, "permille")
            _copy_native_maps(config, "P001", "V1", inputs)
            np.testing.assert_allclose(_read(_derivative_crlb(config)).ravel(), [9.9, 15, 20, 999.9, 5, 6, 7, 8], rtol=1e-6)
            np.testing.assert_array_equal(_read(inputs.crlb_maps["NAA"]).ravel(), [99, 150, 200, 9999, 50, 60, 70, 80])
            self.assertEqual(list(_derivative_crlb(config).parent.glob(".tmp-*")), [])

    def test_rerun_does_not_convert_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._inputs(root)
            config = _config(root, "permille")
            _copy_native_maps(config, "P001", "V1", inputs)
            _copy_native_maps(config, "P001", "V1", inputs)
            self.assertAlmostEqual(float(_read(_derivative_crlb(config)).ravel()[0]), 9.9, places=5)

    def test_percent_crlb_is_copied_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._inputs(root)
            config = _config(root, "percent")
            _copy_native_maps(config, "P001", "V1", inputs)
            np.testing.assert_array_equal(_read(_derivative_crlb(config)).ravel(), [99, 150, 200, 9999, 50, 60, 70, 80])

    def test_permille_input_that_is_the_derivative_itself_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root, "permille")
            in_place = _save(_derivative_crlb(config), [99] * 8)
            inputs = MRSIInputs(metabolite_maps={}, crlb_maps={"NAA": in_place})
            with self.assertRaisesRegex(ValueError, "convert"):
                _copy_native_maps(config, "P001", "V1", inputs)
            np.testing.assert_array_equal(_read(in_place).ravel(), [99] * 8)


class LoadWorkflowCRLBRoutingTests(unittest.TestCase):
    def test_permille_routes_downstream_to_converted_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root, "permille")
            inputs = MRSIInputs(
                metabolite_maps={"NAA": _save(root / "in" / "naa.nii.gz", range(8))},
                crlb_maps={"NAA": _save(root / "in" / "crlb.nii.gz", [99] * 8)},
            )
            with patch("mrsiprep.workflows.mrsi.ensure_brainmask", return_value=root / "mask.nii.gz"):
                result = run_mrsi_load_workflow(config, "P001", "V1", inputs)
            self.assertEqual(result.crlb_maps["NAA"], _derivative_crlb(config))

    def test_percent_keeps_reading_the_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root, "percent")
            crlb_in = _save(root / "in" / "crlb.nii.gz", [9] * 8)
            inputs = MRSIInputs(metabolite_maps={"NAA": _save(root / "in" / "naa.nii.gz", range(8))}, crlb_maps={"NAA": crlb_in})
            with patch("mrsiprep.workflows.mrsi.ensure_brainmask", return_value=root / "mask.nii.gz"):
                result = run_mrsi_load_workflow(config, "P001", "V1", inputs)
            self.assertEqual(result.crlb_maps["NAA"], crlb_in)


if __name__ == "__main__":
    unittest.main()
