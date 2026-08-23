"""T1w-to-template registration.

Covers the backend fork, the cached-transform short circuit, and the
longitudinal composition -- including the ordering of the composed forward
list, which is silent if wrong: the maps still resample, just through the
wrong chain.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.registration.t1_to_mni import (
    T1ToMNIResult,
    compose_longitudinal_t1_to_mni,
    run_t1_to_mni,
)

MODULE = "mrsiprep.registration.t1_to_mni"


def _config(**overrides):
    base = dict(
        derivative_dir=Path("/tmp/derivatives"),
        registration_backend="ants",
        normalization="simple",
        overwrite=False,
        overwrite_template_reg=False,
        ants_t1_to_template_transform="s",
        fsl_t1_to_template_dof=12,
        fsl_cost="corratio",
        nthreads=4,
        verbose=1,
    )
    base.update(overrides)
    config = SimpleNamespace(**base)
    config.resolution_for = MagicMock(return_value=2)
    return config


class RunT1ToMniTests(unittest.TestCase):
    def _patches(self, all_exist_value=False):
        return (
            patch(f"{MODULE}.register"),
            patch(f"{MODULE}.register_flirt"),
            patch(f"{MODULE}.all_exist", return_value=all_exist_value),
            patch(f"{MODULE}.transform_paths", return_value=[Path("/x/xfm.mat")]),
            patch(f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")),
            patch(f"{MODULE}.template_t1w", return_value="TEMPLATE"),
        )

    def test_ants_backend_registers_t1_onto_the_template(self):
        ants, flirt, exists, paths, prefix, tpl = self._patches()
        with ants as ants_mock, flirt as flirt_mock, exists, paths, prefix, tpl:
            result = run_t1_to_mni(_config(), "S001", "V1", Path("/x/t1.nii.gz"))

        ants_mock.assert_called_once()
        flirt_mock.assert_not_called()
        # The template is the fixed image; the subject's T1w moves onto it.
        self.assertEqual(ants_mock.call_args.args[0], "TEMPLATE")
        self.assertEqual(ants_mock.call_args.args[1], Path("/x/t1.nii.gz"))
        self.assertEqual(ants_mock.call_args.kwargs["transform"], "s")
        self.assertIsInstance(result, T1ToMNIResult)

    def test_fsl_backend_uses_flirt_with_its_dof_and_cost(self):
        ants, flirt, exists, paths, prefix, tpl = self._patches()
        with ants as ants_mock, flirt as flirt_mock, exists, paths, prefix, tpl:
            run_t1_to_mni(_config(registration_backend="fsl"), "S001", "V1", Path("/x/t1.nii.gz"))

        flirt_mock.assert_called_once()
        ants_mock.assert_not_called()
        self.assertEqual(flirt_mock.call_args.kwargs["flirt_dof"], 12)
        self.assertEqual(flirt_mock.call_args.kwargs["flirt_cost"], "corratio")

    def test_resolution_prefers_t1w_over_the_mrsi_grid(self):
        # The registration target should not inherit the MRSI resolution.
        ants, flirt, exists, paths, prefix, tpl = self._patches()
        with ants, flirt, exists, paths, prefix, tpl as tpl_mock:
            config = _config()
            run_t1_to_mni(config, "S001", "V1", Path("/x/t1.nii.gz"), Path("/x/ref.nii.gz"))

        self.assertTrue(config.resolution_for.call_args.kwargs["prefer_t1w"])
        tpl_mock.assert_called_once_with(2)

    def test_existing_transforms_short_circuit_registration(self):
        ants, flirt, exists, paths, prefix, tpl = self._patches(all_exist_value=True)
        with ants as ants_mock, flirt, exists, paths, prefix, tpl:
            result = run_t1_to_mni(_config(), "S001", "V1", Path("/x/t1.nii.gz"))

        ants_mock.assert_not_called()
        self.assertEqual(result.template, "TEMPLATE")

    def test_overwrite_flags_force_reregistration(self):
        for flag in ("overwrite", "overwrite_template_reg"):
            ants, flirt, exists, paths, prefix, tpl = self._patches(all_exist_value=True)
            with ants as ants_mock, flirt, exists, paths, prefix, tpl:
                run_t1_to_mni(_config(**{flag: True}), "S001", "V1", Path("/x/t1.nii.gz"))
            ants_mock.assert_called_once_with(
                "TEMPLATE", Path("/x/t1.nii.gz"), Path("/x/prefix"),
                transform="s", verbose=False, threads=4,
            )

    def test_normalization_existing_without_transforms_raises(self):
        # --normalization existing promises to reuse transforms; if they are
        # absent it must say so rather than quietly registering anew.
        ants, flirt, exists, paths, prefix, tpl = self._patches(all_exist_value=False)
        with ants as ants_mock, flirt, exists, paths, prefix, tpl:
            with self.assertRaisesRegex(FileNotFoundError, "--normalization existing requires"):
                run_t1_to_mni(_config(normalization="existing"), "S001", "V1", Path("/x/t1.nii.gz"))
        ants_mock.assert_not_called()

    def test_error_names_the_backend_specific_transform_files(self):
        for backend, expected in (("fsl", ".flirt.mat"), ("ants", ".syn.nii.gz")):
            ants, flirt, exists, paths, prefix, tpl = self._patches(all_exist_value=False)
            with ants, flirt, exists, paths, prefix, tpl:
                with self.assertRaises(FileNotFoundError) as ctx:
                    run_t1_to_mni(
                        _config(normalization="existing", registration_backend=backend),
                        "S001", "V1", Path("/x/t1.nii.gz"),
                    )
            self.assertIn(expected, str(ctx.exception), msg=backend)


class ComposeLongitudinalTests(unittest.TestCase):
    def _template_result(self, session_forward=None):
        return SimpleNamespace(
            per_session_forward={"V1": session_forward if session_forward is not None else [Path("/x/s2t.mat")]},
            template_to_mni_forward=[Path("/x/t2m.mat")],
            template_to_mni_inverse=[Path("/x/m2t.mat")],
        )

    def test_forward_list_is_session_to_template_then_template_to_mni(self):
        # Order matters and is silent if wrong: the maps still resample, just
        # through the wrong chain.
        with patch(f"{MODULE}.all_exist", return_value=True), patch(
            f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")
        ), patch(f"{MODULE}.template_t1w", return_value="TEMPLATE"):
            result = compose_longitudinal_t1_to_mni(
                _config(), "S001", "V1", self._template_result(), Path("/x/t1.nii.gz")
            )

        self.assertEqual(result.forward, [Path("/x/s2t.mat"), Path("/x/t2m.mat")])
        self.assertEqual(result.inverse, [Path("/x/m2t.mat")])

    def test_missing_session_transform_raises_naming_the_recording(self):
        with patch(f"{MODULE}.all_exist", return_value=True), patch(
            f"{MODULE}.template_t1w", return_value="TEMPLATE"
        ):
            with self.assertRaisesRegex(FileNotFoundError, "sub-S001 ses-V2"):
                compose_longitudinal_t1_to_mni(
                    _config(), "S001", "V2", self._template_result(), Path("/x/t1.nii.gz")
                )

    def test_present_but_incomplete_session_transform_also_raises(self):
        with patch(f"{MODULE}.all_exist", return_value=False), patch(
            f"{MODULE}.template_t1w", return_value="TEMPLATE"
        ):
            with self.assertRaises(FileNotFoundError):
                compose_longitudinal_t1_to_mni(
                    _config(), "S001", "V1", self._template_result(), Path("/x/t1.nii.gz")
                )

    def test_resolution_matches_the_shared_template_build(self):
        # Must agree with build_subject_template()'s own choice: the template
        # spans sessions at possibly different MRSI resolutions, so origres has
        # no single answer for the shared template-to-MNI stage.
        with patch(f"{MODULE}.all_exist", return_value=True), patch(
            f"{MODULE}.ants_transform_prefix", return_value=Path("/x/prefix")
        ), patch(f"{MODULE}.template_t1w", return_value="TEMPLATE"):
            config = _config()
            compose_longitudinal_t1_to_mni(
                config, "S001", "V1", self._template_result(), Path("/x/t1.nii.gz"), Path("/x/ref.nii.gz")
            )

        self.assertTrue(config.resolution_for.call_args.kwargs["prefer_t1w"])


if __name__ == "__main__":
    unittest.main()
