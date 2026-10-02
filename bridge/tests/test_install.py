import os
import shutil
from pathlib import Path

import pytest

from jevbot.cli import main

BOT_SCRIPT = "bot_generic.lua"
REPO_SCRIPT_TEXT = "-- repo bot script\n"
FOREIGN_SCRIPT_TEXT = "-- someone else's bot script\n"
GAME_FILE_TEXT = "-- shipped with the game\n"
SUCCEEDED = 0
REFUSED = 2

both_commands = pytest.mark.parametrize("command", ["install", "uninstall"])


def bots_link(dota_dir: Path) -> Path:
    return dota_dir / "game" / "dota" / "scripts" / "vscripts" / "bots"


@pytest.fixture(autouse=True)
def repo_bots(tmp_path, monkeypatch):
    directory = tmp_path / "repo" / "bots"
    directory.mkdir(parents=True)
    (directory / BOT_SCRIPT).write_text(REPO_SCRIPT_TEXT, encoding="utf-8")
    monkeypatch.setattr("jevbot.cli.REPO_BOTS_DIR", directory)
    return directory


@pytest.fixture
def dota_dir(tmp_path):
    directory = tmp_path / "dota 2 beta"
    core = bots_link(directory).parent / "core"
    core.mkdir(parents=True)
    (core / "coreinit.lua").write_text(GAME_FILE_TEXT, encoding="utf-8")
    (directory / "installscript.vdf").write_text(GAME_FILE_TEXT, encoding="utf-8")
    return directory


def run(command: str, dota_dir: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = main([command, "--dota-dir", str(dota_dir)])
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def script_texts(bots_dir: Path) -> dict[str, str]:
    return {script.name: script.read_text(encoding="utf-8") for script in bots_dir.iterdir()}


def snapshot(root: Path) -> dict[str, tuple[int, str | None]]:
    def link_target_or_text(path: Path) -> str | None:
        if path.is_symlink():
            return os.readlink(path)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    return {
        path.relative_to(root).as_posix(): (path.lstat().st_mode, link_target_or_text(path))
        for path in root.rglob("*")
    }


def test_install_links_the_repo_bots_into_the_dota_tree(dota_dir, repo_bots, capsys):
    link = bots_link(dota_dir)

    assert run("install", dota_dir, capsys) == (SUCCEEDED, f"installed {link} -> {repo_bots}\n", "")
    assert link.is_symlink()
    assert link.resolve() == repo_bots.resolve()
    assert script_texts(link) == {BOT_SCRIPT: REPO_SCRIPT_TEXT}


def test_second_install_prints_already_installed(tmp_path, dota_dir, repo_bots, capsys):
    run("install", dota_dir, capsys)
    before = snapshot(tmp_path)

    assert run("install", dota_dir, capsys) == (SUCCEEDED, "already installed\n", "")
    assert bots_link(dota_dir).resolve() == repo_bots.resolve()
    assert snapshot(tmp_path) == before


def test_install_without_the_repo_bots_directory_is_refused_and_creates_no_link(tmp_path, dota_dir, repo_bots, capsys):
    shutil.rmtree(repo_bots)
    before = snapshot(tmp_path)

    refusal = f"{repo_bots} is not a directory, jevbot must be installed from the repo checkout\n"
    assert run("install", dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


def test_install_into_a_directory_without_the_dota_script_tree_is_refused_and_creates_nothing(tmp_path, capsys):
    not_dota = tmp_path / "not dota"
    not_dota.mkdir()
    before = snapshot(tmp_path)

    refusal = f"{bots_link(not_dota).parent} is not a directory, {not_dota} does not look like a Dota 2 install\n"
    assert run("install", not_dota, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


@both_commands
def test_real_bots_directory_is_refused_and_left_unchanged(tmp_path, dota_dir, capsys, command):
    real_bots = bots_link(dota_dir)
    (real_bots / "FunLib").mkdir(parents=True)
    (real_bots / BOT_SCRIPT).write_text(FOREIGN_SCRIPT_TEXT, encoding="utf-8")
    (real_bots / "FunLib" / "utils.lua").write_text(FOREIGN_SCRIPT_TEXT, encoding="utf-8")
    before = snapshot(tmp_path)

    refusal = f"{real_bots} is a real directory, leaving it untouched\n"
    assert run(command, dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


@both_commands
def test_link_to_another_directory_is_refused_and_left_in_place(tmp_path, dota_dir, capsys, command):
    foreign_bots = tmp_path / "another checkout" / "bots"
    foreign_bots.mkdir(parents=True)
    (foreign_bots / BOT_SCRIPT).write_text(FOREIGN_SCRIPT_TEXT, encoding="utf-8")
    link = bots_link(dota_dir)
    link.symlink_to(foreign_bots, target_is_directory=True)
    before = snapshot(tmp_path)

    refusal = f"{link} is a link to {foreign_bots}, leaving it untouched\n"
    assert run(command, dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


@both_commands
def test_dangling_link_is_refused_and_left_in_place(tmp_path, dota_dir, capsys, command):
    missing_target = tmp_path / "deleted checkout" / "bots"
    link = bots_link(dota_dir)
    link.symlink_to(missing_target, target_is_directory=True)
    before = snapshot(tmp_path)

    refusal = f"{link} is a link to {missing_target}, leaving it untouched\n"
    assert run(command, dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


@both_commands
def test_plain_file_at_the_link_path_is_refused_and_left_unchanged(tmp_path, dota_dir, capsys, command):
    plain_file = bots_link(dota_dir)
    plain_file.write_text(FOREIGN_SCRIPT_TEXT, encoding="utf-8")
    before = snapshot(tmp_path)

    refusal = f"{plain_file} is a file, leaving it untouched\n"
    assert run(command, dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


def test_uninstall_without_a_link_is_refused(tmp_path, dota_dir, capsys):
    before = snapshot(tmp_path)

    refusal = f"{bots_link(dota_dir)} does not exist, nothing to uninstall\n"
    assert run("uninstall", dota_dir, capsys) == (REFUSED, "", refusal)
    assert snapshot(tmp_path) == before


def test_uninstall_removes_the_link_and_nothing_else(tmp_path, dota_dir, capsys):
    before_install = snapshot(tmp_path)
    run("install", dota_dir, capsys)

    assert run("uninstall", dota_dir, capsys) == (SUCCEEDED, f"uninstalled {bots_link(dota_dir)}\n", "")
    assert snapshot(tmp_path) == before_install
