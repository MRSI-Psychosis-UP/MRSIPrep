import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.reports.parcel_figures import write_parcel_coverage_figure


def _make_config(tmp_path: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )


class WriteParcelCoverageFigureTests(unittest.TestCase):
    def test_pins_colorbar_to_0_100_even_when_coverage_is_uniform(self):
        """Regression test: a perfectly uniform 100% coverage field (a
        realistic case -- coverage is often exactly 100% everywhere) must
        not let matplotlib autoscale an arbitrary padded range (e.g.
        90-110%) around it; the colorbar should stay pinned to the metric's
        real 0-100% range."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            atlas_data = np.ones((6, 6, 6), dtype=np.int16)
            atlas_path = tmp_path / "atlas_mrsi.nii.gz"
            nib.save(nib.Nifti1Image(atlas_data, np.eye(4)), atlas_path)

            parcel_qc_tsv = tmp_path / "parcelqc.tsv"
            pd.DataFrame({"parcel_id": [1], "anatomical_coverage_percent": [100.0]}).to_csv(parcel_qc_tsv, sep="\t", index=False)

            captured = {}
            from mrsiprep.reports import parcel_figures as parcel_figures_module

            original = parcel_figures_module._render_axial_montage

            def _capture(*args, **kwargs):
                captured.update(kwargs)
                return original(*args, **kwargs)

            with mock.patch.object(parcel_figures_module, "_render_axial_montage", side_effect=_capture):
                write_parcel_coverage_figure(config, "S001", "V1", atlas_path, parcel_qc_tsv)

            self.assertEqual(captured.get("vmin"), 0.0)
            self.assertEqual(captured.get("vmax"), 100.0)


if __name__ == "__main__":
    unittest.main()
