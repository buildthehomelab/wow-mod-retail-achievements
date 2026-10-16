-- acore_world. Run by hand to remove mod-retail-achievements' rows: achievements 9300-9799 and
-- their criteria 20000-23999.
-- Earned achievements and their progress are lost for good: the core deletes the achievements it
-- no longer knows from every character at startup, and their criteria progress at login. The
-- mounts already mailed stay learned. Put the spell patch back to a build without the
-- achievements as well.
DELETE FROM `player_factionchange_achievement` WHERE `alliance_id` BETWEEN 9300 AND 9799;
DELETE FROM `achievement_reward` WHERE `ID` BETWEEN 9300 AND 9799;
DELETE FROM `achievement_criteria_data` WHERE `criteria_id` BETWEEN 20000 AND 23999;
DELETE FROM `achievement_criteria_dbc` WHERE `ID` BETWEEN 20000 AND 23999;
DELETE FROM `achievement_dbc` WHERE `ID` BETWEEN 9300 AND 9799;
