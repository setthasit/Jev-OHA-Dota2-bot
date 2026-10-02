import re
import subprocess
from pathlib import Path

import pytest

from . import harness

LOAD_COUNTER_MODULE = """\
load_count = (load_count or 0) + 1
local load_counter = { load_count = load_count, script_directory = GetScriptDirectory() }
return load_counter
"""
CLOCK_STUBS = """
local now = 10
function DotaTime() return now end
"""
TRANSPORT_STUBS = """
local posted_callback
transport = { Post = function(payload, callback) posted_callback = callback end }
"""
CONSIDER_STUBS = """
local function consider() return 0.8, { name = 'lina' } end
"""
SHORT_TIMEOUT_S = 0.2


@pytest.fixture
def load_counter_stubs(tmp_path: Path) -> str:
    (tmp_path / "load_counter.lua").write_text(LOAD_COUNTER_MODULE, encoding="utf-8")
    return f'package.path = package.path .. ";{tmp_path.as_posix()}/?.lua"'


def test_run_returns_the_value_of_a_module_required_through_load_expr(load_counter_stubs):
    loaded = harness.run(f"return {harness.load_expr('load_counter')}", load_counter_stubs)

    assert loaded == {"load_count": 1, "script_directory": "bots"}


def test_load_expr_reloads_a_module_that_plain_require_would_cache(load_counter_stubs):
    script = f"""
    local first = {harness.load_expr("load_counter")}
    local cached = require("load_counter")
    local reloaded = {harness.load_expr("load_counter")}
    return {{ first.load_count, cached.load_count, reloaded.load_count }}
    """

    assert harness.run(script, load_counter_stubs) == [1, 1, 2]


def test_script_using_goto_and_bit_band_runs():
    script = """
    local odd_sum = 0
    for i = 1, 6 do
      if bit.band(i, 1) == 0 then goto continue end
      odd_sum = odd_sum + i
      ::continue::
    end
    return odd_sum
    """

    assert harness.run(script) == 9


def test_script_advances_a_local_that_the_stubs_declared():
    script = """
    local before = DotaTime()
    now = now + 5
    return { before, DotaTime() }
    """

    assert harness.run(script, CLOCK_STUBS) == [10, 15]


def test_script_fires_a_callback_the_stubs_captured_after_advancing_time():
    script = """
    local answered
    transport.Post({ kind = "team_macro" }, function(choice) answered = { choice = choice, at = DotaTime() } end)
    now = now + 3
    posted_callback("push_mid")
    return answered
    """

    assert harness.run(script, CLOCK_STUBS + TRANSPORT_STUBS) == {"choice": "push_mid", "at": 13}


def test_driver_defines_the_script_directory_and_team_constants():
    assert harness.run("return { GetScriptDirectory(), TEAM_RADIANT, TEAM_DIRE }") == ["bots", 2, 3]


def test_package_path_is_the_repo_root():
    assert harness.run("return package.path") == f"{harness.REPO_ROOT.as_posix()}/?.lua"


def test_script_runs_from_the_repo_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert harness.run("local f = io.open('game/dkjson.lua') return f ~= nil") is True


def test_script_directory_module_name_resolves_to_a_repo_file():
    found = harness.run("return package.searchpath(GetScriptDirectory()..'/FunLib/utils', package.path)")

    assert found == f"{harness.REPO_ROOT.as_posix()}/bots/FunLib/utils.lua"


def test_each_run_starts_a_new_lua_process():
    harness.run("leak = 1")

    assert harness.run("return leak") is None


def test_driver_vector_adds_subtracts_and_measures_ground_length():
    script = """
    local sum = Vector(1, 2, 3) + Vector(10, 20, 30)
    local difference = Vector(10, 20, 30) - Vector(1, 2, 3)
    return {
      sum = { sum.x, sum.y, sum.z },
      difference = { difference.x, difference.y, difference.z },
      ground_length = (Vector(3, 4, 99) - Vector(0, 0, 0)):Length2D(),
      omitted_z = Vector(1, 2).z,
    }
    """

    assert harness.run(script) == {
        "sum": [11, 22, 33],
        "difference": [9, 18, 27],
        "ground_length": 5,
        "omitted_z": 0,
    }


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("return nil", None),
        ("local unused = 1", None),
        ("return {}", []),
        ("return { hero = 'lina', items = {} }", {"hero": "lina", "items": []}),
        ("return { 1.5, 'mid', true }", [1.5, "mid", True]),
        ("return { [TEAM_RADIANT] = 'a', [TEAM_DIRE] = 'b' }", [None, "a", "b"]),
        ("return 1 / 3", 0.33333333333333),
        ("return 2 ^ 53", 9007199254741000),
        ("return { n = 'lina' }", {"n": "lina"}),
    ],
)
def test_return_value_decodes_to_python(script, expected):
    assert harness.run(script) == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("return 7, 'target'", 7),
        ("return nil, 'err'", None),
        ("return consider()", 0.8),
    ],
)
def test_only_the_first_of_several_return_values_is_decoded(script, expected):
    assert harness.run(script, CONSIDER_STUBS) == expected


def test_call_packed_in_a_table_returns_every_value():
    assert harness.run("return { consider() }", CONSIDER_STUBS) == [0.8, {"name": "lina"}]


@pytest.mark.parametrize("script", ["return math.huge", "return 0 / 0", "return { at = -math.huge }", "return { { 0 / 0 } }"])
def test_non_finite_number_in_the_return_value_raises(script):
    with pytest.raises(harness.LuaError, match="non-finite number"):
        harness.run(script)


@pytest.mark.parametrize(
    "script",
    [
        "return { n = 3 }",
        "return { n = 2, 'a', 'b' }",
        "return { units = { n = 3 } }",
        "return { inner = { n = 3 } }",
        "return { { n = 1 } }",
    ],
)
def test_table_with_a_numeric_n_field_in_the_return_value_raises(script):
    with pytest.raises(harness.LuaError, match="numeric `n` field"):
        harness.run(script)


def test_cyclic_return_value_raises_the_encoder_error():
    with pytest.raises(harness.LuaError, match="reference cycle"):
        harness.run("local t = {} t.self = t return t")


def test_whole_lua_number_decodes_as_int():
    result = harness.run("return 6 / 2")

    assert (result, type(result)) == (3, int)


def test_print_does_not_corrupt_the_return_value():
    assert harness.run("print('noise', 1) return 7") == 7


def test_json_global_of_the_encoder_is_hidden_from_scripts():
    assert harness.run("return json == nil") is True


def test_lua_runtime_error_raises_with_stderr():
    with pytest.raises(harness.LuaError, match="scenario:1: tower fell"):
        harness.run("error('tower fell')")


def test_lua_syntax_error_raises_with_stderr():
    with pytest.raises(harness.LuaError, match="scenario:1: '<name>' expected"):
        harness.run("local = 1")


def test_non_zero_exit_raises_with_the_status_and_stderr():
    with pytest.raises(harness.LuaError, match=r"status 3:\nboom"):
        harness.run("io.write('7') io.stderr:write('boom') os.exit(3)")


@pytest.mark.parametrize("written", ["stray", "1"])
def test_script_writing_to_stdout_raises_with_the_stdout_it_wrote(written):
    with pytest.raises(harness.LuaError, match=re.escape(f"stdout: {written}{harness.RESULT_MARKER}7")):
        harness.run(f"io.write('{written}') return 7")


def test_missing_luajit_fails_the_test_naming_mise_install(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)

    with pytest.raises(pytest.fail.Exception, match="mise install"):
        harness.run("return 1")


def test_script_that_never_returns_times_out(monkeypatch):
    monkeypatch.setattr(harness, "TIMEOUT_S", SHORT_TIMEOUT_S)

    with pytest.raises(subprocess.TimeoutExpired):
        harness.run("while true do end")
