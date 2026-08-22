import json
import tempfile
import unittest
from pathlib import Path

from mrsiprep.config import nuclei as N


def _table(**overrides):
    """A minimal valid table; overrides replace whole nucleus entries."""
    base = {
        "1H": {
            "display_name": "Proton",
            "aliases": ["1H", "proton"],
            "quality_defaults": {"snr_min": 4.0, "linewidth_max": 0.1, "crlb_max": 20.0},
            "metabolite_aliases": {"tCr": ["CrPCr", "tCr"]},
            "status": "curated",
            "notes": "",
            "source": "",
        }
    }
    base.update(overrides)
    return base


def _write(table) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(table, handle)
    handle.close()
    return Path(handle.name)


class LoadNucleiTests(unittest.TestCase):
    def test_shipped_table_loads_and_validates(self):
        table = N.load_nuclei()
        self.assertIn("1H", table)
        self.assertIn("31P", table)
        self.assertIn("2H", table)

    def test_rejects_a_non_object_top_level(self):
        path = _write([])
        with self.assertRaisesRegex(ValueError, "non-empty JSON object"):
            N.load_nuclei(path)

    def test_rejects_an_empty_table(self):
        with self.assertRaisesRegex(ValueError, "non-empty JSON object"):
            N.load_nuclei(_write({}))

    def test_missing_required_key_names_the_entry_and_the_key(self):
        broken = _table()
        del broken["1H"]["notes"]
        with self.assertRaisesRegex(ValueError, "'1H' is missing required keys: notes"):
            N.load_nuclei(_write(broken))

    def test_invalid_status_is_rejected(self):
        broken = _table()
        broken["1H"]["status"] = "probably-fine"
        with self.assertRaisesRegex(ValueError, "invalid status"):
            N.load_nuclei(_write(broken))

    def test_entry_without_aliases_is_rejected(self):
        broken = _table()
        broken["1H"]["aliases"] = []
        with self.assertRaisesRegex(ValueError, "at least one alias"):
            N.load_nuclei(_write(broken))

    def test_incomplete_quality_defaults_are_rejected(self):
        broken = _table()
        broken["1H"]["quality_defaults"] = {"snr_min": 4.0}
        with self.assertRaisesRegex(ValueError, "quality_defaults is missing: crlb_max, linewidth_max"):
            N.load_nuclei(_write(broken))

    def test_absent_quality_defaults_require_uncurated_status(self):
        # Guards against an entry claiming to be curated while shipping nothing.
        broken = _table()
        broken["1H"]["quality_defaults"] = None
        with self.assertRaisesRegex(ValueError, "use status 'uncurated'"):
            N.load_nuclei(_write(broken))

    def test_ambiguous_alias_across_two_nuclei_is_rejected(self):
        # Otherwise whichever entry iterated last would silently win.
        clash = _table(**{
            "31P": {
                "display_name": "Phosphorus",
                "aliases": ["31P", "proton"],
                "quality_defaults": None,
                "metabolite_aliases": {},
                "status": "uncurated",
                "notes": "",
                "source": None,
            }
        })
        with self.assertRaisesRegex(ValueError, "alias 'proton' maps to both"):
            N.load_nuclei(_write(clash))


class CanonicalNucleusTests(unittest.TestCase):
    def test_canonical_name_passes_through(self):
        self.assertEqual(N.canonical_nucleus("1H"), "1H")

    def test_aliases_resolve(self):
        for alias in ("proton", "H1", "h", "1h"):
            self.assertEqual(N.canonical_nucleus(alias), "1H", msg=alias)
        for alias in ("phosphorus", "P31", "31p"):
            self.assertEqual(N.canonical_nucleus(alias), "31P", msg=alias)
        for alias in ("deuterium", "D", "dmi"):
            self.assertEqual(N.canonical_nucleus(alias), "2H", msg=alias)

    def test_matching_is_case_and_whitespace_insensitive(self):
        self.assertEqual(N.canonical_nucleus("  ProTon "), "1H")

    def test_unknown_nucleus_lists_the_known_ones_and_names_the_file(self):
        with self.assertRaises(N.NucleusError) as ctx:
            N.canonical_nucleus("19F")
        message = str(ctx.exception)
        for known in ("1H", "2H", "31P"):
            self.assertIn(known, message)
        self.assertIn("nuclei.json", message)


class QualityDefaultsTests(unittest.TestCase):
    def test_proton_defaults_are_unchanged(self):
        # Regression guard for moving this table out of config/defaults.py --
        # these are the values MRSIPrep has always used.
        self.assertEqual(
            N.quality_defaults("1H"),
            {"snr_min": 4.0, "linewidth_max": 0.1, "crlb_max": 20.0},
        )

    def test_lookup_accepts_an_alias(self):
        self.assertEqual(N.quality_defaults("proton"), N.quality_defaults("1H"))

    def test_returns_a_copy_so_callers_cannot_mutate_the_table(self):
        first = N.quality_defaults("1H")
        first["snr_min"] = 999.0
        self.assertEqual(N.quality_defaults("1H")["snr_min"], 4.0)

    def test_uncurated_nucleus_refuses_rather_than_falling_back_to_proton(self):
        for nucleus in ("31P", "2H"):
            with self.assertRaises(N.NucleusError) as ctx:
                N.quality_defaults(nucleus)
            message = str(ctx.exception)
            self.assertIn("--snr-min", message)
            self.assertIn("nuclei.json", message)


class MetaboliteAliasTests(unittest.TestCase):
    def test_proton_alias_table_is_unchanged(self):
        # The exact table that used to live in config/defaults.py.
        self.assertEqual(
            N.metabolite_aliases("1H"),
            {
                "Glx": ["GluGln", "Glx"],
                "GluGln": ["GluGln", "Glx"],
                "NAA": ["NAA", "NAANAAG"],
                "tNAA": ["NAANAAG", "tNAA", "NAA"],
                "NAANAAG": ["NAANAAG", "tNAA", "NAA"],
                "Cho": ["GPCPCh", "Cho"],
                "GPCPCh": ["GPCPCh", "Cho"],
                "tCr": ["CrPCr", "tCr"],
                "CrPCr": ["CrPCr", "tCr"],
                "Ins": ["Ins"],
            },
        )

    def test_non_proton_nuclei_carry_their_own_metabolites(self):
        self.assertIn("PCr", N.metabolite_aliases("31P"))
        self.assertIn("Glucose", N.metabolite_aliases("2H"))
        # ...and not proton's.
        self.assertNotIn("NAA", N.metabolite_aliases("31P"))

    def test_returns_a_copy(self):
        table = N.metabolite_aliases("1H")
        table["NAA"] = ["nonsense"]
        self.assertEqual(N.metabolite_aliases("1H")["NAA"], ["NAA", "NAANAAG"])


class AvailableNucleiTests(unittest.TestCase):
    def test_lists_canonical_names_sorted(self):
        self.assertEqual(N.available_nuclei(), ["1H", "2H", "31P"])

    def test_legacy_defaults_module_still_exposes_the_proton_tables(self):
        # config/defaults.py keeps these names for backwards compatibility.
        from mrsiprep.config.defaults import METABOLITE_ALIASES, QUALITY_DEFAULTS

        self.assertEqual(QUALITY_DEFAULTS, N.quality_defaults("1H"))
        self.assertEqual(METABOLITE_ALIASES, N.metabolite_aliases("1H"))


if __name__ == "__main__":
    unittest.main()
