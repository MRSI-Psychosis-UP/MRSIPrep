"""Tests for registration/subject_template.py's build_subject_template --
previously entirely untested. Real antsMultivariateTemplateConstruction2.sh/
antsRegistrationSyN.sh calls are mocked out via run_cli, with a side_effect
that fabricates the output files those tools are documented (see the
source's own comments) to produce, at whatever prefix the real command
actually requested -- so mrsiprep's own path-reconstruction logic
(input{NNNN}-{stem}- naming, etc.) is what's actually being exercised.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.registration.subject_template import build_subject_template
from mrsiprep.registration.transforms import ants_transform_prefix, transform_paths


class BuildSubjectTemplateFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(
            derivative_dir=self.tmp / "derivatives",
            overwrite_mni_reg=False,
            overwrite=False,
            verbose=0,
            nthreads=2,
            mni_resolution="t1wres",
        )
        self.session_t1_paths = {}
        for session in ("01", "02"):
            t1 = self.tmp / f"ses-{session}_T1w.nii.gz"
            t1.write_bytes(b"fake-t1-data")
            self.session_t1_paths[session] = t1

    def tearDown(self):
        self._tmpdir.cleanup()

    def _expected_paths(self, subject="01"):
        template_prefix = ants_transform_prefix(self.config.derivative_dir, subject, "01", "t1-template").parent
        template_path = template_prefix / f"sub-{subject}_ses-all_desc-template_T1w.nii.gz"
        mni_forward = transform_paths(ants_transform_prefix(self.config.derivative_dir, subject, None, "template-mni"), "forward")
        mni_inverse = transform_paths(ants_transform_prefix(self.config.derivative_dir, subject, None, "template-mni"), "inverse")
        per_session_forward = {
            session: transform_paths(ants_transform_prefix(self.config.derivative_dir, subject, session, "t1-template"), "forward")
            for session in ("01", "02")
        }
        return template_path, mni_forward, mni_inverse, per_session_forward

    def _touch_all_cached_outputs(self):
        template_path, mni_forward, mni_inverse, per_session_forward = self._expected_paths()
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.touch()
        for path in mni_forward:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        for paths in per_session_forward.values():
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        return template_path, mni_forward, mni_inverse, per_session_forward


class BuildSubjectTemplateTooFewSessionsTests(unittest.TestCase):
    def test_returns_none_for_zero_sessions(self):
        self.assertIsNone(build_subject_template(SimpleNamespace(), "01", {}))

    def test_returns_none_for_a_single_session(self):
        self.assertIsNone(build_subject_template(SimpleNamespace(), "01", {"01": Path("t1.nii.gz")}))


class BuildSubjectTemplateCacheHitTests(BuildSubjectTemplateFixture):
    def test_reuses_existing_template_without_rebuilding(self):
        template_path, mni_forward, mni_inverse, per_session_forward = self._touch_all_cached_outputs()

        with patch("mrsiprep.registration.subject_template.require_cli") as require_cli_mock, patch(
            "mrsiprep.registration.subject_template.run_cli"
        ) as run_cli_mock:
            result = build_subject_template(self.config, "01", self.session_t1_paths)

        require_cli_mock.assert_not_called()
        run_cli_mock.assert_not_called()
        self.assertEqual(result.template_path, template_path)
        self.assertEqual(result.template_to_mni_forward, mni_forward)
        self.assertEqual(result.template_to_mni_inverse, mni_inverse)
        self.assertEqual(result.per_session_forward, per_session_forward)

    def test_overwrite_flag_forces_rebuild_even_when_cached(self):
        self._touch_all_cached_outputs()
        self.config.overwrite = True

        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli"
        ) as run_cli_mock:
            with self.assertRaises(FileNotFoundError):
                # run_cli is a no-op mock here, so the real build can't
                # actually complete -- reaching this error proves the cache
                # check was bypassed and a real build was attempted.
                build_subject_template(self.config, "01", self.session_t1_paths)

        run_cli_mock.assert_called_once()

    def test_overwrite_mni_reg_flag_also_forces_rebuild(self):
        self._touch_all_cached_outputs()
        self.config.overwrite_mni_reg = True

        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli"
        ) as run_cli_mock:
            with self.assertRaises(FileNotFoundError):
                build_subject_template(self.config, "01", self.session_t1_paths)

        run_cli_mock.assert_called_once()


class BuildSubjectTemplateErrorTests(BuildSubjectTemplateFixture):
    def test_raises_when_template_construction_produces_no_output(self):
        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli"
        ):
            with self.assertRaisesRegex(FileNotFoundError, "did not produce"):
                build_subject_template(self.config, "01", self.session_t1_paths)

    def test_raises_when_a_sessions_transform_is_missing(self):
        def _partial_run_cli(cmd, **_kwargs):
            out_idx = cmd.index("-o")
            out_prefix = Path(cmd[out_idx + 1])
            if cmd[0] == "antsMultivariateTemplateConstruction2.sh":
                out_prefix.with_name(out_prefix.name + "template0.nii.gz").touch()
                # Deliberately produce no per-session input{NNNN}-...- files.

        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli", side_effect=_partial_run_cli
        ):
            with self.assertRaisesRegex(FileNotFoundError, "did not produce expected transforms for session"):
                build_subject_template(self.config, "01", self.session_t1_paths)


class BuildSubjectTemplateFullBuildTests(BuildSubjectTemplateFixture):
    @staticmethod
    def _fake_run_cli(cmd, **_kwargs):
        out_idx = cmd.index("-o")
        out_prefix = Path(cmd[out_idx + 1])
        if cmd[0] == "antsMultivariateTemplateConstruction2.sh":
            session_inputs = [Path(p) for p in cmd[out_idx + 2 :]]
            for index, session_input in enumerate(session_inputs):
                input_stem = session_input.name
                for suffix in (".nii.gz", ".nii"):
                    if input_stem.endswith(suffix):
                        input_stem = input_stem[: -len(suffix)]
                        break
                warp_prefix = out_prefix.with_name(out_prefix.name + f"input{index:04d}-{input_stem}-")
                warp_prefix.with_name(warp_prefix.name + "0GenericAffine.mat").touch()
                warp_prefix.with_name(warp_prefix.name + "1Warp.nii.gz").touch()
            out_prefix.with_name(out_prefix.name + "template0.nii.gz").write_bytes(b"fake-template")
        elif cmd[0] == "antsRegistrationSyN.sh":
            out_prefix.with_name(out_prefix.name + "1Warp.nii.gz").touch()
            out_prefix.with_name(out_prefix.name + "0GenericAffine.mat").touch()
            out_prefix.with_name(out_prefix.name + "1InverseWarp.nii.gz").touch()

    def test_builds_template_and_registers_to_mni(self):
        mni_template_mock = MagicMock()
        with patch("mrsiprep.registration.subject_template.require_cli") as require_cli_mock, patch(
            "mrsiprep.registration.subject_template.run_cli", side_effect=self._fake_run_cli
        ) as run_cli_mock, patch(
            "mrsiprep.registration.subject_template.resolve_mni_resolution", return_value=2
        ) as resolve_mock, patch(
            "nilearn.datasets.load_mni152_template", return_value=mni_template_mock
        ) as load_template_mock:
            result = build_subject_template(self.config, "01", self.session_t1_paths)

        self.assertEqual(require_cli_mock.call_count, 2)
        self.assertEqual(run_cli_mock.call_count, 2)
        resolve_mock.assert_called_once()
        self.assertEqual(resolve_mock.call_args[0][0], "t1wres")
        load_template_mock.assert_called_once_with(2)
        mni_template_mock.to_filename.assert_called_once()

        template_path, mni_forward, mni_inverse, per_session_forward = self._expected_paths()
        self.assertEqual(result.template_path, template_path)
        self.assertTrue(template_path.exists())
        self.assertEqual(result.template_to_mni_forward, mni_forward)
        self.assertEqual(result.template_to_mni_inverse, mni_inverse)
        for path in mni_forward + mni_inverse:
            self.assertTrue(path.exists())
        self.assertEqual(result.per_session_forward, per_session_forward)
        for paths in per_session_forward.values():
            for path in paths:
                self.assertTrue(path.exists())

    def test_origres_mni_resolution_choice_falls_back_to_t1wres_for_the_template(self):
        """The unbiased template spans multiple sessions at possibly
        different native MRSI resolutions, so 'origres' has no single
        well-defined answer -- falls back to the template's own resolution."""
        self.config.mni_resolution = "origres"
        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli", side_effect=self._fake_run_cli
        ), patch("mrsiprep.registration.subject_template.resolve_mni_resolution", return_value=2) as resolve_mock, patch(
            "nilearn.datasets.load_mni152_template", return_value=MagicMock()
        ):
            build_subject_template(self.config, "01", self.session_t1_paths)
        self.assertEqual(resolve_mock.call_args[0][0], "t1wres")

    def test_explicit_mm_resolution_choice_is_honored_verbatim(self):
        self.config.mni_resolution = "2mm"
        with patch("mrsiprep.registration.subject_template.require_cli"), patch(
            "mrsiprep.registration.subject_template.run_cli", side_effect=self._fake_run_cli
        ), patch("mrsiprep.registration.subject_template.resolve_mni_resolution", return_value=2) as resolve_mock, patch(
            "nilearn.datasets.load_mni152_template", return_value=MagicMock()
        ):
            build_subject_template(self.config, "01", self.session_t1_paths)
        self.assertEqual(resolve_mock.call_args[0][0], "2mm")


if __name__ == "__main__":
    unittest.main()
