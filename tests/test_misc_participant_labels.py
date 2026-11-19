"""Unit tests for mrsiprep.utils.misc.parse_participant_label_entry."""

from __future__ import annotations

import unittest

from mrsiprep.utils.misc import parse_participant_label_entry


class ParseParticipantLabelEntryTests(unittest.TestCase):
    def test_bare_subject_has_no_session(self):
        self.assertEqual(parse_participant_label_entry("5301"), ("5301", None))

    def test_bare_subject_with_sub_prefix(self):
        self.assertEqual(parse_participant_label_entry("sub-5301"), ("5301", None))

    def test_combined_sub_ses_with_prefixes(self):
        self.assertEqual(parse_participant_label_entry("sub-5301_ses-V6"), ("5301", "V6"))

    def test_combined_sub_ses_without_sub_prefix(self):
        self.assertEqual(parse_participant_label_entry("5301_ses-V6"), ("5301", "V6"))

    def test_session_normalization_applies(self):
        # normalize_session() maps a bare "T6"-style label to "V6"; the
        # combined-token path must reuse this, not bypass it.
        self.assertEqual(parse_participant_label_entry("5301_ses-T6"), ("5301", "V6"))

    def test_strips_whitespace(self):
        self.assertEqual(parse_participant_label_entry("  5301_ses-V6  "), ("5301", "V6"))


if __name__ == "__main__":
    unittest.main()
