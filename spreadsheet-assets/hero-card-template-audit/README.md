# Legacy hero card template audit corpus

This directory contains original Column F hero card images and lossless visual extracts for template inspection. It does not contain redesigned or generated hero cards.

## Sources

- **Copy of Icon Links** — workbook `1DLY7kfoEnVjmP9fMgaL1J5b64prJ4bAklBnEzAjAJcw`, tab `HeroIcons`, read-only range `C1:G105`. Each legacy card URL was taken from the `IMAGE()` formula in column F.
- **Data workbook** — workbook `1Ra1fAhZspm3zhiCgyj7LSLeQyVkCGPYacvikK341jc8`, tab `Heroes`, read-only range `A1:E107`. Metadata was joined by hero ID.
- A subset of standalone icon candidates was read from the `Icons` tab in the first workbook. Their source cells and original URLs are in `manifest.json`.

## Extraction method

1. Read the formula text from HeroIcons column F and parse its first URL. Only original `files.secure.website` URLs were accepted as legacy card sources. Later `raw.githubusercontent.com` Column F formulas were excluded as newer generated GitHub assets.
2. Download each accepted URL as bytes and save those bytes under `cards/` without resizing or image rewriting. The filename is `<id>_<hero_slug>.png`; the source files were all PNG. SHA-256 and decoded dimensions are recorded per card.
3. Join the source HeroIcons row to the Data workbook row by ID. The manifest retains the formula, original URL, raw Type cell, readable Type label, color, tier/skill, rows, dimensions, local path, and hash. The workbook's Type cells contain glyphs; readable class labels use the glyph mapping supplied in the user request, while the raw values remain available.
4. Extract distinct right-grid tiles as lossless 78×78 PNGs at x=327/406 and y=0/81/161/241. The three 485×402 T9 cards also have a fifth row at y=322. Recurring exact crops are retained, as are every distinct T9 grid-cell crop. Repeated upper/lower badge crops use the coordinate boxes recorded in the manifest. Two center-field motifs are cropped from clean card pixels. Where a matching standalone source was found, that source was used and its sheet cell, URL, and pixel comparison are recorded.
5. Contact sheets are PNGs assembled from the original-resolution card pixels. They do not resize or alter source cards. Icon sheets show extracted crops at their source pixel dimensions.

To reproduce the download, take each `original_url` in `manifest.json`, request it directly, and write the response body to the card's `file` path. Recompute SHA-256 and decode the image to verify the recorded `width`, `height`, and `format`. The workbook formulas are preserved in the manifest so URL extraction can be audited. Contact-sheet crop coordinates and per-card grid occurrences are also recorded.

## Directory structure

- `cards/` — all 74 original hosted card files.
- `icons/` — distinct recurring grid cells, T9 grid cells, badge variants, and selected standalone or center-field icon sources.
- `contact-sheets/` — card and icon contact sheets, including extra pages where needed for readability.
- `manifest.json` — complete machine-readable card, icon, family, source, dimension, hash, and confidence inventory.
- `findings.md` — visual findings with confirmed observations separated from inference and questions.

## Completeness and exclusions

All 74 original legacy card URLs in scope downloaded successfully; none failed. Every retrieved card is a unique byte sequence. Seventy-one originals are 485×321; the three T9 cards (501 Celine, 510 Kajisha, 519 Gerald) are 485×402. No asset was missing from this original-host scope. Candidate standalone icon downloads used for comparison also succeeded; candidates without a confident card correspondence were not added to `icons/`.

GitHub-referenced/generated Column F images were excluded from this legacy source set. Existing portrait assets under `spreadsheet-assets/hero-icons/` were not changed. No Google Sheet was modified.

## Verification

The corpus was checked by reopening every image, comparing card SHA-256 values to the retrieval inventory, confirming decoded dimensions, and checking that every contact sheet contains non-uniform image pixels. Contact sheets show source images rather than broken-link placeholders.
