import os
import sys
from pathlib import Path

REPO_BOTS_DIR = Path(__file__).resolve().parents[3] / "bots"
LINK_SUBPATH = Path("game", "dota", "scripts", "vscripts", "bots")


class LinkRefused(Exception):
    pass


def install(dota_dir: Path, repo_bots: Path) -> str:
    link = dota_dir / LINK_SUBPATH
    if not dota_dir.is_dir():
        raise LinkRefused(f"{dota_dir} is not a directory, check --dota-dir")
    if not link.parent.is_dir():
        raise LinkRefused(f"{link.parent} is not a directory, {dota_dir} does not look like a Dota 2 install")
    if _is_link_to(link, repo_bots):
        return "already installed"
    if _is_present(link):
        raise LinkRefused(_occupied_message(link))
    if not repo_bots.is_dir():
        raise LinkRefused(f"{repo_bots} is not a directory, jevbot must be installed from the repo checkout")
    _create_directory_link(link, repo_bots.resolve())
    return f"installed {link} -> {repo_bots}"


def uninstall(dota_dir: Path, repo_bots: Path) -> str:
    link = dota_dir / LINK_SUBPATH
    if not _is_present(link):
        raise LinkRefused(f"{link} does not exist, nothing to uninstall")
    if not _is_link_to(link, repo_bots):
        raise LinkRefused(_occupied_message(link))
    os.unlink(link)
    return f"uninstalled {link}"


def _is_present(path: Path) -> bool:
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _occupied_message(path: Path) -> str:
    return f"{path} is {_describe(path)}, leaving it untouched"


def _is_link_to(link: Path, directory: Path) -> bool:
    if _link_target(link) is None:
        return False
    try:
        return os.path.realpath(link, strict=True) == os.path.realpath(directory, strict=True)
    except OSError:
        return False


def _link_target(path: Path) -> str | None:
    # os.readlink also reads a Windows junction, and raises ValueError there on other reparse points.
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        return None


def _describe(path: Path) -> str:
    target = _link_target(path)
    if target is not None:
        return f"a link to {target}"
    if path.is_dir():
        return "a real directory"
    return "a file"


def _create_directory_link(link: Path, directory: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(directory), str(link))
    else:
        os.symlink(directory, link)
