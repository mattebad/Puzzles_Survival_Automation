# Daily Quest handler status matrix

Source: `tasks/daily_quest_catalog.json`, seeded from the complete 2026-07-13 inventory. A
runtime alias can match a catalog row but cannot change its policy or consequence class.

| Objective key | Handler family | Policy | Implementation | Live status | Priority |
|---|---|---|---|---|---:|
| upgrade_building | building_upgrade | disabled | CATALOGED | not started | 31 |
| join_hero_duel | combat_pvp | disabled | DISABLED_POLICY | not started | 30 |
| upgrade_tech | research_or_upgrade | disabled | DISABLED_POLICY | not started | 29 |
| train_fighter | training | disabled | CATALOGED | not started | 20 |
| train_rider | training | disabled | CATALOGED | not started | 21 |
| train_shooter | training | disabled | CATALOGED | not started | 22 |
| train_vehicle | training | disabled | CATALOGED | not started | 23 |
| recruit_noahs_tavern | recruitment | free-only pending proof | CATALOGED | not started | 6 |
| upgrade_hero | hero_upgrade | disabled | DISABLED_POLICY | not started | 28 |
| defeat_zombie_lair | zombie_lair | stamina and level policy | CATALOGED | not started | 13 |
| consume_stamina | stamina | disabled | DISABLED_POLICY | not started | 12 |
| consume_ap | campaign_ap | AP budget required | CATALOGED | not started | 11 |
| help_allies | alliance_help | supervised zero-cost | LIVE_VALIDATED | individual Help validated; lower Help All validated by exact no-request popup | 2 |
| buy_box | purchase | disabled | DISABLED_POLICY | not started | 27 |
| gather_wood | gathering | march and World policy | CATALOGED | not started | 14 |
| gather_steel | gathering | march and World policy | CATALOGED | not started | 15 |
| gather_gas | gathering | march and World policy | CATALOGED | not started | 17 |
| boost_resource_building_output | resource_building | disabled | CATALOGED | not started | 26 |
| ruins_shop_purchase | purchase | disabled | DISABLED_POLICY | not started | 24 |
| rare_earth_shop_purchase | purchase | disabled | DISABLED_POLICY | not started | 25 |
| alliance_shop_purchase | purchase | disabled | DISABLED_POLICY | not started | 23 |
| speedup_using_items | speedup_item | disabled | CATALOGED | not started | 19 |
| bioenhancer_research | bioenhancer | one free daily only | CATALOGED | not started | 5 |
| craft_nanoweapon | nanoweapon | free-only pending proof | CATALOGED | not started | 10 |
| personal_might_praise | praise | cooldown bounded | CATALOGED | not started | 4 |
| enhance_chip | enhancement | one-star material only | CATALOGED | not started | 8 |
| enhance_module | enhancement | one-star material only | CATALOGED | not started | 9 |
| enhance_gear | enhancement | one-star material only | CATALOGED | not started | 7 |
| donate_alliance_tech | donation | disabled | DISABLED_POLICY | not started | 32 |
| supply_depot | supply_depot | free-only; stop when Free disappears | CATALOGED | not started | 3 |
| ruins_challenge | challenge | disabled | CATALOGED | not started | 18 |

The ordinary completed-row Claim transaction is handled by the existing safe-action core and is
not a new inventory row. Tier-4 spending, PvP, uncontrolled upgrades, purchases, and unknown-cost
actions remain disabled regardless of their Go route.
