# Reputation audit — October 20, 2026

Scope: every direct reputation criterion in the 105-achievement catalog, plus the
stock reputation achievements used by its metas. Source: repository TSVs and the
locally saved Evermore z80 DBCs. This checks content compatibility, not live server
availability, character progression or in-game reward delivery.

| Custom IDs | Requirement | Assessment |
| --- | --- | --- |
| 9400 | The Oracles (stock 951) | Northrend; earned achievement survives changing sides |
| 9401 | Kalu'ak | Northrend |
| 9402 | Netherwing | Outland |
| 9403 | Shattered Sun Offensive | Outland / Quel'Danas |
| 9404 | Ogri'la | Outland |
| 9405 | Consortium | Outland |
| 9406 | Thorium Brotherhood + Hydraxian Waterlords | Classic |
| 9407, 9408 | Kalu'ak + earned Oracles (951) and Frenzyheart (950) | Sequential opposing reputations; clarified description |
| 9409 | Cenarion Expedition + Mysteries of the Marsh | Outland |
| 9410 | Booty Bay, Gadgetzan, Ratchet, Everlook | Classic; all four Steamwheedle factions can coexist |
| 9411 | Ashtongue Deathsworn + Shadow of the Betrayer | Outland |
| 9412 | Sons of Hodir + The Summit of Storm Peaks | Northrend |
| 9425 | 40 exalted factions | Reduced from 45 to the stock Wrath milestone; reward unchanged |
| 9428 | Northrend Vanguard (1010), plus exploration/quest metas | Stock four Northrend dungeon factions |
| 9429, 9430 | The Burning Crusader (764 / 763), plus exploration/quest metas | Stock faction-specific Outland dungeon reputations |

All 14 unique direct faction IDs exist in the saved Faction.dbc. Stock achievements
950, 951, 1010, 1015, 763 and 764 exist with the expected goals. No direct reputation
criterion references a faction introduced after Wrath. No simultaneous Oracles/Frenzyheart
requirement is introduced. No faction cap or core reputation-counting behavior is changed.

Validation: TSV loader, existing compatibility guard, generated SQL, candidate MPQ
rebuild/rebuild idempotence and preservation checks. SQL ordering retains the repository's
recorded Ui_Order values; the locally saved patch has different stock General ordering.
The candidate is not a published patch. Live SQL import, loaded-server faction availability,
full progression completion and reward mail remain unverified.
