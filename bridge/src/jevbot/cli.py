import argparse
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from jevbot.budget import SpendGovernor
from jevbot.config import Settings
from jevbot.gamelog import GameLogs
from jevbot.install import REPO_BOTS_DIR, LinkRefused, install, uninstall
from jevbot.jev import JevCaller
from jevbot.server import make_server

EXIT_REFUSED = 2

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jevbot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="serve bot decision requests on localhost")
    install_command = commands.add_parser("install", help="link this repo's bots/ into a Dota 2 install")
    install_command.set_defaults(change=install)
    uninstall_command = commands.add_parser("uninstall", help="remove the link that install created")
    uninstall_command.set_defaults(change=uninstall)
    for link_command in (install_command, uninstall_command):
        link_command.add_argument("--dota-dir", required=True, type=Path, help='path to the "dota 2 beta" directory')
    args = parser.parse_args(argv)
    if "change" in args:
        return _change_link(args.change, args)
    try:
        settings = Settings.from_env()
    except ValueError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _serve(settings)
    return 0


def _change_link(change: Callable[[Path, Path], str], args: argparse.Namespace) -> int:
    try:
        dota_dir = args.dota_dir.expanduser()
    except RuntimeError as error:
        raise _failure(args.command, error) from None
    try:
        print(change(dota_dir, REPO_BOTS_DIR))
    except LinkRefused as refusal:
        print(refusal, file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        raise _failure(args.command, error) from None
    return 0


def _failure(command: str, error: Exception) -> SystemExit:
    return SystemExit(f"jevbot: {command} failed: {error}")


def _serve(settings: Settings) -> None:
    governor = SpendGovernor(settings.max_tokens_per_s, settings.max_requests_per_s)
    logs = GameLogs(settings, lambda: (governor.calls, governor.input_tokens), time.monotonic)
    caller = JevCaller(settings)
    try:
        server = make_server(settings, caller, governor, logs)
    except OSError as error:
        caller.close()
        raise SystemExit(f"jevbot: cannot listen on {settings.host}:{settings.port}: {error.strerror}") from None
    host, port = server.server_address[:2]
    logger.info("Listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        server.server_close()
        logs.close("shutdown")
        caller.close()
