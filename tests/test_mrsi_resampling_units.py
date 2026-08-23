import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.mrsi.resampling import resample_ref_met_to_t1w, transform_mrsi_maps


def _config(root: Path, **overrides):
    base = dict(
        derivative_dir=root / "derivatives",
        work_dir=root / "work",
        ref_met="CrPCr",
        nthreads=4,
        overwrite_transform=False,
        output_mrsi_t1w=False,
        output_spaces=["MNI152NLin2009cAsym"],
        transform="",
        transform_spikemask=False,
        mni_resolution="origres",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _fake_apply(*args, **_kwargs):
    """Stand-in for apply_image_transform: creates and returns the output path."""
    return _touch(args[3])


class ResampleRefMetToT1wTests(unittest.TestCase):
    def test_writes_under_work_dir_not_the_permanent_derivatives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root)

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                out = resample_ref_met_to_t1w(config, "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz")

            self.assertIn(str(config.work_dir), str(out))
            self.assertNotIn(str(config.derivative_dir), str(out))

    def test_uses_linear_interpolation_and_forwards_threads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
                resample_ref_met_to_t1w(
                    _config(root, nthreads=9), "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz"
                )

            self.assertEqual(apply_mock.call_args.kwargs["interpolation"], "linear")
            self.assertEqual(apply_mock.call_args.kwargs["threads"], 9)

    def test_transforms_and_fixed_image_are_passed_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transforms = [root / "a.mat", root / "b.nii.gz"]
            t1 = root / "t1.nii.gz"

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
                resample_ref_met_to_t1w(_config(root), "S001", "V1", root / "ref.nii.gz", transforms, t1)

            self.assertEqual(apply_mock.call_args.args[0], t1)
            self.assertEqual(apply_mock.call_args.args[2], transforms)

    def test_existing_output_is_reused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root)

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                first = resample_ref_met_to_t1w(config, "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz")

            with patch("mrsiprep.mrsi.resampling.apply_image_transform") as apply_mock:
                second = resample_ref_met_to_t1w(config, "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz")

            apply_mock.assert_not_called()
            self.assertEqual(first, second)

    def test_overwrite_transform_forces_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                resample_ref_met_to_t1w(_config(root), "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz")

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
                resample_ref_met_to_t1w(
                    _config(root, overwrite_transform=True), "S001", "V1", root / "ref.nii.gz", [], root / "t1.nii.gz"
                )

            apply_mock.assert_called_once()


class TransformMrsiMapsSpaceSelectionTests(unittest.TestCase):
    def _run(self, config, **kwargs):
        params = dict(
            maps={"CrPCr": Path("/x/cr.nii.gz")},
            mrsi_to_t1=[Path("/x/m2t.mat")],
            t1_to_mni=[Path("/x/t2m.mat")],
            t1_reference=Path("/x/t1.nii.gz"),
        )
        params.update(kwargs)
        with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply), patch(
            "mrsiprep.mrsi.resampling.template_t1w", return_value="TEMPLATE"
        ), patch("mrsiprep.mrsi.resampling.resolve_mni_resolution", return_value=2):
            return transform_mrsi_maps(config, "S001", "V1", **params)

    def test_t1w_space_is_opt_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertNotIn("T1w", self._run(_config(root)))
            self.assertIn("T1w", self._run(_config(root, output_mrsi_t1w=True)))

    def test_mni_space_is_produced_for_the_default_output_space(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIn("MNI152NLin2009cAsym", self._run(_config(Path(tmpdir))))

    def test_mni_space_is_skipped_when_not_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = self._run(_config(Path(tmpdir), output_spaces=["T1w"]))
            self.assertNotIn("MNI152NLin2009cAsym", outputs)

    def test_legacy_transform_string_also_triggers_mni_resampling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = self._run(_config(Path(tmpdir), output_spaces=["T1w"], transform="mni-nonlinear"))
            self.assertIn("MNI152NLin2009cAsym", outputs)

    def test_mni_is_skipped_without_a_t1_to_mni_transform(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for missing in (None, []):
                outputs = self._run(_config(Path(tmpdir)), t1_to_mni=missing)
                self.assertNotIn("MNI152NLin2009cAsym", outputs, msg=repr(missing))

    def test_mni_transform_chain_is_t1_to_mni_then_mrsi_to_t1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mrsi_to_t1 = [Path("/x/m2t.mat")]
            t1_to_mni = [Path("/x/t2m.mat")]

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock, patch(
                "mrsiprep.mrsi.resampling.template_t1w", return_value="TEMPLATE"
            ), patch("mrsiprep.mrsi.resampling.resolve_mni_resolution", return_value=2):
                transform_mrsi_maps(
                    _config(Path(tmpdir)), "S001", "V1",
                    maps={"CrPCr": Path("/x/cr.nii.gz")},
                    mrsi_to_t1=mrsi_to_t1, t1_to_mni=t1_to_mni, t1_reference=Path("/x/t1.nii.gz"),
                )

            self.assertEqual(apply_mock.call_args.args[2], t1_to_mni + mrsi_to_t1)

    def test_mni_resampling_targets_the_template_at_the_resolved_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock, patch(
                "mrsiprep.mrsi.resampling.template_t1w", return_value="TEMPLATE"
            ) as template_mock, patch("mrsiprep.mrsi.resampling.resolve_mni_resolution", return_value=3):
                transform_mrsi_maps(
                    _config(Path(tmpdir)), "S001", "V1",
                    maps={"CrPCr": Path("/x/cr.nii.gz")},
                    mrsi_to_t1=[], t1_to_mni=[Path("/x/t2m.mat")], t1_reference=Path("/x/t1.nii.gz"),
                )

            template_mock.assert_called_once_with(3)
            self.assertEqual(apply_mock.call_args.args[0], "TEMPLATE")


class TransformMrsiMapsContentTests(unittest.TestCase):
    def _run(self, config, **kwargs):
        params = dict(
            maps={"CrPCr": Path("/x/cr.nii.gz")},
            mrsi_to_t1=[],
            t1_to_mni=None,
            t1_reference=Path("/x/t1.nii.gz"),
        )
        params.update(kwargs)
        config.output_mrsi_t1w = True  # exercise a single, simple space
        config.output_spaces = ["T1w"]
        with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
            outputs = transform_mrsi_maps(config, "S001", "V1", **params)
        return outputs["T1w"], apply_mock

    def test_every_metabolite_map_is_resampled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            maps = {m: Path(f"/x/{m}.nii.gz") for m in ("CrPCr", "Ins", "NAA")}
            outputs, _ = self._run(_config(Path(tmpdir)), maps=maps)
            for met in maps:
                self.assertIn(met, outputs)

    def test_crlb_maps_are_keyed_per_metabolite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs, _ = self._run(
                _config(Path(tmpdir)),
                maps={"CrPCr": Path("/x/cr.nii.gz")},
                crlb_maps={"CrPCr": Path("/x/cr_crlb.nii.gz")},
            )
            self.assertIn("crlb-CrPCr", outputs)

    def test_crlb_for_a_metabolite_not_being_resampled_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs, _ = self._run(
                _config(Path(tmpdir)),
                maps={"CrPCr": Path("/x/cr.nii.gz")},
                crlb_maps={"Ins": Path("/x/ins_crlb.nii.gz")},
            )
            self.assertNotIn("crlb-Ins", outputs)

    def test_snr_and_linewidth_are_unkeyed_single_maps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs, _ = self._run(
                _config(Path(tmpdir)), snr_map=Path("/x/snr.nii.gz"), linewidth_map=Path("/x/lw.nii.gz")
            )
            self.assertIn("snr", outputs)
            self.assertIn("fwhm", outputs)

    def test_absent_snr_and_linewidth_produce_no_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs, _ = self._run(_config(Path(tmpdir)), snr_map=None, linewidth_map=None)
            self.assertNotIn("snr", outputs)
            self.assertNotIn("fwhm", outputs)

    def test_spikemask_is_only_included_when_enabled_and_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root, transform_spikemask=True)
            # No spike mask on disk -> nothing to carry forward.
            outputs, _ = self._run(config, maps={"CrPCr": Path("/x/cr.nii.gz")})
            self.assertNotIn("spikemask-CrPCr", outputs)

    def test_spikemask_uses_nearest_label_interpolation_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root, transform_spikemask=True, output_mrsi_t1w=True, output_spaces=["T1w"])
            from mrsiprep.io.naming import mrsi_derivative

            _touch(
                mrsi_derivative(
                    config.derivative_dir, "S001", "V1", space="MRSI", met="CrPCr",
                    desc="spikemask", suffix_override="mask",
                )
            )

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
                outputs = transform_mrsi_maps(
                    config, "S001", "V1", maps={"CrPCr": Path("/x/cr.nii.gz")},
                    mrsi_to_t1=[], t1_to_mni=None, t1_reference=Path("/x/t1.nii.gz"),
                )

            self.assertIn("spikemask-CrPCr", outputs["T1w"])
            interpolations = [c.kwargs["interpolation"] for c in apply_mock.call_args_list]
            self.assertIn("genericLabel", interpolations)
            # The signal map itself still resamples linearly.
            self.assertIn("linear", interpolations)

    def test_existing_outputs_are_reused_unless_overwrite_transform(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root, output_mrsi_t1w=True, output_spaces=["T1w"])
            params = dict(
                maps={"CrPCr": Path("/x/cr.nii.gz")}, mrsi_to_t1=[], t1_to_mni=None,
                t1_reference=Path("/x/t1.nii.gz"),
            )

            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                transform_mrsi_maps(config, "S001", "V1", **params)

            with patch("mrsiprep.mrsi.resampling.apply_image_transform") as apply_mock:
                transform_mrsi_maps(config, "S001", "V1", **params)
            apply_mock.assert_not_called()

            config.overwrite_transform = True
            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply) as apply_mock:
                transform_mrsi_maps(config, "S001", "V1", **params)
            apply_mock.assert_called_once()

    def test_no_requested_spaces_returns_an_empty_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(Path(tmpdir), output_mrsi_t1w=False, output_spaces=["T1w"])
            with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                outputs = transform_mrsi_maps(
                    config, "S001", "V1", maps={"CrPCr": Path("/x/cr.nii.gz")},
                    mrsi_to_t1=[], t1_to_mni=None, t1_reference=Path("/x/t1.nii.gz"),
                )
            self.assertEqual(outputs, {})


if __name__ == "__main__":
    unittest.main()
