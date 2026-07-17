# Ruins Challenge workflow

This is a separate workflow with an executable local BlueStacks route for the Ruins Challenge surface. It does not
register with production, does not enable scheduler eligibility, and does not share state with
Noah's Tavern, Nova Praise, Bioenhancer, Personal Might Praise, Campaign/AP, or recruit routes.

The native adapter accepts only 800×1280 frames. The controller binds a reset identity, keeps each
challenge row independent, rejects locked/wrong-day/premium/paid/ticketed controls, and guards
duplicate action keys and frame hashes. Challenge entry is treated as two consequential steps:
Attack on the detail screen, then Dispatch only when NPC troops are provided and no cost surface is
present. Success and failure are distinct; failure and ambiguity are terminal for that challenge.

Chest claims have their own action keys and postconditions. Exchange, Progress, Total Rank, Mall,
Fast Upgrade, challenge-specific upgrades, and the Daily Quest Claim remain outside the claim path.

`scripts/ruins_challenge_bluestacks.py` performs Home → Ruins → current-day row selection → Attack
→ zero-cost NPC Dispatch → explicit result → progress reconciliation → Home. Optional Ruins chest
claiming is independently gated with `--claim-chests`. A distinct second current-day stage is
permitted only with `--allow-optional-second`, only after an explicitly reconciled first-stage
failure, and never repeats the first identity.

```text
python scripts/ruins_challenge_bluestacks.py --adb <BlueStacks-ADB> --serial <local-serial> --reset-identity <verified-reset> --current-day <Mon-Sun> --execute --yes
```

The route is dry-run by default, retains native frames and transport events under
`.local-captures/`, and leaves production registration and scheduler eligibility disabled. A later
Bliss transport can implement the same runtime port without changing the Ruins controller.

The 2026-07-16 local BlueStacks validation observed two timer-bound current-day rows: Nova Challenge
and Module Challenge. Both used NPC troops and zero visible entry cost, and both reached explicit
LOSE results at the observed floors (Nova 19/100 and Module 47/200). The Daily row nevertheless
reported `Enter Ruins Challenge 1x (1/1)` after the two initiations; its Claim control was left
untouched. Eight previously completed Ruins chests were separately claimed and reconciled.

The 2026-07-16 integrated executable rerun proved Home → Ruins list → Home using only project code.
The fresh list showed 16,350 Ruins points and the same reset-cycle Nova row at the clipped lower
edge. Nova and Module were explicitly excluded because both had already been attempted in retained
validation evidence, so the controller issued zero challenge and zero chest actions. This is the
required no-repeat behavior for an already-completed reset cycle.
