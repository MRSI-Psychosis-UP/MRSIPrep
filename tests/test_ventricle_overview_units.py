import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mrsiprep.qc.ventricles import MetaboliteVentricles, VentricleDice, VentricleQC
from mrsiprep.reports.ventricle_overview import (
    MAX_MONTAGE_COLUMNS,
    _consensus_slice,
    _prior_slice_bias,
    _render_dice_bars,
    _render_ventricle_montage,
    _slice_counts,
    build_ventricle_qc_sections,
)

# Detection and Dice scoring are tested in test_qc_ventricles.py; this file
# covers what the report does with their results.


def _flat_bias(n_slices):
    """Neutral bias, for tests isolating the voting rule from the prior."""
    return np.ones(n_slices, dtype=float)


class ConsensusSliceTests(unittest.TestCase):
    def test_returns_slice_index_with_most_detected_voxels(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[:, :, 2] = True  # every voxel in slice z=2
        counts = [_slice_counts(detected)]
        self.assertEqual(_consensus_slice(counts, [_flat_bias(4)], min_voxels=3), 2)

    def test_returns_none_when_below_minimum(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[0, 0, 1] = True  # only 1 voxel anywhere
        counts = [_slice_counts(detected)]
        self.assertIsNone(_consensus_slice(counts, [_flat_bias(4)], min_voxels=3))

    def test_returns_none_for_no_metabolites(self):
        self.assertIsNone(_consensus_slice([], []))

    def test_majority_outvotes_a_single_dissenting_metabolite(self):
        """The reported bug: one noisy map landed on its own slice and the
        montage rendered each metabolite somewhere different."""
        agree_a = np.zeros(12, dtype=float); agree_a[7] = 10.0
        agree_b = np.zeros(12, dtype=float); agree_b[7] = 8.0
        dissent = np.zeros(12, dtype=float); dissent[2] = 40.0  # loudest in absolute terms
        bias = [_flat_bias(12)] * 3
        self.assertEqual(_consensus_slice([agree_a, agree_b, dissent], bias, min_voxels=3), 7)

    def test_a_single_high_snr_metabolite_cannot_dominate(self):
        # Per-metabolite peak normalisation is what makes this hold: without
        # it the 500-voxel map would win on raw magnitude alone.
        loud = np.zeros(10, dtype=float); loud[1] = 500.0
        quiet_a = np.zeros(10, dtype=float); quiet_a[6] = 4.0
        quiet_b = np.zeros(10, dtype=float); quiet_b[6] = 5.0
        bias = [_flat_bias(10)] * 3
        self.assertEqual(_consensus_slice([loud, quiet_a, quiet_b], bias, min_voxels=3), 6)

    def test_bias_cannot_manufacture_a_detection(self):
        # min_voxels is checked against raw counts, so a strong bias at a
        # slice with almost nothing detected must still return None.
        counts = [np.array([0.0, 1.0, 0.0, 0.0])]
        bias = [np.array([0.0, 100.0, 0.0, 0.0])]
        self.assertIsNone(_consensus_slice(counts, bias, min_voxels=3))


class PriorSliceBiasTests(unittest.TestCase):
    def test_peaks_at_the_priors_centre_of_mass(self):
        prior = np.zeros((4, 4, 11), dtype=bool)
        prior[:, :, 8] = True
        self.assertEqual(int(np.argmax(_prior_slice_bias(prior))), 8)

    def test_falls_back_to_the_array_middle_for_an_empty_prior(self):
        prior = np.zeros((4, 4, 11), dtype=bool)
        self.assertEqual(int(np.argmax(_prior_slice_bias(prior))), 5)

    def test_downweights_slices_far_from_the_prior(self):
        """Why the inferior-slice false positives went away: those slices
        are many sigma from where the prior puts the ventricles."""
        prior = np.zeros((4, 4, 20), dtype=bool)
        prior[:, :, 11] = True
        bias = _prior_slice_bias(prior)
        self.assertGreater(bias[11], bias[6])
        self.assertGreater(bias[10], bias[2])


class RenderVentricleMontageTests(unittest.TestCase):
    def test_wraps_rows_beyond_max_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            n_metabolites = MAX_MONTAGE_COLUMNS + 2  # forces a second row
            panels = []
            for i in range(n_metabolites):
                signal = np.ones((4, 4, 3), dtype=np.float32)
                prior_roi = np.zeros((4, 4, 3), dtype=bool)
                detected = np.zeros((4, 4, 3), dtype=bool)
                panels.append((f"MET{i}", signal, prior_roi, detected))
            result = _render_ventricle_montage(panels, 1, out_path)
            self.assertEqual(result, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)


class RenderDiceBarsTests(unittest.TestCase):
    def test_writes_a_figure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = _render_dice_bars({"CrPCr": 0.31, "Glu": 0.12, "NAA": 0.0}, Path(tmpdir) / "bars.png")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)


def _detection(met, detected, shape=(4, 4, 3)):
    prior = np.zeros(shape, dtype=bool)
    prior[:, :, 1] = True
    return MetaboliteVentricles(met, np.ones(shape, dtype=np.float32), prior, detected, np.ones(shape, dtype=bool))


def _slice1():
    mask = np.zeros((4, 4, 3), dtype=bool)
    mask[:, :, 1] = True
    return mask


class BuildVentricleQcSectionsTests(unittest.TestCase):
    def _build(self, result, tmpdir, reference=None):
        config = SimpleNamespace(derivative_dir=Path(tmpdir) / "derivatives" / "mrsiprep")
        with patch("mrsiprep.reports.ventricle_overview.run_ventricle_qc", return_value=result) as run:
            sections = build_ventricle_qc_sections(config, "01", "01", {"CrPCr": Path("c.nii.gz")}, reference_ventricles=reference)
        run.assert_called_once_with({"CrPCr": Path("c.nii.gz")}, reference)
        return config, sections

    def test_returns_empty_when_the_qc_cannot_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _config, sections = self._build(None, tmpdir)
        self.assertEqual(sections, [])

    def test_renders_every_detection_at_one_shared_slice(self):
        result = VentricleQC(detections=[_detection("Good", _slice1()), _detection("NoDetection", np.zeros((4, 4, 3), dtype=bool))])
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "mrsiprep.reports.ventricle_overview._render_ventricle_montage", return_value=Path(tmpdir) / "out.png"
        ) as render:
            _config, sections = self._build(result, tmpdir)
        panels, z, _ = render.call_args[0]
        self.assertEqual([p[0] for p in panels], ["Good", "NoDetection"])
        self.assertEqual(z, 1)
        title, body = sections[0]
        self.assertIn("Ventricle visibility", title)
        self.assertIn("z=1", body)
        self.assertNotIn("ventricle-dice.png", body)  # no reference, no chart

    def test_returns_empty_when_nothing_is_detected_and_there_is_no_reference(self):
        result = VentricleQC(detections=[_detection("CrPCr", np.zeros((4, 4, 3), dtype=bool))])
        with tempfile.TemporaryDirectory() as tmpdir:
            _config, sections = self._build(result, tmpdir)
        self.assertEqual(sections, [])

    def test_adds_the_dice_chart_and_table_with_a_reference(self):
        result = VentricleQC(
            detections=[_detection("CrPCr", _slice1()), _detection("Glu", _slice1())],
            dice=[VentricleDice("CrPCr", 1.0, 16, 16), VentricleDice("Glu", 0.0, 1, 16)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config, sections = self._build(result, tmpdir, reference=Path(tmpdir) / "vent.nii.gz")
            tsv = config.derivative_dir / "sub-01" / "ses-01" / "confounds" / "sub-01_ses-01_desc-ventricleqc.tsv"
            rows = tsv.read_text().splitlines()
            figures = list((config.derivative_dir / "sub-01" / "ses-01" / "reports" / "figures").glob("*ventricle-dice.png"))
        body = sections[0][1]
        self.assertIn("ventricle-qc.png", body)
        self.assertIn("ventricle-dice.png", body)
        self.assertIn("median 0.50", body)
        self.assertEqual(rows[3].split("\t")[:2], ["median", "0.5"])
        self.assertEqual(len(figures), 1)

    def test_keeps_the_dice_chart_when_nothing_is_detected(self):
        """No detection anywhere is itself the result (Dice 0): with a
        reference the section stays, without a montage."""
        empty = np.zeros((4, 4, 3), dtype=bool)
        result = VentricleQC(detections=[_detection("CrPCr", empty)], dice=[VentricleDice("CrPCr", 0.0, 0, 16)])
        with tempfile.TemporaryDirectory() as tmpdir:
            _config, sections = self._build(result, tmpdir, reference=Path(tmpdir) / "vent.nii.gz")
        body = sections[0][1]
        self.assertIn("No ventricle-like darkening", body)
        self.assertIn("ventricle-dice.png", body)
        self.assertNotIn("ventricle-qc.png", body)

    def test_skips_metabolites_on_different_grids(self):
        result = VentricleQC(detections=[_detection("A", _slice1()), _detection("B", np.zeros((2, 2, 2), dtype=bool), (2, 2, 2))])
        with tempfile.TemporaryDirectory() as tmpdir:
            _config, sections = self._build(result, tmpdir)
        self.assertEqual(sections, [])


if __name__ == "__main__":
    unittest.main()
