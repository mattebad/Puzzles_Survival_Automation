# Native fixture footprint review

Reviewed the added `tests/fixtures/` files between base
`67ef48c495f4786ce2243891a8b4728e43b95468` and branch snapshot
`d15cdc550a5b051b5a2527dd190dfb77074dbe95`.

- 151 files: 109 PNGs, 41 JSON records and one provenance text file.
- 150,636,351 bytes in the checkout; 149 distinct byte payloads.
- Largest file: `personal_might/native-more-menu-20261029.png`, 2,360,085 bytes.
- Two identical image pairs account for 4,269,781 repeated checkout bytes.
  Git stores each identical pair as one blob; removing a pathname would not
  reclaim those bytes from the published history.

The identical pairs are `campaign_home_entry/canonical-home-20261029.png`
and `home_base/native-home-zoom-settled-20261029.png`, and
`home_base/native-home-return-20261028.png` and
`home_nav/home-return-20261028-b.png`. Native bytes were not recompressed,
cropped or rewritten for this review.

Consumer review found five enhancement images loaded through
`enhancement_material_label_crop/provenance.json` by the material-label and
positive-recovery regressions. Their filenames need not appear in Python
source. The `home_nav` directory is different: only
`campaign-20261028-a.png` has a current test consumer, in
`tests/test_service_supply.py`. Its eight companion images have no current
test consumer found by source/manifest search. They remain historical native
captures, not additional test coverage. All other added PNG names have test
references; a reference alone does not establish that every fixture ran in CI.

The fixture addition is substantial. This review preserves the source captures
and published history rather than presenting their deletion as a test repair.
Future fixture additions should identify their consumer and avoid copying
whole navigation sequences when only one frame is exercised. No Git LFS
migration or history rewrite was performed.
