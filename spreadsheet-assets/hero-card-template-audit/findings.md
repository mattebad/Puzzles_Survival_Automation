# Forensic findings

## Confirmed

- 74 usable legacy Column F `IMAGE()` formulas pointed to `files.secure.website`; 74/74 original PNG files were retrieved. Each file has a distinct SHA-256. There were no failed source URLs.
- The Data workbook contains 74 joined rows for those cards. Color, Tier / Skill, Type, and workbook row values are in `manifest.json` alongside the raw HeroIcons formula and URL.
- A read-only follow-up of the `Heroes` tab header area and Lee's row found classification and coded progression/build fields, but no readable per-skill effect descriptions. Other workbook tabs were not comprehensively searched for a separate effect catalog; this inspection made no sheet changes.
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
- The Zzz-like marks recur on passive/special cards and a standalone `gray-passive-icon.png` exists. Their meaning is clarified by the user below; this meaning is not established by a workbook label.

## User-provided clarifications

These interpretations were supplied by the user after reviewing the linked pictures. They are recorded as user-provided gameplay context, not as claims independently established by the workbook or image filenames.

- The blue flag means the stats apply to the active march while the hero is active. The user cites Hanyu's Fighter ATK, Rider ATK, and Troop DEF as examples.
- For Lee (542), the user identifies Protected Resources and Reinforcement March Speed increases as Sanctuary stats, and Troop ATK as a passive increase. The user describes Lee's troop skill card as showing those effects. This clarifies the effect categories, but does not by itself prove that the pictured structure-like motifs are Sanctuary icons.
- Zzz means a passive-stat increase or an economy-stat increase.
- The user identifies the blue gun as ATK, the shield as DEF, the arrow as free speedups, the gold crossed-weapon tile as Fighter stats, and the troop-looking tile as a troop-stat type. The user confirms the heart tile means HP. The red-cross/X mark remains ambiguous.
- Hero stat attributes vary by hero. All heroes have tactical skills. The user sees a red-cross/X mark on Lee's and other heroes' tactical-skill displays but does not know what it means; it should not be interpreted as a missing tactical skill.
- Some T9 heroes have four troop skills rather than three. For Kajisha, the user lists Rider ATK, Shooter ATK, Troop DEF, and Troop HP. This does not establish a one-to-one mapping between the five visible right-grid rows and skill count.

## Needs user confirmation

1. What, if anything, do the observed blue-flag counts (2, 3, or 4) encode beyond the user's clarification that the flag marks active-march applicability?
2. Are the center-field Atropos structure motif and the Lee/Samuel right-grid structure tile both Sanctuary-related, or do they represent different mechanics?
3. What does the red-cross/X mark on tactical-skill displays mean? The user says all heroes have tactical skills and does not know why the mark appears.
4. Which upper-badge symbols are authoritative Fighter/Rider/Shooter markers versus hero-specific or tier-specific marks?
5. How does the five-row T9 card grid represent the three- or four-skill sets reported by the user? The card pixels and user clarification establish the layouts and skill counts separately, but not their exact row-to-skill mapping.

No newer Column F template was designed or generated as part of this corpus.
