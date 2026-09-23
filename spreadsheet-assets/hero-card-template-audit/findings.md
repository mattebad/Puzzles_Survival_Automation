# Forensic findings

## Confirmed

- 74 usable legacy Column F `IMAGE()` formulas pointed to `files.secure.website`; 74/74 original PNG files were retrieved. Each file has a distinct SHA-256. There were no failed source URLs.
- The Data workbook contains 74 joined rows for those cards. Color, Tier / Skill, Type, and workbook row values are in `manifest.json` alongside the raw HeroIcons formula and URL.
- Card canvases split into two native sizes: 71 cards are 485×321, and all three T9 examples (501 Celine, 510 Kajisha, 519 Gerald) are 485×402. The T9 cards have five right-grid rows; all other extracted cards have four. Contact sheets preserve these native dimensions.
- Across the combat cards, the center field visibly has two blue flag-like marks on T1–T2 cards, three on T3–T8 cards, and four on the three T9 examples. These counts describe pixels only; no game meaning is assigned.
- The common card shell has a left portrait/name panel, an adjacent badge area, a patterned center field, and a right-side grid. The grid is two columns wide and has four or five rows according to the card dimensions above.
- There are 247 pixel-unique right-grid cell crops across 598 grid-cell instances. Seventy-one distinct cell crops recur at least twice. The audit extracts those 71 plus all 30 T9 grid-cell variants.
- Fifteen cards are classified `Tr Stats`. Fourteen share a recurring grid recipe; Lee (542) is a visible outlier with an isometric structure/base-like right-grid tile in row 2, left column. The same right-grid tile pixels occur on Samuel (548), whose Data classification is `Tr HP`.
- Atropos (532), classified `RAID STATS`, has three copies of an isometric structure-like motif in the center field. This center motif is different from the right-grid tile seen on Lee and Samuel.
- The Data workbook classifications for all 14 downstream target IDs (509, 518, 527, and 556–566) were independently read from the `Heroes` tab and are recorded in the manifest. Their existing GitHub-referenced Column F formulas were excluded from this legacy source corpus.
- Standalone images from the `Icons` tab were checked. Eleven card-grid tile sources match pixel-for-pixel in RGB after at most a one-pixel crop registration adjustment, including troop/type and class-specific ATK/HP tiles. `gray-healing` and `gray-gath-march-speed` are near-pixel matches and are identified with measured RGB differences in the icon records. The Zzz and flag-looking standalone candidates remain separately attributed.

## Strong inference

- The corpus has two repeated structural shells: a combat-march shell and a passive/special shell. The manifest documents 19 visual/classification subgroups beneath those shells. Some one-card subgroups are kept separate because the evidence does not support combining their grid recipes.
- `Tr Stats` and `TROOP SIZE` labels align with repeated visual recipes, but the tile images alone do not prove the exact game effects encoded by each glyph.
- Standalone source filenames are useful clues (`type-fighter`, `gray-healing`, `gray-passive-icon`, and similar), but they do not independently establish gameplay semantics. The manifest keeps those associations as high or medium confidence rather than confirmed facts.
- The Zzz-like marks are likely associated with passive/special cards because they recur in those cards and a standalone `gray-passive-icon.png` exists. Whether they mean passive, sleeping, inactive, or another game state remains unverified.

## Needs user confirmation

1. What do the blue flag-like center marks represent, and what do their observed counts (2, 3, or 4) encode, if anything?
2. Are the isometric structure/base-like images sanctuary-related? If so, do the center-field Atropos motif and the Lee/Samuel right-grid tile refer to the same mechanic or different variants?
3. What is the precise gameplay meaning of the Zzz-like badge and repeated center-field Zzz pattern?
4. Do the blue pistol-like, red heart, yellow shield, troop, arrow, and crossed-weapon tiles specifically mean ATK, HP, DEF, troop size, or another effect? Their visual resemblance and source filenames do not settle this.
5. Why do heroes with the same `Tr Stats` classification have different grid recipes, including Lee's structure tile? Are these hero-specific stats, conditional/passive variants, or another distinction?
6. Is the T9 fifth grid row a meaningful additional attribute row, or a separate card-layout variant? The fifth row is visually confirmed; its gameplay purpose is not.
7. Which upper-badge symbols are authoritative Fighter/Rider/Shooter markers versus hero-specific or tier-specific marks? The three supplied T9 examples have distinct visible tile recipes, but the workbook does not label those glyphs.

No newer Column F template was designed or generated as part of this corpus.
