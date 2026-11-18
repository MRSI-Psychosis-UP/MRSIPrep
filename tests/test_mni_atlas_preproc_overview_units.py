import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.parcellation.mni_atlas import run_mni_parcellation
from mrsiprep.reports.preproc_overview import _PARAM_ROWS, _STEP_LABELS, build_preproc_overview_sections

MODULE = "mrsiprep.parcellation.mni_atlas"


def _config(root: Path, **overrides):
    base = dict(
        derivative_dir=root / "derivatives",
        work_dir=root / "work",
        overwrite=False,
        nthreads=4,
    )
    base.setdefault("atlas", "schaefer400")
    base.update(overrides)
    config = SimpleNamespace(**base)
    config.atlases = lambda: [item.strip() for item in str(config.atlas).split(",") if item.strip()]
    return config


def _touch(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _fake_apply(*args, **_kwargs):
    return _touch(args[3])


class RunMniParcellationTests(unittest.TestCase):
    def _patches(self, root, atlas_name="schaefer400"):
        atlas_path = _touch(root / "atlas.nii.gz")
        labels_path = _touch(root / "atlas.tsv")
        return (
            patch(f"{MODULE}.load_mni_atlas", return_value=(atlas_path, labels_path, atlas_name)),
            patch(f"{MODULE}.apply_image_transform", side_effect=_fake_apply),
            patch(f"{MODULE}.copy_labels", side_effect=lambda src, dst: _touch(dst)),
        )

    def test_atlas_is_warped_mni_to_t1w_then_t1w_to_mrsi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            load_p, apply_p, copy_p = self._patches(root)

            with load_p, apply_p as apply_mock, copy_p:
                results = run_mni_parcellation(
                    _config(root), "S001", "V1", "MRSI_REF", "T1_REF", ["MNI2T1"], ["T12MRSI"]
                )

            first, second = apply_mock.call_args_list
            # Step 1: atlas (MNI) -> T1w, using the MNI->T1w transform.
            self.assertEqual(first.args[0], "T1_REF")
            self.assertEqual(first.args[2], ["MNI2T1"])
            # Step 2: the T1w result -> MRSI, chained off step 1's output.
            self.assertEqual(second.args[0], "MRSI_REF")
            self.assertEqual(second.args[1], results[0].atlas_t1)
            self.assertEqual(second.args[2], ["T12MRSI"])

    def test_both_warps_use_nearest_label_interpolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            load_p, apply_p, copy_p = self._patches(root)

            with load_p, apply_p as apply_mock, copy_p:
                run_mni_parcellation(_config(root), "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            for call in apply_mock.call_args_list:
                self.assertEqual(call.kwargs["interpolation"], "genericLabel")

    def test_nthreads_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            load_p, apply_p, copy_p = self._patches(root)

            with load_p, apply_p as apply_mock, copy_p:
                run_mni_parcellation(_config(root, nthreads=11), "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            for call in apply_mock.call_args_list:
                self.assertEqual(call.kwargs["threads"], 11)

    def test_result_records_atlas_mode_and_all_three_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            load_p, apply_p, copy_p = self._patches(root, atlas_name="mist197")

            with load_p, apply_p, copy_p:
                results = run_mni_parcellation(_config(root), "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            self.assertEqual(results[0].mode, "atlas")
            self.assertEqual(results[0].atlas_name, "mist197")
            self.assertTrue(results[0].atlas_mni.exists())
            self.assertTrue(results[0].atlas_t1.exists())
            self.assertTrue(results[0].atlas_mrsi.exists())
            self.assertTrue(results[0].labels.exists())

    def test_atlas_is_fetched_into_the_work_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            load_p, apply_p, copy_p = self._patches(root)

            with load_p as load_mock, apply_p, copy_p:
                config = _config(root)
                run_mni_parcellation(config, "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            self.assertEqual(load_mock.call_args.args[1], config.work_dir / "atlases")

    def test_existing_outputs_are_reused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root)

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p, copy_p:
                run_mni_parcellation(config, "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p as apply_mock, copy_p:
                run_mni_parcellation(config, "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            apply_mock.assert_not_called()

    def test_overwrite_regenerates_both_warps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p, copy_p:
                run_mni_parcellation(_config(root), "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p as apply_mock, copy_p:
                run_mni_parcellation(
                    _config(root, overwrite=True), "S001", "V1", "MRSI_REF", "T1_REF", [], []
                )

            self.assertEqual(apply_mock.call_count, 2)

    def test_labels_are_copied_every_run_even_when_warps_are_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _config(root)

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p, copy_p:
                run_mni_parcellation(config, "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            load_p, apply_p, copy_p = self._patches(root)
            with load_p, apply_p, copy_p as copy_mock:
                run_mni_parcellation(config, "S001", "V1", "MRSI_REF", "T1_REF", [], [])

            copy_mock.assert_called_once()

    def test_comma_separated_atlases_each_produce_their_own_parcellation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas_path = _touch(root / "atlas.nii.gz")
            labels_path = _touch(root / "atlas.tsv")

            def fake_load(_config, _work_dir, name=None):
                return atlas_path, labels_path, name

            with patch(f"{MODULE}.load_mni_atlas", side_effect=fake_load) as load_mock, patch(
                f"{MODULE}.apply_image_transform", side_effect=_fake_apply
            ), patch(f"{MODULE}.copy_labels", side_effect=lambda src, dst: _touch(dst)):
                results = run_mni_parcellation(
                    _config(root, atlas="schaefer400,mist197"), "S001", "V1", "MRSI_REF", "T1_REF", [], []
                )

            self.assertEqual([r.atlas_name for r in results], ["schaefer400", "mist197"])
            # Each atlas resolves independently rather than reusing config.atlas.
            self.assertEqual([call.args[2] for call in load_mock.call_args_list], ["schaefer400", "mist197"])
            self.assertEqual(len({r.atlas_mrsi for r in results}), 2)


class BuildPreprocOverviewSectionsTests(unittest.TestCase):
    def _config(self, **overrides):
        base = dict(
            tissue_backend="synthseg-fast",
            registration_backend="ants",
            registration_t1_target="brain",
            normalization="simple",
            output_spaces=["MNI152NLin2009cAsym"],
            parcellation_mode="synthseg",
            atlas="chimera-LFMIHIFIS_scale3",
            snr_min=5.0,
            linewidth_max=0.1,
            crlb_max=20.0,
            filter_biharmonic=True,
            spike_percentile=99.0,
            no_pvc=False,
            t1_correction="none",
            write_connectivity=False,
            nproc=2,
            nthreads=8,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_returns_the_two_expected_sections(self):
        sections = build_preproc_overview_sections(self._config())
        self.assertEqual([heading for heading, _ in sections], ["Processing parameters", "Pipeline stages"])

    def test_every_declared_parameter_row_is_rendered(self):
        _, param_table = build_preproc_overview_sections(self._config())[0]
        for label, _attr, _formatter in _PARAM_ROWS:
            self.assertIn(label, param_table, msg=label)

    def test_parameter_values_come_from_the_config(self):
        _, param_table = build_preproc_overview_sections(
            self._config(parcellation_mode="chimera", tissue_backend="existing")
        )[0]
        self.assertIn("<td>chimera</td>", param_table)
        self.assertIn("<td>existing</td>", param_table)

    def test_output_spaces_are_joined(self):
        _, param_table = build_preproc_overview_sections(
            self._config(output_spaces=["MNI152NLin2009cAsym", "T1w"])
        )[0]
        self.assertIn("MNI152NLin2009cAsym, T1w", param_table)

    def test_empty_output_spaces_render_as_none(self):
        _, param_table = build_preproc_overview_sections(self._config(output_spaces=[]))[0]
        self.assertIn("<td>none</td>", param_table)

    def test_nproc_and_nthreads_are_combined_into_one_row(self):
        _, param_table = build_preproc_overview_sections(self._config(nproc=3, nthreads=12))[0]
        self.assertIn("3 x 12", param_table)

    def test_missing_config_attribute_renders_as_none_rather_than_raising(self):
        config = self._config()
        del config.atlas
        _, param_table = build_preproc_overview_sections(config)[0]
        self.assertIn("<td>None</td>", param_table)

    def test_parameter_table_has_one_row_per_parameter_plus_a_header(self):
        _, param_table = build_preproc_overview_sections(self._config())[0]
        self.assertEqual(param_table.count("<tr>"), len(_PARAM_ROWS) + 1)

    def test_pipeline_stage_diagram_lists_every_step_in_order(self):
        _, dag_html = build_preproc_overview_sections(self._config())[1]
        positions = [dag_html.index(label) for _name, label in _STEP_LABELS]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(dag_html.count("dag-node"), len(_STEP_LABELS))

    def test_stages_are_joined_with_arrows(self):
        _, dag_html = build_preproc_overview_sections(self._config())[1]
        self.assertEqual(dag_html.count("&rarr;"), len(_STEP_LABELS) - 1)

    def test_processing_mode_is_no_longer_reported(self):
        # --mode was removed; the table reports parcellation mode and tissue
        # backend independently instead.
        _, param_table = build_preproc_overview_sections(self._config())[0]
        self.assertNotIn("Processing mode", param_table)
        self.assertIn("Parcellation mode", param_table)
        self.assertIn("Tissue backend", param_table)


if __name__ == "__main__":
    unittest.main()
