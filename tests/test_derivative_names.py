from pathlib import Path
import unittest

from mrsiprep.io.naming import (
    anat_derivative,
    chimera_derivative,
    coverage_figure_derivative,
    coverage_report_html,
    mrsi_derivative,
    mrsi_parcel_dir,
    parcellation_derivative,
    provenance_derivative,
    qc_report_derivative,
)


class DerivativeNameTests(unittest.TestCase):
    def test_derivative_names(self):
        root = Path("/out")
        self.assertTrue(str(mrsi_derivative(root, "sub-S001", "ses-V1", space="MRSI", met="CrPCr", desc="qcmask", suffix_override="mask")).endswith(
            "sub-S001/ses-V1/qmasks/sub-S001_ses-V1_space-mrsi_met-CrPCr_desc-qcmask_mask.nii.gz"
        ))
        self.assertTrue(str(mrsi_derivative(root, "S001", "V1", space="MRSI", met="CrPCr", desc="preproc", suffix_override="mrsi")).endswith(
            "sub-S001/ses-V1/mrsi/orig/sub-S001_ses-V1_space-mrsi_met-CrPCr_desc-preproc_mrsi.nii.gz"
        ))
        self.assertTrue(str(mrsi_derivative(root, "S001", "V1", space="T1w", met="CrPCr", desc="preproc", suffix_override="mrsi")).endswith(
            "sub-S001/ses-V1/mrsi/t1w/sub-S001_ses-V1_space-T1w_met-CrPCr_desc-preproc_mrsi.nii.gz"
        ))
        self.assertTrue(str(mrsi_derivative(root, "S001", "V1", space="MNI152NLin2009cAsym", met="CrPCr", desc="preproc", suffix_override="mrsi")).endswith(
            "sub-S001/ses-V1/mrsi/mni/sub-S001_ses-V1_space-MNI152NLin2009cAsym_met-CrPCr_desc-preproc_mrsi.nii.gz"
        ))
        self.assertTrue(str(mrsi_derivative(root, "S001", "V1", space="MRSI", met="CrPCr", desc="pvc", suffix_override="mrsi")).endswith(
            "sub-S001/ses-V1/mrsi/orig-pvc/sub-S001_ses-V1_space-mrsi_met-CrPCr_desc-pvc_mrsi.nii.gz"
        ))
        self.assertTrue(str(mrsi_derivative(root, "S001", "V1", space="MRSI", label="GM", suffix_override="probseg")).endswith(
            "sub-S001/ses-V1/anat/tissue/sub-S001_ses-V1_space-mrsi_label-GM_probseg.nii.gz"
        ))
        self.assertTrue(str(anat_derivative(root, "S001", "V1", space="T1w", label="GM", suffix_override="probseg")).endswith(
            "sub-S001/ses-V1/anat/tissue/sub-S001_ses-V1_space-T1w_label-GM_probseg.nii.gz"
        ))
        self.assertTrue(str(anat_derivative(root, "S001", "V1", space="T1w", desc="brainCSF")).endswith(
            "sub-S001/ses-V1/anat/synthseg/sub-S001_ses-V1_space-T1w_desc-brainCSF_T1w.nii.gz"
        ))
        self.assertTrue(str(anat_derivative(root, "S001", "V1", space="T1w", desc="synthsegBrain")).endswith(
            "sub-S001/ses-V1/anat/synthseg/sub-S001_ses-V1_space-T1w_desc-synthsegBrain_T1w.nii.gz"
        ))
        self.assertTrue(str(anat_derivative(root, "S001", "V1", space="T1w", desc="synthsegParcRobust", suffix_override="dseg")).endswith(
            "sub-S001/ses-V1/anat/synthseg/sub-S001_ses-V1_space-T1w_desc-synthsegParcRobust_dseg.nii.gz"
        ))
        self.assertTrue(str(anat_derivative(root, "S001", "V1", space="T1w")).endswith(
            "sub-S001/ses-V1/anat/sub-S001_ses-V1_space-T1w_T1w.nii.gz"
        ))
        self.assertTrue(str(parcellation_derivative(root, "S001", "V1", space="MRSI", atlas="chimera", scale="scale3", desc="regional", suffix_override="tsv")).endswith(
            "sub-S001/ses-V1/anat/synthseg/sub-S001_ses-V1_space-mrsi_atlas-chimera_scale-scale3_desc-regional.tsv"
        ))
        self.assertTrue(str(chimera_derivative(root, "S001", "V1", space="MRSI", atlas="chimeraLFMIHIFIS", scale="scale3", suffix_override="dseg")).endswith(
            "chimera-atlases/sub-S001/ses-V1/anat/sub-S001_ses-V1_space-mrsi_atlas-chimeraLFMIHIFIS_scale-scale3_dseg.nii.gz"
        ))

    def test_mrsi_parcel_dir(self):
        root = Path("/out")
        self.assertTrue(str(mrsi_parcel_dir(root, "S001", "V1")).endswith("sub-S001/ses-V1/mrsi/parcel"))

    def test_reports_layout(self):
        root = Path("/out")
        self.assertTrue(str(coverage_report_html(root, "S001", "V1")).endswith(
            "sub-S001/ses-V1/reports/coverage/sub-S001_ses-V1_desc-report.html"
        ))
        self.assertTrue(str(coverage_figure_derivative(root, "S001", "V1", desc="parcelcoverage")).endswith(
            "sub-S001/ses-V1/reports/coverage/figures/sub-S001_ses-V1_desc-parcelcoverage.png"
        ))
        self.assertTrue(str(qc_report_derivative(root, "S001", "V1", "tissue")).endswith(
            "sub-S001/ses-V1/reports/qc-reports/sub-S001_ses-V1_step-tissue.html"
        ))
        self.assertTrue(str(provenance_derivative(root, "S001", "V1")).endswith(
            "sub-S001/ses-V1/reports/sub-S001_ses-V1_desc-provenance.json"
        ))


if __name__ == "__main__":
    unittest.main()
