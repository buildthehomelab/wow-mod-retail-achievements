# Retail Achievements

Retail's mount achievements for an [AzerothCore](https://www.azerothcore.org/) (WotLK 3.3.5a)
server, pointed at content a 3.3.5a realm has. Retail gates many of its mounts behind an
achievement; this module brings those achievements over and mails the mount when one is earned.
The mounts themselves are the items of
[wow-mod-retail-collection](https://github.com/buildthehomelab/wow-mod-retail-collection).

This first batch is 105 achievements that the core's own criteria can track (the module's code
only catches characters up, keeps bots out and guards the rewards, see below):

| Family | Achievements | What it takes |
| --- | --- | --- |
| Mount collection | 16 (Alliance and Horde, as in retail) | Own 150, 200, 250, 300, 350, 400, 500 and 600 mounts; each follows the stock Mountain o' Mounts (100) |
| Timerunner | 9 | Reach level 80 with a Warrior, Paladin, Hunter, Rogue, Priest, Death Knight, Shaman, Mage or Warlock |
| Honor Level | 7 | 15,000, 25,000, 50,000, 75,000, 100,000, 150,000 and 250,000 honorable kills |
| Gladiator seasons | 13 | 100, 200, ... 1,500 battleground wins in any battleground (one step per retail season) |
| Combatant seasons | 24 (Alliance and Horde) | 50 or 150 wins in one battleground; each faction gets its season's Vicious mount |
| Bosses | 3 | Ragnaros (the stock Molten Core achievement); Azuregos, Lord Kazzak, Doomwalker and Doom Lord Kazzak; Algalon (Observed, 10 or 25 player) |
| Reputation, quests and metas | 33 | Exalted reputations, quests in a zone, and stock achievements put together, e.g. Wake Me Up (the Oracles), Closing Time (120 quests in Tanaris and Silithus), A World Awoken (Explore Northrend, Across the Isles, Northrend Vanguard) |

[`data/achievements.tsv`](data/achievements.tsv) lists every one with its retail id, and
[`data/criteria.tsv`](data/criteria.tsv) what it takes.

## How they work

- **Titles and rewards are retail's**, and so are the points (at most 50; 0 becomes 10). Where the
  retail goal doesn't exist here (a Legion Remix level, an arena rating, a Dragonflight zone), the
  description says what it takes instead.
- **Faction pairs:** where retail has an Alliance and a Horde version, so does this module, and
  each side only sees its own. A few metas over stock achievements that are themselves split by
  faction (Life of the Party, Worldsoul-Searching) come in pairs too.
- **Earned the usual way:** the core counts kills, wins, quests, reputations and mounts like it does
  for its stock achievements.
- **Catching up:** the core's own achievement check at login is switched off, so a second after
  each login the module checks its own criteria again: levels, mounts, reputations, quests,
  honorable kills and the stock achievements a meta needs. A character that already qualifies
  earns those on its next login. Stock achievements are left alone. Kills and battleground wins
  can't be caught up (the core only counts them as they happen):
  the Gladiator and Combatant wins, the world bosses and the Lich King count from the day the
  module is installed. Where a stock achievement covers a kill (Molten Core, Gnomeregan,
  Observed), that one is used instead, so earlier kills count.
- **Random bots don't earn them:** mod-playerbots' random bots (its `AiPlayerbot.RandomBotAccountPrefix`
  accounts, read at startup) would otherwise fill their mailboxes with reward mounts, so their
  progress on these isn't counted. A player's own characters played as bots count like the player.
- **No empty letters:** at startup the module looks up every reward item and mail sender. An
  achievement whose item or sender is missing (wow-mod-retail-collection not installed, say)
  counts no progress until it is there and the server has restarted, so its mount is never lost;
  the server log lists them. Kills and wins in that time don't count.
- **Faction change:** each Alliance and Horde pair is in `player_factionchange_achievement`, so a
  character that changes faction keeps what it earned on the other side's version.
- **The reward comes by mail**, from a character of the story (Mei Francis for the mount
  collection, Chromie for the Timerunners, the faction leaders for the Combatant mounts, ...).
- **Placed with the stock ones:** each achievement sits in the stock category that fits it
  (General, Player vs. Player, a battleground, Dungeons & Raids, Quests, Reputation, Exploration,
  World Events), after that category's own achievements. The collection, Honor Level and
  Gladiator ladders show one step at a time, like the stock ones.
- **Ids:** achievements 9300-9799 and criteria 20000-23999. The characters database keeps both
  as 16-bit numbers, so retail's own ids don't fit. A row keeps its id and meaning for good: the
  core deletes achievements it no longer knows from every character at startup, and criteria
  progress at login. The build refuses to drop or change one an earlier build had.
- **Not in this batch:** achievements whose reward mount has no look yet (Awake the Drakes'
  Emerald Drake, the Vicious War Steed, the Prestigious War Steed, the Crimson and Draconic
  Gladiator's Drakes), the Glory boss challenges, and the ones that need a check of their own
  (timed dungeons, flight paths, treasures, world PvP). The Gladiator steps of the two missing
  drakes keep their ids (9348, 9351).

## Installing

Server: clone this repo into the server's `modules` folder under the name
`mod-retail-achievements` (AzerothCore names the module's loader after its folder), with
[wow-mod-retail-collection](https://github.com/buildthehomelab/wow-mod-retail-collection) for the
reward mounts, then rebuild:

```bash
cd modules
git clone https://github.com/buildthehomelab/wow-mod-retail-achievements.git mod-retail-achievements
```

Its SQL ([`data/sql/db-world`](data/sql/db-world/mod_retail_achievements.sql)) adds the
achievements, their criteria, the reward mail and the faction change pairs. Install
wow-mod-retail-collection first, or at the same time: until its items exist, the achievements
wait (see No empty letters).

Client: the spell patch (whichever patch of yours carries `Achievement.dbc` and
`Achievement_Criteria.dbc`), rebuilt with the module's rows. A player without it still earns the
achievements and gets the mail, but sees them without a name.

## Requirements

- An AzerothCore (WotLK 3.3.5a) server.
- [wow-mod-retail-collection](https://github.com/buildthehomelab/wow-mod-retail-collection): the
  reward mounts (items 400000 and up). Without it the achievements can't be earned.
- To build: Python 3.10+ and [StormLib](https://github.com/ladislav-zezula/StormLib).

## Building

```bash
python3 tools/build_achievements.py --patch <your spell patch> --out <new spell patch> \
    --sql data/sql/db-world/mod_retail_achievements.sql
```

The spell patch needs the collection's rows already (the build checks that every reward item is in
its `Item.dbc` and every icon in its `SpellIcon.dbc`), so build this module after
wow-mod-retail-collection. The build only writes rows in its own blocks of `Achievement.dbc` and
`Achievement_Criteria.dbc` and leaves every other row and file alone; running it again on its own
output changes nothing. It stops when the data drops an achievement or criterion that the input
patch or the module's current SQL has, or changes what a criterion counts (its achievement, type,
asset or criteria data) or an achievement's faction; `--allow-changes` lets it through, for rows no server has yet. Add new rows with new ids.

### The data files

`data/achievements.tsv`, one row per achievement:

| Column | |
| --- | --- |
| `id` | 9300-9799 |
| `retail_id` | the retail achievement it comes from |
| `faction` | `any`, `alliance` or `horde` |
| `category` | an Achievement_Category id that has stock achievements (92 General, 95 Player vs. Player, ...) |
| `parent` | the achievement this one follows in a series (shown once that one is done), or 0 |
| `points`, `icon` | achievement points; a SpellIcon id |
| `count` | how many of its criteria it needs (0: all of them) |
| `flags` | 0, or 136 to add up its criteria into one bar (each criterion then holds the total) |
| `title`, `description` | at most 100 and 200 characters |
| `reward`, `item`, `letter` | the mount's name (shown as "Reward: ..."), the item mailed, and the letter in `letters.tsv` |

`data/criteria.tsv`, one row per criterion: `id` (20000-23999), `achievement`, `type`
(`kill_creature`, `win_bg`, `reach_level`, `complete_achievement`, `quests_in_zone`,
`complete_quest`, `learn_spell`, `gain_reputation`, `exalted_reputations`, `use_gameobject`,
`skillline_spells`, `honorable_kills`), `asset` and `quantity` (what and how many, as the core
reads them), `flags` (1 progress bar, 2 hidden), `data` (`class=N`, `race=N` or `difficulty=N`
for the core's criteria data) and `text`. Kill and battleground criteria get the empty criteria
data row the core needs to count them.

`data/letters.tsv`: `key`, `sender` (a creature entry), `subject` and `body`, where `{title}` is
the achievement's title and `{mount}` its reward.

## Removing

Run [`data/sql/uninstall/mod_retail_achievements_uninstall.sql`](data/sql/uninstall/mod_retail_achievements_uninstall.sql)
on the world database, remove the module folder, rebuild, and go back to a spell patch without the
achievements. Earned achievements are lost; mounts already mailed stay.

## Patch Notes: Retail Achievements

Category: Achievements

- 105 achievements from later expansions now reward the mounts they gave there, each by mail:
  - Mount collection: 150 to 600 mounts.
  - Timerunner: reach level 80 with a Warrior, Paladin, Hunter, Rogue, Priest, Death Knight,
    Shaman, Mage or Warlock.
  - Honor Level: 15,000 to 250,000 honorable kills.
  - Gladiator: 100 to 1,500 battleground wins.
  - Combatant: 50 or 150 wins in one battleground, for a Vicious mount of your faction.
  - Ragnaros, the old world bosses and Algalon.
  - Reputations, zone quests and meta achievements across Kalimdor, the Eastern Kingdoms, Outland
    and Northrend.
- Characters that already qualify earn them on their next login. Kills and battleground wins count
  from today.

## Credits

- Achievement titles, reward mounts and icons: Blizzard Entertainment, from retail's tables.
- The reward mounts are wow-mod-retail-collection's.

## License

MIT, see [LICENSE](LICENSE).
