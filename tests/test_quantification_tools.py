import unittest

import numpy as np

from mrsiprep.mrsi.quantification_tools import (
    SUPPORTED_TOOLS,
    QuantificationToolError,
    get_tool,
    normalize_linewidth_to_hz,
    resolve_crlb_unit,
    resolve_linewidth_unit,
    resolve_quantification_tool,
)


class QuantificationToolsTests(unittest.TestCase):
    def test_supported_tools_are_verified_only(self):
        self.assertEqual(set(SUPPORTED_TOOLS), {"lcmodel", "fsl-mrs", "osprey", "custom"})

    def test_get_tool_rejects_unverified_tool(self):
        with self.assertRaisesRegex(QuantificationToolError, "tarquin"):
            get_tool("tarquin")

    def test_verified_tools_are_identity_scaling(self):
        values = np.array([1.0, 2.0, 3.0])
        for name in ("lcmodel", "fsl-mrs", "osprey", "custom"):
            tool = get_tool(name)
            np.testing.assert_array_equal(tool.crlb_scale(values), values)
            np.testing.assert_array_equal(tool.snr_scale(values), values)
            np.testing.assert_array_equal(tool.linewidth_scale(values), values)

    def test_cli_value_takes_precedence_over_mrsinmrs(self):
        mrsinmrs = {"CommonMetadata": {"QuantificationTool": "custom"}}
        self.assertEqual(resolve_quantification_tool("lcmodel", mrsinmrs), "lcmodel")

    def test_falls_back_to_mrsinmrs_common_metadata(self):
        mrsinmrs = {"CommonMetadata": {"QuantificationTool": "fsl-mrs"}}
        self.assertEqual(resolve_quantification_tool(None, mrsinmrs), "fsl-mrs")

    def test_raises_when_neither_source_declares_a_tool(self):
        with self.assertRaisesRegex(QuantificationToolError, "No upstream quantification tool"):
            resolve_quantification_tool(None, {"CommonMetadata": {}})
        with self.assertRaisesRegex(QuantificationToolError, "No upstream quantification tool"):
            resolve_quantification_tool(None, None)

    def test_rejects_unverified_tool_declared_in_mrsinmrs(self):
        mrsinmrs = {"CommonMetadata": {"QuantificationTool": "jmrui"}}
        with self.assertRaisesRegex(QuantificationToolError, "Unsupported"):
            resolve_quantification_tool(None, mrsinmrs)

    def test_resolve_linewidth_unit_cli_takes_precedence(self):
        mrsinmrs = {"CommonMetadata": {"LinewidthUnit": "ppm"}}
        self.assertEqual(resolve_linewidth_unit("Hz", mrsinmrs), "Hz")

    def test_resolve_linewidth_unit_falls_back_to_mrsinmrs(self):
        mrsinmrs = {"CommonMetadata": {"LinewidthUnit": "ppm"}}
        self.assertEqual(resolve_linewidth_unit(None, mrsinmrs), "ppm")

    def test_resolve_linewidth_unit_raises_when_undeclared(self):
        with self.assertRaisesRegex(QuantificationToolError, "No linewidth unit"):
            resolve_linewidth_unit(None, {"CommonMetadata": {}})

    def test_resolve_linewidth_unit_rejects_unsupported_value(self):
        with self.assertRaisesRegex(QuantificationToolError, "Unsupported --linewidth-unit"):
            resolve_linewidth_unit("Tesla", None)
        with self.assertRaisesRegex(QuantificationToolError, "Unsupported LinewidthUnit"):
            resolve_linewidth_unit(None, {"CommonMetadata": {"LinewidthUnit": "Tesla"}})

    def test_resolve_crlb_unit_raises_when_undeclared(self):
        with self.assertRaisesRegex(QuantificationToolError, "No CRLB unit"):
            resolve_crlb_unit(None, {"CommonMetadata": {}})

    def test_resolve_crlb_unit_accepts_percent(self):
        self.assertEqual(resolve_crlb_unit(None, {"CommonMetadata": {"CRLBUnit": "percent"}}), "percent")
        self.assertEqual(resolve_crlb_unit("percent", None), "percent")

    def test_normalize_linewidth_hz_is_unchanged(self):
        values = np.array([5.0, 10.0])
        np.testing.assert_array_equal(normalize_linewidth_to_hz(values, "Hz", "1H", None), values)

    def test_normalize_linewidth_ppm_converts_using_field_strength(self):
        values = np.array([0.1])
        hz = normalize_linewidth_to_hz(values, "ppm", "1H", 3.0)
        self.assertAlmostEqual(hz[0], 0.1 * 42.577478 * 3.0)

    def test_normalize_linewidth_ppm_without_field_strength_raises(self):
        with self.assertRaisesRegex(QuantificationToolError, "MagneticFieldStrength"):
            normalize_linewidth_to_hz(np.array([0.1]), "ppm", "1H", None)

    def test_normalize_linewidth_ppm_for_uncurated_nucleus_raises(self):
        with self.assertRaisesRegex(QuantificationToolError, "no gyromagnetic ratio"):
            normalize_linewidth_to_hz(np.array([0.1]), "ppm", "31P", 3.0)


if __name__ == "__main__":
    unittest.main()
