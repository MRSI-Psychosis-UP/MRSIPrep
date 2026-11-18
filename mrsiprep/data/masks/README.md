# Bundled masks

- `mni_gm_mask.nii.gz`: binary gray-matter mask on MRSIPrep's own
  MNI152NLin2009cAsym 1mm grid, used by `mrsiprep.parcellation.cubic` to
  generate `--atlas cubic<N>mm` grid parcellations on demand. Derived from
  `mrsitoolbox`'s `cubic-10mm` reference atlas (binarized: a voxel is GM if
  it belongs to any cube), resampled onto MRSIPrep's actual MNI grid --
  templateflow's own `res-01_label-GM_probseg` is not fetched by the
  offline container image, so this mask is used instead of that
  probability map.
