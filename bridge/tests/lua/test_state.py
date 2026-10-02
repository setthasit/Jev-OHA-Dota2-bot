from typing import Any

import pytest

from . import harness

STATE = harness.load_expr("bots/FunLib/jev/state")
AXE = "npc_dota_hero_axe"
LION = "npc_dota_hero_lion"
LINA = "npc_dota_hero_lina"
PUDGE = "npc_dota_hero_pudge"
LINA_IN_MID_LANE = {"hero": LINA, "region": "mid_lane", "hp": "medium", "level": 9}
LINA_LAST_SEEN_IN_TOP_LANE = {"hero": LINA, "last_seen_region": "top_lane", "seconds_since_seen": 42}
TIERS = {"t1", "t2", "t3"}
TEAM_MACRO = "State.TeamMacro(TEAM_RADIANT)"
WORLD_STUBS = (
    f"""
local AXE_ID, LION_ID, LINA_ID, PUDGE_ID = 0, 1, 5, 6
local hero_names = {{ [AXE_ID] = '{AXE}', [LION_ID] = '{LION}', [LINA_ID] = '{LINA}', [PUDGE_ID] = '{PUDGE}' }}
"""
    + """
UNIT_LIST_ENEMY_HEROES = 'enemy_heroes'
TOWER_TOP_1, TOWER_TOP_2, TOWER_TOP_3 = 0, 1, 2
TOWER_MID_1, TOWER_MID_2, TOWER_MID_3 = 3, 4, 5
TOWER_BOT_1, TOWER_BOT_2, TOWER_BOT_3 = 6, 7, 8

local player_ids = { [TEAM_RADIANT] = { AXE_ID, LION_ID }, [TEAM_DIRE] = { LINA_ID, PUDGE_ID } }
local now = 12 * 60 + 34
local deaths_of_dead_players = {}
local last_seen = {}
local enemy_hero_units = {}
local top_lane_sighting = { location = Vector(-6000, 6000, 0), time_since_seen = 42.9 }

local function hero(unit)
  unit.GetPlayerID = function() return unit.player_id end
  unit.CanBeSeen = function() return true end
  unit.IsAlive = function() return true end
  unit.GetLocation = function() return unit.location end
  unit.GetLevel = function() return unit.level end
  unit.GetRespawnTime = function() return unit.respawn_time end
  return unit
end

local function lina_in_mid_lane()
  return hero({ player_id = LINA_ID, location = Vector(0, 0, 0), level = 9, hp = 0.5 })
end

local function standing_tower(tower)
  tower.IsAlive = function() return true end
  tower.CanBeSeen = function() return true end
  tower.GetLocation = function() return tower.location end
  return tower
end

local forbidden_reads = {}

local function handle_exposing_only(label, members)
  return setmetatable(members, {
    __index = function(_, key)
      forbidden_reads[#forbidden_reads + 1] = label .. '.' .. tostring(key)
      error('`' .. tostring(key) .. '` was read on the ' .. label .. ' handle', 0)
    end,
  })
end

local function fogged(label, unit)
  for member in pairs(unit) do unit[member] = nil end
  unit.CanBeSeen = function() return false end
  return handle_exposing_only(label, unit)
end

local always_fogged_enemy_hero = fogged('always fogged enemy hero', {})

local function fog_every_enemy_hero_unit()
  for _, unit in ipairs(enemy_hero_units) do fogged('enemy hero that became fogged', unit) end
end

local axe = hero({ player_id = AXE_ID, location = Vector(-7000, -7000, 0), level = 7, hp = 0.9, position = 3 })
local lion = hero({ player_id = LION_ID, location = Vector(-7000, -7000, 0), level = 5, hp = 0.9, position = 5 })
local allies = { axe, lion }

local towers = { [TEAM_RADIANT] = {}, [TEAM_DIRE] = {} }
for tower_id = TOWER_TOP_1, TOWER_BOT_3 do
  towers[TEAM_RADIANT][tower_id] = standing_tower({ location = Vector(-5000, -5000, 0), hp = 1 })
  towers[TEAM_DIRE][tower_id] = standing_tower({ location = Vector(5000, 5000, 0), hp = 1 })
end

function GetTeam() return TEAM_RADIANT end
function GetOpposingTeam() return TEAM_DIRE end
function GetTeamPlayers(team) return player_ids[team] end
function GetTeamMember(slot) return allies[slot] end
function GetSelectedHeroName(player_id) return hero_names[player_id] end
function GetUnitList(kind)
  local units = { always_fogged_enemy_hero }
  for _, unit in ipairs(enemy_hero_units) do units[#units + 1] = unit end
  units[#units + 1] = always_fogged_enemy_hero
  return ({ [UNIT_LIST_ENEMY_HEROES] = units })[kind]
end
function IsHeroAlive(player_id) return deaths_of_dead_players[player_id] == nil end
function GetHeroDeaths(player_id) return deaths_of_dead_players[player_id] or 0 end
function GetHeroLastSeenInfo(player_id) return last_seen[player_id] end
function GetTower(team, tower_id) return towers[team][tower_id] end
function DotaTime() return now end

package.loaded['bots/FunLib/jmz_func'] = {
  GetPosition = function(unit) return unit.position end,
  GetHP = function(unit) return unit.hp end,
  IsSuspiciousIllusion = function(unit) return unit.is_illusion == true end,
}
"""
    + f"local State = {STATE}\n"
)


def fog_checked_team_macro_before_and_after_fog(arrange: str = "", once_fogged: str = "") -> tuple[Any, Any]:
    state, state_once_fogged, forbidden_reads = harness.run(
        f"""
        {arrange}
        local state = {TEAM_MACRO}
        fog_every_enemy_hero_unit()
        {once_fogged}
        return {{ state, {TEAM_MACRO}, forbidden_reads }}
        """,
        WORLD_STUBS,
    )
    state_without_enemy_units, forbidden_reads_without_enemy_units = harness.run(
        f"""
        {arrange}
        enemy_hero_units = {{}}
        {once_fogged}
        return {{ {TEAM_MACRO}, forbidden_reads }}
        """,
        WORLD_STUBS,
    )
    assert not forbidden_reads
    assert not forbidden_reads_without_enemy_units
    assert state_once_fogged == state_without_enemy_units, (
        "state after fogging every enemy handle differs from the state with no enemy units"
    )
    return state, state_once_fogged


def fog_checked_team_macro(arrange: str = "") -> Any:
    state, _ = fog_checked_team_macro_before_and_after_fog(arrange)
    return state


def test_state_carries_the_game_clock_the_phase_and_every_team_section():
    state = fog_checked_team_macro()

    assert set(state) == {"time", "phase", "allies", "enemies_visible", "enemies_missing", "enemies_dead", "towers"}
    assert state["time"] == "12:34"
    assert state["phase"] == "mid"


@pytest.mark.parametrize(
    ("now", "time", "phase"),
    [
        (-65, "-01:05", "laning"),
        (599, "09:59", "laning"),
        (600, "10:00", "mid"),
        (1799, "29:59", "mid"),
        (1800, "30:00", "late"),
    ],
)
def test_game_time_is_a_zero_padded_clock_within_its_phase(now, time, phase):
    state = fog_checked_team_macro(f"now = {now}")

    assert (state["time"], state["phase"]) == (time, phase)


def test_living_ally_is_reported_with_its_hp_bucket_and_no_respawn_wait():
    axe, _ = fog_checked_team_macro()["allies"]

    assert axe == {
        "hero": AXE,
        "position": 3,
        "region": "radiant_base",
        "hp": "high",
        "level": 7,
        "alive": True,
        "respawn_seconds": 0,
    }


def test_team_slot_without_a_hero_handle_is_left_out_of_allies():
    state = fog_checked_team_macro("allies[2] = nil")

    assert [ally["hero"] for ally in state["allies"]] == [AXE]


def test_enemy_in_the_unit_list_is_visible_with_an_hp_bucket():
    state = fog_checked_team_macro("enemy_hero_units = { lina_in_mid_lane() }")

    assert state["enemies_visible"] == [LINA_IN_MID_LANE]
    assert state["enemies_missing"] == [{"hero": PUDGE}]
    assert state["enemies_dead"] == []


def test_two_visible_units_of_one_player_are_reported_once_as_the_first_unit():
    state = fog_checked_team_macro("""
    enemy_hero_units = {
      lina_in_mid_lane(),
      hero({ player_id = LINA_ID, location = Vector(-6000, 6000, 0), level = 3, hp = 0.9 }),
    }
    """)

    assert state["enemies_visible"] == [LINA_IN_MID_LANE]


def test_enemy_absent_from_the_unit_list_is_missing_with_only_its_last_sighting():
    state = fog_checked_team_macro("last_seen[LINA_ID] = { top_lane_sighting }")

    assert state["enemies_missing"] == [LINA_LAST_SEEN_IN_TOP_LANE, {"hero": PUDGE}]
    assert state["enemies_visible"] == []
    assert state["enemies_dead"] == []


def test_enemy_with_several_sightings_is_missing_at_the_first_one():
    state = fog_checked_team_macro("""
    last_seen[LINA_ID] = { top_lane_sighting, { location = Vector(0, 0, 0), time_since_seen = 7 } }
    """)

    assert state["enemies_missing"] == [LINA_LAST_SEEN_IN_TOP_LANE, {"hero": PUDGE}]


def test_suspected_illusion_is_skipped_and_read_no_further_than_the_illusion_check():
    state = fog_checked_team_macro("""
    enemy_hero_units = {
      handle_exposing_only('suspected illusion', {
        is_illusion = true,
        CanBeSeen = function() return true end,
        IsAlive = function() return true end,
      }),
    }
    """)

    assert state["enemies_visible"] == []
    assert state["enemies_missing"] == [{"hero": LINA}, {"hero": PUDGE}]


def test_suspected_illusion_beside_a_tower_is_not_counted_near_it():
    state = fog_checked_team_macro("""
    towers[TEAM_DIRE][TOWER_MID_1].location = Vector(0, 0, 0)
    enemy_hero_units = {
      handle_exposing_only('suspected illusion', {
        is_illusion = true,
        CanBeSeen = function() return true end,
        IsAlive = function() return true end,
        GetLocation = function() return Vector(0, 0, 0) end,
      }),
    }
    """)

    assert state["towers"]["enemy"]["mid"]["t1"]["enemy_heroes_near"] == 0


def test_dead_enemy_is_only_under_dead_and_its_handle_is_read_no_further_than_whether_it_is_alive():
    state = fog_checked_team_macro("""
    deaths_of_dead_players[LINA_ID] = 1
    enemy_hero_units = {
      handle_exposing_only('dead enemy hero', {
        CanBeSeen = function() return true end,
        IsAlive = function() return false end,
      }),
    }
    last_seen[LINA_ID] = { top_lane_sighting }
    """)

    assert state["enemies_dead"] == [{"hero": LINA}]
    assert state["enemies_missing"] == [{"hero": PUDGE}]
    assert state["enemies_visible"] == []


def test_dead_enemy_with_a_visible_living_unit_is_only_under_dead():
    state = fog_checked_team_macro("""
    deaths_of_dead_players[LINA_ID] = 1
    enemy_hero_units = { lina_in_mid_lane() }
    """)

    assert state["enemies_dead"] == [{"hero": LINA}]
    assert state["enemies_visible"] == []
    assert state["enemies_missing"] == [{"hero": PUDGE}]


def test_enemy_that_dies_after_being_visible_is_only_under_dead_once_fogged():
    state, state_once_fogged = fog_checked_team_macro_before_and_after_fog(
        "enemy_hero_units = { lina_in_mid_lane() }",
        once_fogged="deaths_of_dead_players[LINA_ID] = 1",
    )

    assert state["enemies_visible"] == [LINA_IN_MID_LANE]
    assert state_once_fogged["enemies_dead"] == [{"hero": LINA}]
    assert state_once_fogged["enemies_missing"] == [{"hero": PUDGE}]


def test_dead_ally_is_not_alive_with_respawn_seconds_and_no_hp():
    _, lion = fog_checked_team_macro("""
    deaths_of_dead_players[LION_ID] = 1
    lion.respawn_time = 40
    """)["allies"]

    assert lion == {
        "hero": LION,
        "position": 5,
        "region": "radiant_base",
        "level": 5,
        "alive": False,
        "respawn_seconds": 40,
    }


def test_dead_ally_respawn_seconds_count_down_to_zero_and_restart_at_the_next_death():
    script = f"""
    local function lion_respawn_seconds() return {TEAM_MACRO}.allies[2].respawn_seconds end
    lion.respawn_time = 40

    deaths_of_dead_players[LION_ID] = 1
    local at_death = lion_respawn_seconds()
    now = now + 15
    local after_15_seconds = lion_respawn_seconds()
    now = now + 60
    local past_the_respawn_time = lion_respawn_seconds()

    deaths_of_dead_players[LION_ID] = 2
    local at_the_next_death = lion_respawn_seconds()

    return {{ at_death, after_15_seconds, past_the_respawn_time, at_the_next_death }}
    """

    assert harness.run(script, WORLD_STUBS) == [40, 25, 0, 40]


def test_team_macro_for_a_team_other_than_the_bots_own_returns_nothing():
    assert harness.run("return State.TeamMacro(TEAM_DIRE)", WORLD_STUBS) is None


@pytest.mark.parametrize(
    "last_seen_info",
    [
        pytest.param("nil", id="no_record"),
        pytest.param("{}", id="empty_record"),
        pytest.param("{ { time_since_seen = 5 } }", id="no_location"),
        pytest.param("{ { location = Vector(0, 0, 0) } }", id="no_time"),
        pytest.param("{ { location = Vector(0, 0, 0), time_since_seen = math.huge } }", id="infinite_time"),
        pytest.param("{ { location = Vector(0 / 0, 0 / 0, 0), time_since_seen = 5 } }", id="nan_location"),
    ],
)
def test_enemy_with_a_missing_or_incomplete_last_sighting_is_missing_by_hero_only_once_fogged(last_seen_info):
    _, state_once_fogged = fog_checked_team_macro_before_and_after_fog(f"""
    enemy_hero_units = {{ lina_in_mid_lane() }}
    last_seen[LINA_ID] = {last_seen_info}
    """)

    assert state_once_fogged["enemies_missing"] == [{"hero": LINA}, {"hero": PUDGE}]


def test_enemy_with_a_complete_last_sighting_is_missing_with_only_that_sighting_once_fogged():
    _, state_once_fogged = fog_checked_team_macro_before_and_after_fog("""
    enemy_hero_units = { lina_in_mid_lane() }
    last_seen[LINA_ID] = { top_lane_sighting }
    """)

    assert state_once_fogged["enemies_missing"] == [LINA_LAST_SEEN_IN_TOP_LANE, {"hero": PUDGE}]


@pytest.mark.parametrize(
    ("x", "y", "region"),
    [
        (0, 0, "mid_lane"),
        (-6000, 6000, "top_lane"),
        (0, -6000, "bot_lane"),
        (0, -4000, "radiant_jungle"),
        (0, 5000, "dire_jungle"),
        (-7000, -7000, "radiant_base"),
        (7000, 7000, "dire_base"),
        pytest.param(1499, 0, "mid_lane", id="x_just_west_of_a_cell_edge"),
        pytest.param(1500, 0, "dire_jungle", id="x_on_a_cell_edge_is_in_the_east_cell"),
        pytest.param(0, -1500, "mid_lane", id="y_on_a_cell_edge_is_in_the_north_cell"),
        pytest.param(0, -1501, "radiant_jungle", id="y_just_south_of_a_cell_edge"),
        pytest.param(-2984, 2349, "roshan_pit", id="north_west_pit_centre"),
        pytest.param(2980, -2816, "roshan_pit", id="south_east_pit_centre"),
        pytest.param(-2384, 2949, "roshan_pit", id="pit_corner_600_from_its_centre"),
        pytest.param(-2383, 2349, "river", id="x_601_from_the_pit_centre"),
        pytest.param(-2984, 2950, "river", id="y_601_from_the_pit_centre"),
        pytest.param(99999, 0, "dire_jungle", id="east_of_the_map_clamps_to_the_edge"),
        pytest.param(-99999, 0, "radiant_jungle", id="west_of_the_map_clamps_to_the_edge"),
    ],
)
def test_region_names_the_map_area_of_a_coordinate(x, y, region):
    assert harness.run(f"return {STATE}.Region({x}, {y})") == region


def test_towers_are_grouped_by_side_then_lane_then_tier():
    state = fog_checked_team_macro()

    tiers_by_lane_by_side = {
        side: {lane: set(towers_by_tier) for lane, towers_by_tier in towers_by_lane.items()}
        for side, towers_by_lane in state["towers"].items()
    }
    assert tiers_by_lane_by_side == {
        "allied": {"top": TIERS, "mid": TIERS, "bot": TIERS},
        "enemy": {"top": TIERS, "mid": TIERS, "bot": TIERS},
    }


@pytest.mark.parametrize(
    ("tower_id", "lane", "tier"),
    [
        ("TOWER_TOP_1", "top", "t1"),
        ("TOWER_TOP_2", "top", "t2"),
        ("TOWER_TOP_3", "top", "t3"),
        ("TOWER_MID_1", "mid", "t1"),
        ("TOWER_MID_2", "mid", "t2"),
        ("TOWER_MID_3", "mid", "t3"),
        ("TOWER_BOT_1", "bot", "t1"),
        ("TOWER_BOT_2", "bot", "t2"),
        ("TOWER_BOT_3", "bot", "t3"),
    ],
)
def test_tower_id_is_reported_under_its_lane_and_tier(tower_id, lane, tier):
    state = fog_checked_team_macro(f"towers[TEAM_DIRE][{tower_id}] = nil")

    fallen = [
        (fallen_lane, fallen_tier)
        for fallen_lane, towers_by_tier in state["towers"]["enemy"].items()
        for fallen_tier, tower in towers_by_tier.items()
        if not tower["alive"]
    ]
    assert fallen == [(lane, tier)]


@pytest.mark.parametrize(
    ("hp", "bucket"),
    [
        (0.3, "low"),
        (0.39, "low"),
        (0.4, "medium"),
        (0.69, "medium"),
        (0.7, "high"),
    ],
)
def test_allied_tower_hp_ratio_maps_to_its_bucket(hp, bucket):
    state = fog_checked_team_macro(f"towers[TEAM_RADIANT][TOWER_MID_1].hp = {hp}")

    assert state["towers"]["allied"]["mid"]["t1"] == {"alive": True, "enemy_heroes_near": 0, "hp": bucket}


def test_allied_tower_carries_its_hp_bucket_even_when_it_reports_it_cannot_be_seen():
    state = fog_checked_team_macro("towers[TEAM_RADIANT][TOWER_MID_1].CanBeSeen = function() return false end")

    assert state["towers"]["allied"]["mid"]["t1"] == {"alive": True, "enemy_heroes_near": 0, "hp": "high"}


def test_enemy_tower_the_team_can_see_carries_its_hp_bucket():
    state = fog_checked_team_macro()

    assert state["towers"]["enemy"]["mid"]["t1"] == {"alive": True, "enemy_heroes_near": 0, "hp": "high"}


def test_enemy_tower_the_team_cannot_see_carries_no_hp_and_its_hp_is_not_read():
    state = fog_checked_team_macro("""
    towers[TEAM_DIRE][TOWER_MID_1] = handle_exposing_only('unseen enemy tower', {
      IsAlive = function() return true end,
      CanBeSeen = function() return false end,
      GetLocation = function() return Vector(5000, 5000, 0) end,
    })
    """)

    assert state["towers"]["enemy"]["mid"]["t1"] == {"alive": True, "enemy_heroes_near": 0}


def test_enemy_tower_that_stops_being_seen_carries_no_hp():
    _, state_once_fogged = fog_checked_team_macro_before_and_after_fog(
        once_fogged="towers[TEAM_DIRE][TOWER_MID_1].CanBeSeen = function() return false end"
    )

    assert state_once_fogged["towers"]["enemy"]["mid"]["t1"] == {"alive": True, "enemy_heroes_near": 0}


def test_tower_of_either_side_counts_the_visible_enemies_within_1200_units_of_it():
    state = fog_checked_team_macro("""
    towers[TEAM_RADIANT][TOWER_MID_1].location = Vector(0, 0, 0)
    towers[TEAM_DIRE][TOWER_MID_1].location = Vector(0, 0, 0)
    enemy_hero_units = {
      hero({ player_id = LINA_ID, location = Vector(0, 1200, 0) }),
      hero({ player_id = PUDGE_ID, location = Vector(0, 1201, 0) }),
    }
    """)

    enemy_heroes_near_mid = {
        tier: {side: state["towers"][side]["mid"][tier]["enemy_heroes_near"] for side in state["towers"]}
        for tier in ("t1", "t2")
    }
    assert enemy_heroes_near_mid == {"t1": {"allied": 1, "enemy": 1}, "t2": {"allied": 0, "enemy": 0}}


@pytest.mark.parametrize(
    "dead_tower",
    [
        pytest.param("nil", id="no_handle"),
        pytest.param("handle_exposing_only('dead tower', { IsAlive = function() return false end })", id="handle_not_alive"),
    ],
)
def test_dead_tower_is_not_alive_and_carries_nothing_else(dead_tower):
    state = fog_checked_team_macro(f"towers[TEAM_DIRE][TOWER_BOT_2] = {dead_tower}")

    assert state["towers"]["enemy"]["bot"]["t2"] == {"alive": False}
