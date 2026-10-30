import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.io.mrsinmrs import load_mrsinmrs, resolve_mrsinmrs


class MRSinMRSTests(unittest.TestCase):
    def _metadata_path(self, root):
        path = Path(root) / "derivatives" / "mrsi-orig" / "mrsinmrs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_load_reads_metadata_at_mrsi_input_root(self):
        with tempfile.TemporaryDirectory() as td:
            data = {"CommonMetadata": {"Nucleus": "1H", "RepetitionTime": 0.45}}
            self._metadata_path(td).write_text(json.dumps(data))
            self.assertEqual(load_mrsinmrs(td), data)

    def test_legacy_dataset_root_is_not_an_automatic_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            data = {"CommonMetadata": {"Nucleus": "1H"}}
            (Path(td) / "mrsinmrs.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(FileNotFoundError, "--mrsinmrs-file"):
                load_mrsinmrs(td)

    def test_explicit_path_overrides_default_location(self):
        with tempfile.TemporaryDirectory() as td:
            default = {"CommonMetadata": {"Nucleus": "1H"}}
            custom = {"CommonMetadata": {"Nucleus": "31P"}}
            self._metadata_path(td).write_text(json.dumps(default))
            selected = Path(td) / "custom acquisition.json"
            selected.write_text(json.dumps(custom))
            self.assertEqual(load_mrsinmrs(td, selected), custom)

    def test_missing_explicit_file_does_not_use_valid_default(self):
        with tempfile.TemporaryDirectory() as td:
            self._metadata_path(td).write_text(json.dumps({"CommonMetadata": {"Nucleus": "1H"}}))
            with self.assertRaisesRegex(FileNotFoundError, "absent.json"):
                load_mrsinmrs(td, Path(td) / "absent.json")

    def test_rejects_empty_metadata_and_invalid_containers(self):
        for data in ({}, {"CommonMetadata": {}}, {"CommonMetadata": []}, {"Recordings": ["invalid"]}):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as td:
                self._metadata_path(td).write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_mrsinmrs(td)

    def test_mrsi_input_metadata_takes_precedence_over_legacy_file(self):
        with tempfile.TemporaryDirectory() as td:
            data = {"CommonMetadata": {"Nucleus": "31P"}}
            self._metadata_path(td).write_text(json.dumps(data))
            (Path(td) / "mrsinmrs.json").write_text("{malformed legacy data")
            self.assertEqual(load_mrsinmrs(td), data)

    def test_invalid_preferred_metadata_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as td:
            self._metadata_path(td).write_text("{malformed preferred data")
            (Path(td) / "mrsinmrs.json").write_text(json.dumps({"CommonMetadata": {"Nucleus": "1H"}}))
            with self.assertRaisesRegex(ValueError, "derivatives/mrsi-orig/mrsinmrs.json"):
                load_mrsinmrs(td)

    def test_load_mrsinmrs_fails_when_file_absent(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(FileNotFoundError, "derivatives/mrsi-orig"):
                load_mrsinmrs(td)

    def test_optional_library_probe_returns_none_when_file_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(load_mrsinmrs(td, required=False))

    def test_load_mrsinmrs_raises_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            self._metadata_path(td).write_text("{not valid json")
            with self.assertRaises(ValueError):
                load_mrsinmrs(td)

    def test_load_mrsinmrs_rejects_unsupported_top_level_keys(self):
        with tempfile.TemporaryDirectory() as td:
            self._metadata_path(td).write_text(json.dumps({"Unsupported": {}}))
            with self.assertRaises(ValueError):
                load_mrsinmrs(td)

    def test_resolve_mrsinmrs_merges_common_and_recording_override(self):
        parsed = {
            "CommonMetadata": {"FieldStrength_T": 3, "Sequence": "ECCENTRIC"},
            "Recordings": [
                {"sub": "01", "ses": "01"},
                {"sub": "02", "ses": "01", "FieldStrength_T": 7},
            ],
        }
        resolved_default = resolve_mrsinmrs(parsed, "01", "01")
        self.assertEqual(resolved_default["FieldStrength_T"], 3)
        self.assertEqual(resolved_default["Sequence"], "ECCENTRIC")

        resolved_override = resolve_mrsinmrs(parsed, "02", "01")
        self.assertEqual(resolved_override["FieldStrength_T"], 7)
        self.assertEqual(resolved_override["Sequence"], "ECCENTRIC")

    def test_resolve_mrsinmrs_subject_only_entry_applies_to_all_sessions(self):
        parsed = {
            "CommonMetadata": {"FieldStrength_T": 3},
            "Recordings": [{"sub": "01", "TR_ms": 457}],
        }
        resolved = resolve_mrsinmrs(parsed, "01", "02")
        self.assertEqual(resolved["TR_ms"], 457)

    def test_resolve_mrsinmrs_handles_sub_ses_prefixes(self):
        parsed = {"CommonMetadata": {}, "Recordings": [{"sub": "sub-01", "ses": "ses-01", "TR_ms": 400}]}
        resolved = resolve_mrsinmrs(parsed, "01", "01")
        self.assertEqual(resolved["TR_ms"], 400)

    def test_resolve_mrsinmrs_returns_none_when_parsed_is_none(self):
        self.assertIsNone(resolve_mrsinmrs(None, "01", "01"))

    def test_resolve_mrsinmrs_returns_none_when_no_data_applies(self):
        parsed = {"CommonMetadata": {}, "Recordings": []}
        self.assertIsNone(resolve_mrsinmrs(parsed, "01", "01"))


class RequiredMetadataCLITests(unittest.TestCase):
    def _args(self, root):
        return [str(root), str(root / "output"), "participant", "--metabolites", "CrPCr", "--ref-met", "CrPCr"]

    def test_processing_validation_and_reports_require_metadata(self):
        from mrsiprep.cli.parser import parse_args

        for flags in ([], ["--validate-only"], ["--reports-only"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with self.assertRaisesRegex(FileNotFoundError, "--mrsinmrs-file"):
                    parse_args(self._args(root) + flags)
                self.assertFalse((root / "output").exists())

    def test_default_location_is_loaded_and_recorded(self):
        from mrsiprep.cli.parser import parse_args

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "derivatives" / "mrsi-orig" / "mrsinmrs.json"
            path.parent.mkdir(parents=True)
            data = {"CommonMetadata": {"Nucleus": "1H", "SequenceName": "DefaultProtocol", "QuantificationTool": "lcmodel", "LinewidthUnit": "Hz", "CRLBUnit": "percent"}}
            path.write_text(json.dumps(data))
            config = parse_args(self._args(root))
            self.assertEqual(config.mrsinmrs, data)
            self.assertEqual(config.mrsinmrs_file, path.resolve())

    def test_custom_metadata_is_used_by_configuration_and_report(self):
        from mrsiprep.cli.parser import parse_args
        from mrsiprep.reports.html import _mrsinmrs_html

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "old dataset metadata.json"
            path.write_text(json.dumps({"CommonMetadata": {"Nucleus": "31P", "SequenceName": "CustomProtocol", "QuantificationTool": "custom", "LinewidthUnit": "Hz", "CRLBUnit": "percent"}}))
            config = parse_args(self._args(root) + [
                "--mrsinmrs-file", str(path), "--snr-min", "2", "--linewidth-max", "0.3", "--crlb-max", "50",
            ])
            self.assertEqual(config.nucleus, "31P")
            self.assertEqual(config.mrsinmrs_file, path.resolve())
            self.assertIn("CustomProtocol", _mrsinmrs_html(config, "01", "01"))

    def test_cli_reports_missing_file_without_starting_processing(self):
        from mrsiprep.cli.run import main

        with tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
            with patch("mrsiprep.cli.run.run_participant_workflow") as workflow:
                code = main(self._args(Path(td)))
                self.assertEqual(code, 2)
                workflow.assert_not_called()
            self.assertIn("Required MRSinMRS", error.getvalue())
            self.assertIn("--mrsinmrs-file", error.getvalue())

    def test_library_workflow_rejects_missing_metadata_before_writing(self):
        from mrsiprep.config.settings import MRSIPrepConfig
        from mrsiprep.workflows.participant import run_participant_workflow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = MRSIPrepConfig(root, root / "out", "participant", metabolites=["CrPCr"], ref_met="CrPCr")
            with patch("mrsiprep.workflows.participant.ensure_work_dirs") as create_dirs:
                with self.assertRaises(FileNotFoundError):
                    run_participant_workflow(config)
                create_dirs.assert_not_called()


class MetadataDockerWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from importlib import import_module

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wrapper" / "src"))
        try:
            cls.wrapper = import_module("mrsiprep_docker.__main__")
        finally:
            sys.path.pop(0)

    def test_custom_host_file_is_mounted_read_only_and_forwarded(self):
        wrapper = self.wrapper
        with tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()):
            root = Path(td)
            metadata = root / "custom metadata.json"
            metadata.write_text(json.dumps({"CommonMetadata": {"Nucleus": "1H"}}))
            argv = ["mrsiprep-docker", str(root / "bids"), str(root / "out"), "participant", "--mrsinmrs-file", str(metadata)]
            with patch.object(sys, "argv", argv), patch.object(wrapper, "check_docker", return_value=1), patch.object(wrapper, "check_image", return_value=True):
                with patch.object(wrapper.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                    self.assertEqual(wrapper.main(), 0)
            command = run.call_args.args[0]
            self.assertIn(f"{metadata}:/tmp/mrsinmrs.json:ro", command)
            self.assertEqual(command[command.index("--mrsinmrs-file") + 1], "/tmp/mrsinmrs.json")

    def test_missing_custom_file_fails_before_docker_is_used(self):
        wrapper = self.wrapper
        with tempfile.TemporaryDirectory() as td, redirect_stderr(io.StringIO()) as error:
            argv = ["mrsiprep-docker", td, str(Path(td) / "out"), "participant", "--mrsinmrs-file", str(Path(td) / "absent.json")]
            with patch.object(sys, "argv", argv), patch.object(wrapper, "check_docker") as check:
                self.assertEqual(wrapper.main(), 2)
                check.assert_not_called()
            self.assertIn("--mrsinmrs-file", error.getvalue())


if __name__ == "__main__":
    unittest.main()
