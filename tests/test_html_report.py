import tempfile
import types
import unittest
from pathlib import Path

import pandas as pd

from mrsiprep.reports.html import generate_subject_report


def _config(tmp_path: Path, **overrides) -> types.SimpleNamespace:
    base = dict(
        derivative_dir=tmp_path / "derivatives",
        bids_dir=Path("/data"),
        processing_mode="parc-con",
        tissue_backend="synthseg-fast",
        registration_backend="ants",
        registration_t1_target="brain-csf",
        normalization="simple",
        output_spaces=["MNI152NLin2009cAsym"],
        parcellation_mode="chimera",
        atlas="chimera-LFMIHIFIS_scale3",
        snr_min=4.0,
        linewidth_max=0.1,
        crlb_max=20.0,
        filter_biharmonic=True,
        spike_percentile=99.0,
        no_pvc=False,
        t1_correction="none",
        write_connectivity=True,
        nproc=1,
        nthreads=4,
        preset_citation=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


_EMPTY_QC_SECTIONS = {
    "tissue": [],
    "mrsi_raw": [],
    "mrsi_preproc": [],
    "t1_correction": None,
    "t1w_alignment": [],
    "mni_alignment": [],
    "parcellation": [],
    "connectivity": None,
    "runtime": [],
}


class GenerateSubjectReportTabsTests(unittest.TestCase):
    def test_always_present_tabs_are_rendered(self):
        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td))
            out = generate_subject_report(config, "S001", "V1", {}, _EMPTY_QC_SECTIONS)
            html = out.read_text()
            for tab_id in ("acquisition", "mrsi-raw-qc", "preproc", "anatomical", "spike-filter", "t1w-alignment", "coverage", "mni-alignment", "parcellation", "runtime", "outputs"):
                self.assertIn(f"data-tab='{tab_id}'", html, f"missing tab button: {tab_id}")
                self.assertIn(f"id='{tab_id}'", html, f"missing tab panel: {tab_id}")

    def test_t1_correction_tab_present_only_when_sections_given(self):
        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td))
            sections = dict(_EMPTY_QC_SECTIONS, t1_correction=[("Saturation correction factors", "<p>x</p>")])
            out = generate_subject_report(config, "S001", "V1", {}, sections)
            self.assertIn("data-tab='t1-correction'", out.read_text())

        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td))
            out = generate_subject_report(config, "S002", "V1", {}, _EMPTY_QC_SECTIONS)
            self.assertNotIn("data-tab='t1-correction'", out.read_text())

    def test_mrsi_raw_sections_appear_inside_mrsi_raw_qc_tab_not_a_separate_tab(self):
        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td))
            sections = dict(_EMPTY_QC_SECTIONS, mrsi_raw=[("Metabolite: CrPCr", "<img src='figures/raw-slices.png'>")])
            out = generate_subject_report(config, "S001", "V1", {}, sections)
            html = out.read_text()
            self.assertNotIn("data-tab='mrsi-raw'", html, "raw maps must not get their own tab")
            mrsi_qc_panel = html[html.index("id='mrsi-raw-qc'") : html.index("id='preproc'")]
            self.assertIn("raw-slices.png", mrsi_qc_panel)
            self.assertIn("Raw metabolite maps", mrsi_qc_panel)

    def test_connectivity_tab_present_only_when_sections_given(self):
        """Gated on qc_sections['connectivity'] being non-None (set whenever
        processing_mode == parc-con, regardless of --write-connectivity),
        not directly on config.write_connectivity -- parc-con without
        --write-connectivity still gets a tab explaining it wasn't requested."""
        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td), write_connectivity=False)
            sections = dict(_EMPTY_QC_SECTIONS, connectivity=[("Connectivity matrix", "<p>not requested</p>")])
            out = generate_subject_report(config, "S001", "V1", {}, sections)
            html = out.read_text()
            self.assertIn("data-tab='connectivity'", html)
            self.assertIn("not requested", html)

        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td), processing_mode="mni-norm", write_connectivity=False)
            out = generate_subject_report(config, "S002", "V1", {}, _EMPTY_QC_SECTIONS)
            self.assertNotIn("data-tab='connectivity'", out.read_text())

    def test_leakage_table_appears_in_matching_space_tab_only(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _config(tmp_path)
            leakage_qc = tmp_path / "leakage.tsv"
            pd.DataFrame(
                {
                    "space": ["T1w", "MNI152NLin2009cAsym"],
                    "metabolite": ["CrPCr", "CrPCr"],
                    "n_quality_voxels": [10, 10],
                    "total_signal_mass": [100.0, 100.0],
                    "leakage_signal_mass": [1.0, 5.0],
                    "leakage_fraction": [0.01, 0.05],
                    "leakage_percent": [1.0, 5.0],
                }
            ).to_csv(leakage_qc, sep="\t", index=False)
            out = generate_subject_report(config, "S001", "V1", {"leakage_qc": leakage_qc}, _EMPTY_QC_SECTIONS)
            html = out.read_text()

            t1_panel = html[html.index("id='t1w-alignment'") : html.index("id='coverage'")]
            mni_panel = html[html.index("id='mni-alignment'") : html.index("id='parcellation'")]
            self.assertIn("1.000", t1_panel)
            self.assertNotIn("5.000", t1_panel)
            self.assertIn("5.000", mni_panel)
            self.assertNotIn("1.000", mni_panel)

    def test_no_regional_metabolites_tab(self):
        with tempfile.TemporaryDirectory() as td:
            config = _config(Path(td))
            out = generate_subject_report(config, "S001", "V1", {}, _EMPTY_QC_SECTIONS)
            self.assertNotIn("data-tab='regional'", out.read_text())


if __name__ == "__main__":
    unittest.main()
