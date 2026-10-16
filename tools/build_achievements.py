#!/usr/bin/env python3
"""Turn data/achievements.tsv, data/criteria.tsv and data/letters.tsv into achievement rows for the
realm's spell patch and the module's world database SQL.

    python3 build_achievements.py --patch patch-z80-spells-and-items.MPQ \\
        --out patch-z80-spells-and-items-new.MPQ --sql ../data/sql/db-world/mod_retail_achievements.sql

--patch is the realm's patch that carries Achievement.dbc and Achievement_Criteria.dbc (and
Item.dbc and SpellIcon.dbc, which the build only reads). A patch MPQ replaces whole files, so the
new rows go into its copies and every other file in it is copied unchanged. It gains:

- Achievement.dbc: one row per achievement, placed after the stock achievements of its category.
- Achievement_Criteria.dbc: its criteria.

The SQL has the same rows for the server (achievement_dbc, achievement_criteria_dbc), the
criteria data the core wants for some criteria types (achievement_criteria_data), the mail that
brings the reward mount (achievement_reward), and the Alliance and Horde twins for a faction
change (player_factionchange_achievement).

Every id is the module's: achievements 9300-9799, criteria 20000-23999 (the characters database
keeps both as 16-bit numbers). Rows in those blocks are written again from the data files; rows
outside them are never touched. Running the tool again on its own output changes nothing.

Rows players may have earned keep their meaning: the build stops when the input patch or the
current SQL file has an achievement or criterion the data drops, or a criterion that now counts
something else, unless --allow-changes says no server has them yet.
"""
import argparse
import csv
import os
import re
import struct
import sys
import tempfile

import dbcmpq
from dbcmpq import add_string, read_dbc, write_dbc

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
ACHIEVEMENT_BLOCK = (9300, 9799)
CRITERIA_BLOCK = (20000, 23999)

ACHIEVEMENT_FIELDS, CRITERIA_FIELDS = 62, 31
UNSET = 0xFFFFFFFF                          # -1: either faction, any map
LANG_MASK, LANG_MASK_EMPTY = 16712190, 16712188
FACTIONS = {"any": UNSET, "horde": 0, "alliance": 1}
ACHIEVEMENT_FLAG_SUMM = 0x8                 # sum the criteria counters (each criterion holds the goal)
ACHIEVEMENT_FLAG_BAR = 0x80                 # show the sum as one progress bar (stock sums set both)
SPELL_FIELDS, F_SPELL_ICON = 234, 133
# Lengths of the server's columns (achievement_dbc, achievement_criteria_dbc, achievement_reward).
TITLE_MAX, DESCRIPTION_MAX, REWARD_MAX, CRITERION_MAX, SUBJECT_MAX = 100, 200, 100, 100, 255

# Criteria types (the core's AchievementCriteriaTypes) the data files may use.
CRITERIA_TYPES = {
    "kill_creature": 0,          # asset creature entry (the normal-difficulty one), quantity kills
    "win_bg": 1,                 # asset battleground map, quantity wins
    "reach_level": 5,            # quantity level
    "complete_achievement": 8,   # asset achievement
    "quests_in_zone": 11,        # asset zone (quest_template.QuestSortID), quantity quests
    "complete_quest": 27,        # asset quest
    "learn_spell": 34,           # asset spell
    "gain_reputation": 46,       # asset faction, quantity reputation (42000 is exalted)
    "exalted_reputations": 47,   # quantity factions at exalted
    "use_gameobject": 68,        # asset gameobject entry
    "skillline_spells": 75,      # asset skill line (777 mounts, 778 companions), quantity spells
    "honorable_kills": 113,      # quantity lifetime honorable kills
}
# Types the core only counts when the criterion has a row in achievement_criteria_data.
NEEDS_DATA = {0, 1}
# achievement_criteria_data types the data column may set: name=value1[:value2]
DATA_TYPES = {
    "class": 21,                 # the player's class (value1); ACHIEVEMENT_CRITERIA_DATA_TYPE_S_PLAYER_CLASS_RACE
    "race": 21,                  # the player's race (value2 of the same type)
    "difficulty": 12,            # the map's difficulty (0 normal, 1 heroic / 25 player, ...)
}
SQL_CHUNK = 500


def load_tsv(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    for i, r in enumerate(rows, 2):
        bad = [k for k, v in r.items() if v is None or k is None or any(c in v for c in "\t\r\n")]
        need(not bad, path, "line %d: a missing column, or a tab or line break in %s" % (i, ", ".join(map(str, bad))))
    return rows


def need(cond, path, what):
    if not cond:
        sys.exit("%s: %s" % (path, what))


def load_data(folder):
    """The three data files, checked; returns (achievements, criteria, letters)."""
    path = os.path.join(folder, "letters.tsv")
    letters = {}
    for r in load_tsv(path):
        need(r["key"] not in letters, path, "two letters named %s" % r["key"])
        r["sender"] = int(r["sender"])
        need(len(r["body"]) < 8000, path, "letter %s is too long" % r["key"])
        letters[r["key"]] = r

    path = os.path.join(folder, "achievements.tsv")
    achievements = load_tsv(path)
    seen = set()
    for a in achievements:
        for k in ("id", "retail_id", "category", "parent", "points", "icon", "count", "flags", "item"):
            a[k] = int(a[k] or 0)
        what = "achievement %d %s" % (a["id"], a["title"])
        need(ACHIEVEMENT_BLOCK[0] <= a["id"] <= ACHIEVEMENT_BLOCK[1], path,
             "%s is outside the block %d-%d" % (what, *ACHIEVEMENT_BLOCK))
        need(a["id"] not in seen, path, "%s: the id is used twice" % what)
        seen.add(a["id"])
        need(a["faction"] in FACTIONS, path, "%s: faction is one of %s" % (what, ", ".join(FACTIONS)))
        need(0 < len(a["title"]) <= TITLE_MAX, path, "%s: the title is empty or longer than %d" % (what, TITLE_MAX))
        need(0 < len(a["description"]) <= DESCRIPTION_MAX, path,
             "%s: the description is empty or longer than %d" % (what, DESCRIPTION_MAX))
        need(len(reward_text(a)) <= REWARD_MAX, path, "%s: the reward text is longer than %d" % (what, REWARD_MAX))
        need(bool(a["item"]) == bool(a["letter"]), path, "%s: an item needs a letter and a letter an item" % what)
        need(not a["letter"] or a["letter"] in letters, path, "%s: no letter %s" % (what, a["letter"]))
        need(not a["letter"] or len(letter_text(a, letters, "subject")) <= SUBJECT_MAX, path,
             "%s: the mail subject is longer than %d" % (what, SUBJECT_MAX))
        need(a["flags"] in (0, ACHIEVEMENT_FLAG_SUMM | ACHIEVEMENT_FLAG_BAR), path,
             "%s: flags is 0 or %d (sum the criteria, as one bar)" % (what, ACHIEVEMENT_FLAG_SUMM | ACHIEVEMENT_FLAG_BAR))
        a["criteria"] = []
    by_id = {a["id"]: a for a in achievements}

    path = os.path.join(folder, "criteria.tsv")
    criteria = load_tsv(path)
    seen = set()
    for c in criteria:
        for k in ("id", "achievement", "asset", "quantity", "flags"):
            c[k] = int(c[k] or 0)
        what = "criterion %d %s" % (c["id"], c["text"])
        need(CRITERIA_BLOCK[0] <= c["id"] <= CRITERIA_BLOCK[1], path,
             "%s is outside the block %d-%d" % (what, *CRITERIA_BLOCK))
        need(c["id"] not in seen, path, "%s: the id is used twice" % what)
        seen.add(c["id"])
        need(c["achievement"] in by_id, path, "%s: no achievement %d" % (what, c["achievement"]))
        need(c["type"] in CRITERIA_TYPES, path, "%s: type is one of %s" % (what, ", ".join(CRITERIA_TYPES)))
        c["type_id"] = CRITERIA_TYPES[c["type"]]
        need(0 < len(c["text"]) <= CRITERION_MAX, path, "%s: the text is empty or longer than %d" % (what, CRITERION_MAX))
        c["data_rows"] = criteria_data(c, path, what)
        by_id[c["achievement"]]["criteria"].append(c)
    for a in achievements:
        what = "achievement %d %s" % (a["id"], a["title"])
        need(a["criteria"], path, "%s has no criteria" % what)
        need(a["count"] <= len(a["criteria"]), path, "%s needs %d of its %d criteria" % (what, a["count"], len(a["criteria"])))
        if a["flags"] & ACHIEVEMENT_FLAG_SUMM:
            goals = {c["quantity"] for c in a["criteria"]}
            need(len(goals) == 1 and min(goals) > 0, path,
                 "%s sums its criteria, so each of them holds the same goal" % what)
    return achievements, criteria, letters


def criteria_data(c, path, what):
    """achievement_criteria_data rows (type, value1, value2) for a criterion."""
    rows = {}
    for part in filter(None, c["data"].split(",")):
        name, _, value = part.partition("=")
        need(name in DATA_TYPES and value.isdigit(), path, "%s: data is name=value with name one of %s"
             % (what, ", ".join(DATA_TYPES)))
        kind = DATA_TYPES[name]
        v1, v2 = rows.get(kind, (0, 0))
        if name == "race":
            v2 = int(value)
        else:
            v1 = int(value)
        rows[kind] = (v1, v2)
    if c["type_id"] in NEEDS_DATA and not rows:
        rows[0] = (0, 0)              # an empty row: the core counts the criterion only with one
    return sorted((k, v1, v2) for k, (v1, v2) in rows.items())


def check_kept(old_achievements, old_criteria, achievements, where, allow):
    """Rows players may already have must stay what they were. The core deletes an achievement or
    criterion it no longer knows from every character, and reads old progress under a changed
    criterion's new meaning. old_achievements: {id: faction}; old_criteria: {id: (achievement,
    type, asset[, criteria data rows])}; the patch has no criteria data, the SQL does."""
    new_a = {a["id"]: FACTIONS[a["faction"]] for a in achievements}
    new_c = {c["id"]: (a["id"], c["type_id"], c["asset"], tuple(c["data_rows"])) for a in achievements for c in a["criteria"]}
    problems = ["achievement %d is gone" % i for i in sorted(set(old_achievements) - set(new_a))]
    problems += ["achievement %d changed faction" % i for i in sorted(old_achievements)
                 if i in new_a and old_achievements[i] != new_a[i]]
    problems += ["criterion %d is gone" % i for i in sorted(set(old_criteria) - set(new_c))]
    problems += ["criterion %d changed achievement, type, asset or data" % i for i in sorted(old_criteria)
                 if i in new_c and old_criteria[i] != new_c[i][:len(old_criteria[i])]]
    if not problems:
        return
    text = "%s has rows this build drops or changes: %s" % (where, "; ".join(problems))
    if not allow:
        sys.exit(text + ".\nPlayers lose what they earned there. Give new ids instead, or pass "
                 "--allow-changes if no server has these rows yet.")
    print("WARNING: " + text)


def old_sql_rows(path):
    """The achievements and criteria the module's current SQL file gives the server."""
    old_a, old_c, data = {}, {}, {}
    if not os.path.exists(path):
        return old_a, old_c
    text = open(path, encoding="utf-8").read()
    for table, pattern in (("achievement_dbc", r"^\((\d+), (-?\d+), "),
                           ("achievement_criteria_dbc", r"^\((\d+), (\d+), (\d+), (\d+), ")):
        for m in re.finditer(r"INSERT INTO `%s` .*?;\n" % table, text, re.S):
            for row in re.finditer(pattern, m.group(0), re.M):
                v = [int(x) for x in row.groups()]
                if table == "achievement_dbc":
                    old_a[v[0]] = struct.unpack("<I", struct.pack("<i", v[1]))[0]
                else:
                    old_c[v[0]] = (v[1], v[2], v[3])
    for m in re.finditer(r"INSERT INTO `achievement_criteria_data` .*?;\n", text, re.S):
        for row in re.finditer(r"^\((\d+), (\d+), (\d+), (\d+), ", m.group(0), re.M):
            v = [int(x) for x in row.groups()]
            data.setdefault(v[0], []).append(tuple(v[1:]))
    for i in old_c:
        old_c[i] += (tuple(sorted(data.get(i, []))),)
    return old_a, old_c


def faction_pairs(achievements):
    """(alliance id, horde id, title) of each achievement that comes in one Alliance and one Horde
    version of the same title, for the core's faction change."""
    by_title = {}
    for a in achievements:
        if a["faction"] != "any":
            by_title.setdefault(a["title"], []).append(a)
    pairs = []
    for title, rows in by_title.items():
        sides = {a["faction"]: a["id"] for a in rows}
        if len(rows) == 2 and len(sides) == 2:
            pairs.append((sides["alliance"], sides["horde"], title))
    return sorted(pairs)


def reward_text(a):
    return "Reward: %s" % a["reward"] if a["reward"] else ""


def letter_text(a, letters, field):
    return letters[a["letter"]][field].format(title=a["title"], mount=a["reward"])


# --- client patch ------------------------------------------------------------------------------

def dbc_name(table):
    return "DBFilesClient\\%s.dbc" % table


def in_block(row_id, block):
    return block[0] <= row_id <= block[1]


def patch_dbcs(files, achievements, criteria, args):
    """Writes the rows into the unpacked patch; returns {achievement id: ui order}."""
    for table in ("Achievement", "Achievement_Criteria", "Item", "SpellIcon"):
        need(dbc_name(table) in files, args.patch, "it has no %s.dbc" % table)
    rows, strings, fields = read_dbc(files[dbc_name("Achievement")])
    need(fields == ACHIEVEMENT_FIELDS, args.patch, "Achievement.dbc has %d fields, not %d" % (fields, ACHIEVEMENT_FIELDS))
    crit_rows, crit_strings, crit_fields = read_dbc(files[dbc_name("Achievement_Criteria")])
    need(crit_fields == CRITERIA_FIELDS, args.patch,
         "Achievement_Criteria.dbc has %d fields, not %d" % (crit_fields, CRITERIA_FIELDS))
    items = {r[0] for r in read_dbc(files[dbc_name("Item")])[0]}
    icons = {r[0] for r in read_dbc(files[dbc_name("SpellIcon")])[0]}

    ours = {a["id"] for a in achievements}
    check_kept({r[0]: r[1] for r in rows if in_block(r[0], ACHIEVEMENT_BLOCK)},
               {r[0]: (r[1], r[2], r[3]) for r in crit_rows if in_block(r[0], CRITERIA_BLOCK)},
               achievements, args.patch, args.allow_changes)
    stock = [r for r in rows if not in_block(r[0], ACHIEVEMENT_BLOCK)]
    clash = [r[0] for r in crit_rows if in_block(r[0], CRITERIA_BLOCK) and not in_block(r[1], ACHIEVEMENT_BLOCK)]
    need(not clash, args.patch, "criteria %s in the module's block belong to other achievements" % clash)

    stock_ids = {r[0] for r in stock}
    categories = {r[38] for r in stock}
    faction = {r[0]: r[1] for r in stock}
    faction.update({a["id"]: FACTIONS[a["faction"]] for a in achievements})

    def reachable(what, other):
        """An achievement of one faction can't need, or follow, one of the other faction."""
        need(other != what["id"], args.patch, "achievement %d refers to itself" % what["id"])
        mine, theirs = faction[what["id"]], faction[other]
        need(mine == theirs or UNSET in (mine, theirs), args.patch,
             "achievement %d (%s) refers to %d of the other faction" % (what["id"], what["faction"], other))
    for a in achievements:
        what = "achievement %d %s" % (a["id"], a["title"])
        need(a["category"] in categories, args.patch, "%s: no stock achievement is in category %d" % (what, a["category"]))
        need(not a["parent"] or a["parent"] in stock_ids or a["parent"] in ours, args.patch,
             "%s: no achievement %d to follow" % (what, a["parent"]))
        if a["parent"]:
            reachable(a, a["parent"])
        need(a["icon"] in icons, args.patch, "%s: SpellIcon.dbc has no row %d" % (what, a["icon"]))
        need(not a["item"] or a["item"] in items, args.patch, "%s: Item.dbc has no item %d" % (what, a["item"]))
        for c in a["criteria"]:
            if c["type"] == "complete_achievement":
                need(c["asset"] in stock_ids or c["asset"] in ours, args.patch,
                     "criterion %d: no achievement %d" % (c["id"], c["asset"]))
                if a["count"] != 1:             # "any one of" may list both factions' versions
                    reachable(a, c["asset"])

    # Each category lists ours after its stock achievements, in the order of the data file.
    last = {}
    for r in stock:
        last[r[38]] = max(last.get(r[38], 0), r[40])
    order = {}
    for a in achievements:
        last[a["category"]] += 1
        order[a["id"]] = last[a["category"]]

    rows[:] = stock
    for a in achievements:
        row = [0] * ACHIEVEMENT_FIELDS
        row[0] = a["id"]
        row[1] = FACTIONS[a["faction"]]
        row[2] = UNSET                                   # any map
        row[3] = a["parent"]
        row[4] = add_string(strings, a["title"])
        row[20] = LANG_MASK
        row[21] = add_string(strings, a["description"])
        row[37] = LANG_MASK
        row[38] = a["category"]
        row[39] = a["points"]
        row[40] = order[a["id"]]
        row[41] = a["flags"]
        row[42] = a["icon"]
        row[43] = add_string(strings, reward_text(a))
        row[59] = LANG_MASK if a["reward"] else LANG_MASK_EMPTY
        row[60] = a["count"]
        rows.append(row)

    crit_rows[:] = [r for r in crit_rows if not in_block(r[0], CRITERIA_BLOCK)]
    for a in achievements:
        for i, c in enumerate(a["criteria"], 1):
            row = [0] * CRITERIA_FIELDS
            row[0] = c["id"]
            row[1] = a["id"]
            row[2] = c["type_id"]
            row[3] = c["asset"]
            row[4] = c["quantity"]
            row[9] = add_string(crit_strings, c["text"])
            row[25] = LANG_MASK
            row[26] = c["flags"]
            row[30] = i                                  # Ui_Order
            crit_rows.append(row)

    write_dbc(files[dbc_name("Achievement")], rows, strings, fields)
    write_dbc(files[dbc_name("Achievement_Criteria")], crit_rows, crit_strings, crit_fields)
    return order


# --- SQL ---------------------------------------------------------------------------------------

def sql_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def si(v):
    """A DBC uint32 as the signed int the server's *_dbc columns hold (-1, not 4294967295)."""
    return struct.unpack("<i", struct.pack("<I", v))[0]


def inserts(f, head, lines):
    for i in range(0, len(lines), SQL_CHUNK):
        f.write(head + "\n" + ",\n".join(lines[i:i + SQL_CHUNK]) + ";\n")


def write_sql(path, achievements, criteria, letters, order):
    a_block, c_block = ACHIEVEMENT_BLOCK, CRITERIA_BLOCK
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- mod-retail-achievements: retail's mount achievements, pointed at WotLK content. Generated by\n")
        f.write("-- tools/build_achievements.py from data/achievements.tsv, data/criteria.tsv and data/letters.tsv:\n")
        f.write("-- change those files and run the tool again, don't edit this one.\n")
        f.write("-- Achievements %d-%d, criteria %d-%d. The client has the same rows in the spell patch.\n\n"
                % (*a_block, *c_block))

        f.write("DELETE FROM `achievement_reward` WHERE `ID` BETWEEN %d AND %d;\n" % a_block)
        f.write("DELETE FROM `achievement_criteria_data` WHERE `criteria_id` BETWEEN %d AND %d;\n" % c_block)
        f.write("DELETE FROM `achievement_criteria_dbc` WHERE `ID` BETWEEN %d AND %d;\n" % c_block)
        f.write("DELETE FROM `achievement_dbc` WHERE `ID` BETWEEN %d AND %d;\n" % a_block)
        f.write("DELETE FROM `player_factionchange_achievement` WHERE `alliance_id` BETWEEN %d AND %d;\n\n" % a_block)

        inserts(f, "INSERT INTO `achievement_dbc` (`ID`, `Faction`, `Instance_Id`, `Supercedes`, `Title_Lang_enUS`, `Title_Lang_Mask`, `Description_Lang_enUS`, `Description_Lang_Mask`, `Category`, `Points`, `Ui_Order`, `Flags`, `IconID`, `Reward_Lang_enUS`, `Reward_Lang_Mask`, `Minimum_Criteria`, `Shares_Criteria`) VALUES",
                ["(%d, %d, -1, %d, %s, %d, %s, %d, %d, %d, %d, %d, %d, %s, %d, %d, 0)" % (
                    a["id"], si(FACTIONS[a["faction"]]), a["parent"], sql_str(a["title"]), LANG_MASK,
                    sql_str(a["description"]), LANG_MASK, a["category"], a["points"], order[a["id"]], a["flags"],
                    a["icon"], sql_str(reward_text(a)), LANG_MASK if a["reward"] else LANG_MASK_EMPTY, a["count"])
                 for a in achievements])
        lines, data = [], []
        for a in achievements:
            for i, c in enumerate(a["criteria"], 1):
                lines.append("(%d, %d, %d, %d, %d, %s, %d, %d, %d)" % (
                    c["id"], a["id"], c["type_id"], c["asset"], c["quantity"], sql_str(c["text"]), LANG_MASK,
                    c["flags"], i))
                data += ["(%d, %d, %d, %d, '')" % (c["id"], *d) for d in c["data_rows"]]
        inserts(f, "INSERT INTO `achievement_criteria_dbc` (`ID`, `Achievement_Id`, `Type`, `Asset_Id`, `Quantity`, `Description_Lang_enUS`, `Description_Lang_Mask`, `Flags`, `Ui_Order`) VALUES",
                lines)
        f.write("\n-- Criteria the core only counts with a row here (kills, battleground wins), and class checks.\n")
        inserts(f, "INSERT INTO `achievement_criteria_data` (`criteria_id`, `type`, `value1`, `value2`, `ScriptName`) VALUES", data)
        f.write("\n-- A character that changes faction swaps each Alliance achievement for its Horde twin and back.\n")
        inserts(f, "INSERT INTO `player_factionchange_achievement` (`alliance_id`, `alliance_comment`, `horde_id`, `horde_comment`) VALUES",
                ["(%d, %s, %d, %s)" % (al, sql_str(title), ho, sql_str(title)) for al, ho, title in faction_pairs(achievements)])
        f.write("\n-- The reward mounts, by mail.\n")
        inserts(f, "INSERT INTO `achievement_reward` (`ID`, `TitleA`, `TitleH`, `ItemID`, `Sender`, `Subject`, `Body`, `MailTemplateID`) VALUES",
                ["(%d, 0, 0, %d, %d, %s, %s, 0)" % (
                    a["id"], a["item"], letters[a["letter"]]["sender"], sql_str(letter_text(a, letters, "subject")),
                    sql_str(letter_text(a, letters, "body"))) for a in achievements if a["item"]])
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", required=True, help="the realm's spell patch (Achievement.dbc, Item.dbc, ...)")
    ap.add_argument("--data", default=DATA, help="the folder with the three data files")
    ap.add_argument("--out", required=True, help="the new spell patch")
    ap.add_argument("--sql", help="write the module's world SQL here")
    ap.add_argument("--allow-changes", action="store_true",
                    help="drop or change achievements and criteria an earlier build had (only while no server has them)")
    args = ap.parse_args()

    achievements, criteria, letters = load_data(args.data)
    if args.sql:
        # The SQL file is what the server has; the patch check below only sees an earlier build's rows.
        check_kept(*old_sql_rows(args.sql), achievements, args.sql, args.allow_changes)
    with tempfile.TemporaryDirectory() as tmp:
        files = dbcmpq.unpack(args.patch, tmp)
        order = patch_dbcs(files, achievements, criteria, args)
        dbcmpq.pack(args.out, [(local, name) for name, local in sorted(files.items())])
        print("%s: %d achievements, %d criteria, %d files, %.1f MB" % (
            args.out, len(achievements), len(criteria), len(files), os.path.getsize(args.out) / 1e6))
    if args.sql:
        write_sql(args.sql, achievements, criteria, letters, order)


if __name__ == "__main__":
    main()
