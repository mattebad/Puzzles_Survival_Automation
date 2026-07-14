# Alliance Help semantic correction — 2026-07-13

## Historical interpretation correction

The immutable historical action recorded as `ALLIANCE_HELP_ALL` at ROI
`(556,274)-(727,330)` and tap `(641,302)` visibly targeted the upper row-level orange button
labeled **Help**. Its correct semantic interpretation is `ALLIANCE_HELP_ONE`: one individual
request was processed. The lower button labeled **Help All** remained visible in the retained
post frame. Historical screenshots and SQLite rows are unchanged.

## Separate actual Help All target

The actual `ALLIANCE_HELP_ALL` anchor is the lower orange button at
`(277,1188)-(523,1268)`, center `(400,1228)`. Authorization requires literal Help All OCR or the
independently cropped retained template, the fixed lower-screen geometry, an orange rectangular
button, a complete unclipped target, and an interior tap. A target near `(641,302)` is rejected.

## Actual lower Help All live result

The pnsctl-only action `alliance-help-1783986842` positively matched literal `Help All` at
`(277,1188)-(523,1268)`, center `(400,1228)`. The mandatory JSON and annotated screenshot proved
the target top was 1188, center y was greater than 1150, the target did not intersect the
individual-help region, and the tap was inside the button with margin.

Exactly one tap at `(400,1228)` was dispatched. The first bounded post observation positively
contained the transient exact message `No help request currently`; later frames returned to
Speedup Help. The immutable source journal is preserved, and a reconciled copy confirms the action
from that positive semantic evidence. Help All is live-validated; no request was available and no
Daily Quest completion is inferred.
