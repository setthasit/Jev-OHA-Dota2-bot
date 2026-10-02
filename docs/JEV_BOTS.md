# Jev Bots Setup and Lobby Guide

This guide gets you a Dota 2 custom lobby where one or both teams run this repo's bots. The bots ask a local bridge process for decisions from TypeSafe's Jev model. The guide also lists the lobby rules that keep every bot free of resource bonuses.

The in-game code that calls the bridge is not in this checkout yet, so the log and outage sections describe intended behaviour.

The shortest path, from the repo root:

```sh
mise install
export TYPESAFE_API_KEY="<your key>"
cd bridge
mise exec -- uv run jevbot install --dota-dir "<path to dota 2 beta>"
mise exec -- uv run jevbot serve
```

Then follow [Lobby](#lobby). This short path skips Setup step 5 and [Fair Play](#fair-play). Read both before you trust a result.

---

## Prerequisites

- Dota 2 installed through Steam.
- A checkout of this repository. Keep it in place after installing. The install is a link to this checkout, not a copy.
- mise. It installs the pinned Python and uv from `mise.toml`.
- A TypeSafe API key.

The Windows steps are untested. No test in this repo covers the Windows path of `jevbot install`.

---

## Setup

1. Install the pinned tools. Run this at the repo root.

   ```sh
   mise install
   ```

2. Set `TYPESAFE_API_KEY` in the shell that will run the bridge. Use your own key in place of the placeholder. Do not write the key into any file in this repo.

   macOS and Linux:

   ```sh
   export TYPESAFE_API_KEY="<your key>"
   ```

   Windows PowerShell:

   ```powershell
   $env:TYPESAFE_API_KEY = "<your key>"
   ```

3. Find your `dota 2 beta` directory. In your Steam Library, right-click Dota 2. Choose Properties > Installed Files > Browse. The usual locations are:

   | OS | Path |
   |---|---|
   | Windows | `C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta` |
   | macOS | `~/Library/Application Support/Steam/steamapps/common/dota 2 beta` |
   | Linux | `~/.steam/steam/steamapps/common/dota 2 beta` |

4. Install the bots. Run this from `bridge/`. Quote the path, because it contains spaces.

   ```sh
   mise exec -- uv run jevbot install --dota-dir "<path to dota 2 beta>"
   ```

   On macOS with the usual location, that is:

   ```sh
   mise exec -- uv run jevbot install --dota-dir "$HOME/Library/Application Support/Steam/steamapps/common/dota 2 beta"
   ```

   The command links `<dota-dir>/game/dota/scripts/vscripts/bots` to this repo's `bots/`. It prints `installed <link> -> <repo bots>`. Running it again prints `already installed`. If it refuses, see [Troubleshooting](#troubleshooting).

5. Check for a leftover customize file from an earlier OHA setup.

   ```
   <dota-dir>/game/dota/scripts/vscripts/game/Customize/general.lua
   ```

   If that file exists, see [Leftover Customize Folder](#leftover-customize-folder).

6. Start the bridge. Run this from `bridge/`. Leave the terminal open for the whole game.

   ```sh
   mise exec -- uv run jevbot serve
   ```

   The bridge logs `Listening on http://127.0.0.1:8765`. Stop it with Ctrl+C.

7. Optional. Check the bridge from a second terminal.

   ```sh
   curl http://127.0.0.1:8765/health
   ```

   A running bridge answers `{"status":"ok","game_open":false}`.

---

## Lobby

The bot script labels, the per-team script and difficulty selectors, the empty-slot behaviour, and the Workshop pairing in this guide come from the Dota 2 client and are not checked by this repo.

1. Start Dota 2 and create a **Custom Lobby**.
2. Select **Local Host** as the server location.
3. Leave `Enable Cheats` unchecked.
4. Choose All Pick as the game mode.
5. Choose the bot script for each team from the table below.
6. Choose a bot difficulty for each team. See [Fair Play](#fair-play).
7. Decide who plays. Take a slot on a team to play yourself. For a game with 10 bots and no humans, do not join either team. Bots fill the empty slots.
8. Start the game. The bots pick their heroes and play.

With this repo's default settings, bots that run this repo's script have names ending in `.OHA`. Stock OHA bots carry the same suffix, so the name does not separate the two. Stock Valve bots carry no `.OHA` suffix. That is client behaviour and is not checked by this repo.

| Team should run | Bot script to select for that team |
|---|---|
| The new bots from this repo | "Local dev script" |
| Stock Valve bots | "Default bots" |
| Stock OHA | The **Open Hyper AI** Workshop item. Subscribe on the [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3246316298) first. |

Common setups:

| Goal | Radiant | Dire |
|---|---|---|
| New bots against stock Valve bots | "Default bots" | "Local dev script" |
| New bots on both teams | "Local dev script" | "Local dev script" |
| New bots against stock OHA | **Open Hyper AI** | "Local dev script" |

Swap the columns to put the new bots on Radiant.

To confirm the bots reach the bridge, see [Logs](#logs).

---

## Fair Play

A fair game means no bot receives gold, XP, levels, stats, armor, magic resistance, or neutral items from anything other than normal play. Three host choices decide that.

1. Never load FretBots or Buff. Both scripts ship in `bots/`. Both give bots bonus gold, XP, and neutral items. FretBots also gives levels, stats, armor, and magic resistance. They run only when someone loads them from the console. Do not run either of these commands:

   ```
   script_reload_code bots/fretbots
   script_reload_code bots/Buff/buff
   ```

   Do not run any other `script_reload_code` command during the game. Ignore any bot chat line that suggests enabling FretBots.

   The FretBots command comes from the OHA manual installation guide linked in `README.md` and is not checked by this repo.

2. Leave `Enable Cheats` unchecked. Never run this console command:

   ```
   sv_cheats 1
   ```

   Buff is documented as needing cheats. See `bots/Buff/README.md`.

3. Choose a bot difficulty that gives bots no resource bonus. Use the same rule for every team, stock Valve bots included. The bot API lists five levels: `DIFFICULTY_PASSIVE`, `DIFFICULTY_EASY`, `DIFFICULTY_MEDIUM`, `DIFFICULTY_HARD`, and `DIFFICULTY_UNFAIR`. This repo does not establish which of them carry a gold or XP bonus. Use a level you have confirmed carries none.

The `Fretbots` table in `bots/Customize/general.lua` has no effect unless FretBots is loaded.

---

## Logs

A new file appears in `bridge/logs/` once the new bots send their first request. That file confirms the bots reach the bridge.

If no file appears, check these:

1. The link is installed. Setup step 4 printed `installed <link> -> <repo bots>` or `already installed`.
2. "Local dev script" is selected for that team.
3. The bridge was started from `bridge/` before the game.
4. The in-game code that calls the bridge is in your checkout. Without it, no file is expected.

The bridge writes one file per game to `bridge/logs/`. The file is named `game-<UTC timestamp>.jsonl`, for example `game-20261002T031500.jsonl`. Each line is one JSON object. The directory is ignored by git.

The path is `logs` relative to the directory where you start the bridge. Set `JEVBOT_LOG_DIR` to write somewhere else.

Each model request is a line with `"type": "call"`. It carries the `team`, the `player`, the `game_time`, and a `status`:

| `status` | Meaning |
|---|---|
| `ok` | The model answered. |
| `timeout` | The model did not answer in time. |
| `rate_limited` | TypeSafe rate-limited the request. |
| `error` | The request failed for another reason. A missing or invalid API key shows up here. |
| `budget` | The bridge's own per-second request or token limit refused the request. |
| `unknown_kind` | The bridge does not know this kind of request. |

Every `call` and `event` line carries `team`. The `team` value is 2 for Radiant and 3 for Dire. With the new bots on one team only, every such line has the same `team` value. With the new bots on both teams, the lines carry both 2 and 3.

The last line of a finished game is a `spend_summary` with `calls`, `input_tokens`, `cost_usd`, and `reason`. The `reason` says how the game log closed:

| `reason` | Meaning |
|---|---|
| `game_end` | The bots reported the end of the game. |
| `idle` | No request arrived for 120 seconds. |
| `reset` | The game clock jumped back by more than 60 seconds. A new game log then opens. |
| `shutdown` | The bridge was stopped. |

---

## Outage Messages

The in-game code that sends these notices is not in this checkout yet, so this section states the intended behaviour.

The new bots keep playing when the model is unreachable. They report it in their own team's chat.

| Team chat message | Meaning |
|---|---|
| `AI offline: fallback logic` | No model request from that team has succeeded for 10 seconds of game time. That team's bots now play on fallback logic. One bot sends this once. It is not repeated until the model has recovered. |
| `AI online` | A model request succeeded after the offline message. One bot on that team sends this once. |

If the bridge is not running when the game clock reaches 0:00, every new bot plays on fallback logic. The offline message appears by 0:10.

When you see `AI offline: fallback logic`:

1. Check that the bridge terminal is still running.
2. Check the bridge from a second terminal.

   ```sh
   curl http://127.0.0.1:8765/health
   ```

3. Look for `Jev call failed` in the bridge terminal. Then check that `TYPESAFE_API_KEY` is set in that shell. The bridge starts without a key, but every model request then fails.
4. Read the `status` of the latest `call` lines in the game log.

---

## Leftover Customize Folder

An earlier OHA setup can leave this file behind:

```
<dota-dir>/game/dota/scripts/vscripts/game/Customize/general.lua
```

If that file exists, it replaces this repo's `bots/Customize/general.lua` for every script that loads settings through `bots/FunLib/custom_loader.lua`. Examples are `bots/hero_selection.lua`, `bots/FunLib/aba_chat.lua`, and `bots/FunLib/localization.lua`. `bots/FunLib/jmz_func.lua` loads it the same way and shares it with other scripts as `J.Customize`.

Scripts that require `bots/Customize/general.lua` directly keep reading this repo's file. Examples are `bots/mode_farm_generic.lua` and `bots/FunLib/aba_push.lua`. Through that direct path they read only `Enable` and `ThinkLess`.

A leftover file controls these settings:

| Setting | Effect |
|---|---|
| `Enable` | When false, hero selection and the chat language code ignore the leftover settings. |
| `Allow_Trash_Talk`, `Trash_Talk_Level` | Bot taunts, replies to player chat, and all-chat odds lines. |
| `Localization` | Bot chat language. |
| `Radiant_Heros`, `Dire_Heros` | Hero picks. |
| `Ban`, `Strict_Ban_Match` | Hero bans. |
| `Allow_Repeated_Heroes`, `Weak_Hero_Cap`, `Weak_Penalty` | Rules for random hero picks. |
| `Radiant_Names`, `Dire_Names` | Bot names. |
| `Allow_AI_GPT_Response`, `Fretbots` | Read only by FretBots. No effect unless FretBots is loaded. |

Move the `Customize` folder out of `vscripts/game`. If you keep it instead, check every setting in the table. Set both of these to false in it.

```lua
Customize.Allow_Trash_Talk = false
Customize.Allow_AI_GPT_Response = false
```

Keeping the folder also keeps any `Customize/hero/<hero>.lua` file in it. Each such file overrides that hero's ability, talent, and item builds when it sets `Enable = true`.

---

## Troubleshooting

`jevbot install` and `jevbot uninstall` exit with code 2 when they refuse. They change nothing in that case. They exit with code 1 when the operating system rejects the change.

| Message | Meaning and fix |
|---|---|
| `<dota-dir> is not a directory, check --dota-dir` | The path is wrong. Check the quoting and the spelling. |
| `... does not look like a Dota 2 install` | The path exists but is not the `dota 2 beta` directory. |
| `.../vscripts/bots is a link to <target>, leaving it untouched` | Another bot script is linked there. Follow the steps below the table. |
| `.../vscripts/bots is a real directory, leaving it untouched` | A real `bots` folder is there. Decide first whether you still need its contents. Move it elsewhere yourself. Then repeat Setup step 4. |
| `.../vscripts/bots is a file, leaving it untouched` | A file named `bots` is there. Decide first whether you still need it. Move it elsewhere yourself. Then repeat Setup step 4. |
| `<repo bots> is not a directory, jevbot must be installed from the repo checkout` | `jevbot` is not running from this checkout. Run the command from `bridge/` in the checkout. |
| `.../vscripts/bots does not exist, nothing to uninstall` | Nothing is installed at that path. |
| `jevbot: install failed: ...` or `jevbot: uninstall failed: ...` | The operating system rejected the change. The text after the colon gives the reason. Exit code 1. |
| `jevbot: cannot listen on 127.0.0.1:8765: ...` | Usually another process holds the port. The text after the last colon gives the reason. Stop that process. Then start the bridge again. |

When the message says `is a link to <target>`:

1. Decide whether you still need the script at `<target>`. The OHA quick-install scripts create such a link.
2. If you do not need it, remove the link yourself. The "Uninstall" part of [bots/Install-to-vscript/README.md](../bots/Install-to-vscript/README.md) describes how.
3. Repeat Setup step 4.

---

## Uninstall

Run this from `bridge/`.

```sh
mise exec -- uv run jevbot uninstall --dota-dir "<path to dota 2 beta>"
```

It removes the link and prints `uninstalled <link>`. It only removes a link that points at this repo's `bots/`. This checkout and your Dota 2 files are not touched.
