/*
 * mod-retail-achievements
 *
 * The achievements themselves are world database rows (data/sql/db-world). This file adds what
 * the rows can't do on their own:
 *
 * - Catching up. The core's own achievement check at login is switched off, so an achievement
 *   counts only what happens after it exists: a level 80 character would never be a Timerunner,
 *   and a meta over stock achievements earned earlier would never complete. Shortly after each
 *   login of a player, the module's own criteria are checked again (stock ones are left alone;
 *   kill and battleground win criteria can't be, the core only counts them as they happen).
 * - Random bots. They would earn these too and get the reward mounts in the mail, so their
 *   progress on the module's criteria isn't counted at all. Alt bots (a player's own characters
 *   played by mod-playerbots) count like the player.
 * - Missing rewards. When a reward item or mail sender doesn't exist (the collection module isn't
 *   installed, say), the core would complete the achievement and send an empty letter, and the
 *   mount could never be sent again. Those achievements count no progress, and are logged at
 *   startup, until the item is there (after a restart).
 *
 * Progress is held back before it is recorded, not when the achievement would complete: the core
 * never looks at a completed criterion again, so an achievement stopped at completion could
 * never be earned later.
 *
 * AzerothCore looks up a loader symbol derived from the module's folder name: for folder
 * "mod-retail-achievements" that symbol is exactly "Addmod_retail_achievementsScripts". If you clone
 * the repo under a different folder name, rename that function to match.
 *
 * Released under the MIT License.
 */

#include "AchievementMgr.h"
#include "Config.h"
#include "DBCStores.h"
#include "DatabaseEnv.h"
#include "Log.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "WorldSession.h"

#include <atomic>
#include <set>
#include <string>
#include <type_traits>
#include <unordered_set>
#include <utility>

namespace
{
    constexpr uint32 FIRST_ACHIEVEMENT = 9300;
    constexpr uint32 LAST_ACHIEVEMENT = 9799;

    bool IsOurs(uint32 achievementId)
    {
        return achievementId >= FIRST_ACHIEVEMENT && achievementId <= LAST_ACHIEVEMENT;
    }

    // Filled once at startup and only read after that (from the map threads too), so they need no
    // lock: `ready` is set last, and until then nothing of ours counts.
    std::atomic<bool> ready{ false };
    std::set<uint32> loginTypes;                   // criteria types the login check goes through
    std::unordered_set<uint32> heldBack;           // achievements whose reward is missing
    std::unordered_set<uint32> randomBotAccounts;  // mod-playerbots' random bot accounts

    // The criteria type the login check is going through on this thread (0 when it isn't): of
    // that type, only the module's criteria are looked at. Other types the check sets off on the
    // way (the achievement points of what it completes) count as usual.
    thread_local uint32 loginCheckType = 0;

    // Bots are sessions without a socket. AzerothCore marks them with WorldSession::IsHeadless();
    // older playerbots core forks have WorldSession::IsBot() instead, and older stock cores have
    // neither. Looking for both at compile time lets the module build on all of them.
    template <typename Session, typename = void>
    struct HasIsHeadless : std::false_type { };

    template <typename Session>
    struct HasIsHeadless<Session, std::void_t<decltype(std::declval<Session&>().IsHeadless())>> : std::true_type { };

    template <typename Session, typename = void>
    struct HasIsBot : std::false_type { };

    template <typename Session>
    struct HasIsBot<Session, std::void_t<decltype(std::declval<Session&>().IsBot())>> : std::true_type { };

    template <typename Session>
    bool IsBotSession(Session* session)
    {
        if constexpr (HasIsHeadless<Session>::value)
            return session->IsHeadless();
        else if constexpr (HasIsBot<Session>::value)
            return session->IsBot();
        else
            return false;
    }

    // A random bot is a session without a socket on one of mod-playerbots' own accounts. A
    // player's alt bots are headless too, but on the player's account.
    bool IsRandomBot(Player* player)
    {
        WorldSession* session = player ? player->GetSession() : nullptr;
        return !session || (IsBotSession(session) && randomBotAccounts.count(session->GetAccountId()));
    }

    // The types a check at login can count. Kills and battleground wins only count as they
    // happen (the core skips them without the creature or map of the moment).
    bool CountsAtLogin(uint32 type)
    {
        return type != ACHIEVEMENT_CRITERIA_TYPE_KILL_CREATURE && type != ACHIEVEMENT_CRITERIA_TYPE_WIN_BG;
    }

    std::string LikePrefix(std::string prefix)
    {
        std::string out;
        for (char c : prefix)
        {
            if (c == '\\')
                out += "\\\\\\\\";              // a literal backslash: escaped for LIKE, then for the string
            else if (c == '%' || c == '_')
                out += std::string("\\\\") + c;   // escaped for LIKE (the backslash itself for the string)
            else if (c == '\'')
                out += "''";
            else
                out += c;
        }
        return out + "%";
    }
}

class RetailAchievementsWorld : public WorldScript
{
public:
    RetailAchievementsWorld() : WorldScript("RetailAchievementsWorld", { WORLDHOOK_ON_STARTUP }) { }

    void OnStartup() override
    {
        for (uint32 id = 0; id < sAchievementCriteriaStore.GetNumRows(); ++id)
        {
            AchievementCriteriaEntry const* criteria = sAchievementCriteriaStore.LookupEntry(id);
            if (criteria && IsOurs(criteria->referredAchievement) && CountsAtLogin(criteria->requiredType))
                loginTypes.insert(criteria->requiredType);
        }

        // achievement_reward as it is in the database: the core has already zeroed the item or
        // sender it couldn't find in its own copy.
        std::string missing;
        if (QueryResult result = WorldDatabase.Query("SELECT `ID`, `ItemID`, `Sender` FROM `achievement_reward` WHERE `ID` BETWEEN {} AND {}",
            FIRST_ACHIEVEMENT, LAST_ACHIEVEMENT))
        {
            do
            {
                Field* fields = result->Fetch();
                uint32 achievementId = fields[0].Get<uint32>();
                uint32 itemId = fields[1].Get<uint32>();
                uint32 sender = fields[2].Get<uint32>();
                if ((itemId && !sObjectMgr->GetItemTemplate(itemId)) || (sender && !sObjectMgr->GetCreatureTemplate(sender)))
                {
                    heldBack.insert(achievementId);
                    missing += (missing.empty() ? "" : ", ") + std::to_string(achievementId);
                }
            } while (result->NextRow());
        }

        // mod-playerbots names its random bot accounts with this prefix (its own setting, read
        // from its config when it is installed). Accounts it makes later count after a restart.
        std::string prefix = sConfigMgr->GetOption<std::string>("AiPlayerbot.RandomBotAccountPrefix", "rndbot", false);
        if (!prefix.empty())
            if (QueryResult result = LoginDatabase.Query("SELECT `id` FROM `account` WHERE `username` LIKE '{}'", LikePrefix(prefix)))
                do
                    randomBotAccounts.insert(result->Fetch()[0].Get<uint32>());
                while (result->NextRow());

        ready = true;

        if (!missing.empty())
            LOG_ERROR("module", "mod-retail-achievements: the reward item or mail sender of achievements {} doesn't exist; "
                "nobody can earn them until it does and the server restarts (is wow-mod-retail-collection installed?)", missing);
        LOG_INFO("module", "mod-retail-achievements: {} criteria types checked at login, {} achievements held back, {} random bot accounts",
            loginTypes.size(), heldBack.size(), randomBotAccounts.size());
    }
};

class RetailAchievementsCriteria : public AchievementScript
{
public:
    RetailAchievementsCriteria() : AchievementScript("RetailAchievementsCriteria", { ACHIEVEMENTHOOK_CAN_CHECK_CRITERIA }) { }

    bool CanCheckCriteria(AchievementMgr* mgr, AchievementCriteriaEntry const* criteria) override
    {
        if (!IsOurs(criteria->referredAchievement))
            return !loginCheckType || criteria->requiredType != loginCheckType;

        return ready && !heldBack.count(criteria->referredAchievement) && !IsRandomBot(mgr->GetPlayer());
    }
};

class RetailAchievementsPlayer : public PlayerScript
{
public:
    RetailAchievementsPlayer() : PlayerScript("RetailAchievementsPlayer", { PLAYERHOOK_ON_LOGIN }) { }

    void OnPlayerLogin(Player* player) override
    {
        if (!ready || loginTypes.empty() || IsRandomBot(player))
            return;

        // A moment after login, like the core's own check: done while the player is still
        // loading, the client wouldn't hear about what was earned.
        player->m_Events.AddEventAtOffset([player]
        {
            auto check = [player](uint32 type)
            {
                loginCheckType = type;
                player->UpdateAchievementCriteria(AchievementCriteriaTypes(type));
                loginCheckType = 0;
            };
            for (uint32 type : loginTypes)
                check(type);
            // Metas last, so the parts earned just now count too.
            check(ACHIEVEMENT_CRITERIA_TYPE_COMPLETE_ACHIEVEMENT);
        }, 1s);
    }
};

void Addmod_retail_achievementsScripts()
{
    new RetailAchievementsWorld();
    new RetailAchievementsCriteria();
    new RetailAchievementsPlayer();
}
