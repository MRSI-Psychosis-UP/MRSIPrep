import unittest

import numpy as np

from mrsiprep.mrsi.quantification_tools import (
    SUPPORTED_TOOLS,
    QuantificationToolError,
    get_tool,
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


if __name__ == "__main__":
    unittest.main()
