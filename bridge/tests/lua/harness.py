import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TIMEOUT_S = 10.0
RESULT_MARKER = "@@lua-harness-result@@"

DRIVER = (
    f"package.path = [==[{REPO_ROOT.as_posix()}/?.lua]==]\n"
    f"local result_marker = [==[{RESULT_MARKER}]==]\n"
    r"""
GetScriptDirectory = function() return "bots" end
TEAM_RADIANT = 2
TEAM_DIRE = 3

local vector_methods = {}
local vector_meta = { __index = vector_methods }

function Vector(x, y, z)
  return setmetatable({ x = x, y = y, z = z or 0 }, vector_meta)
end

function vector_methods:Length2D()
  return math.sqrt(self.x * self.x + self.y * self.y)
end

vector_meta.__add = function(a, b) return Vector(a.x + b.x, a.y + b.y, a.z + b.z) end
vector_meta.__sub = function(a, b) return Vector(a.x - b.x, a.y - b.y, a.z - b.z) end

print = function(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[i] = tostring((select(i, ...))) end
  io.stderr:write(table.concat(parts, "\t"), "\n")
end

local encode = require("game/dkjson").encode
-- dkjson registers a global `json`.
json = nil

local function is_non_finite(number)
  return number ~= number or number == math.huge or number == -math.huge
end

local function reject_what_json_would_distort(value, visited)
  if type(value) == "number" and is_non_finite(value) then
    error("return value holds the non-finite number " .. tostring(value), 0)
  end
  if type(value) ~= "table" or visited[value] then return end
  visited[value] = true
  if type(rawget(value, "n")) == "number" then
    error("return value holds a table with a numeric `n` field, which the encoder reads as an array length", 0)
  end
  for _, item in pairs(value) do reject_what_json_would_distort(item, visited) end
end

local scenario, syntax_error = loadstring(io.read("*a"), "=scenario")
if not scenario then error(syntax_error, 0) end
local result = scenario()
reject_what_json_would_distort(result, {})
io.write(result_marker, encode(result))
"""
)


class LuaError(Exception):
    pass


def load_expr(module: str) -> str:
    return f"(function(name) package.loaded[name] = nil; return require(name) end)([==[{module}]==])"


def run(script: str, stubs: str = "") -> object:
    completed = subprocess.run(
        [_luajit(), "-e", DRIVER],
        input="\n".join(part for part in (stubs, script) if part),
        capture_output=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        timeout=TIMEOUT_S,
    )
    if completed.returncode != 0:
        raise LuaError(f"luajit exited with status {completed.returncode}:\n{completed.stderr}")
    if not completed.stdout.startswith(RESULT_MARKER):
        raise LuaError(
            f"luajit stdout does not start with the return value:\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return json.loads(completed.stdout.removeprefix(RESULT_MARKER))


def _luajit() -> str:
    luajit = shutil.which("luajit")
    if luajit is None:
        pytest.fail("luajit is not on PATH. Run `mise install` at the repo root, then run pytest through `mise exec`.")
    return luajit
