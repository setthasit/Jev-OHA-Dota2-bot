import argparse
import logging
import time

from jevbot.budget import SpendGovernor
from jevbot.config import Settings
from jevbot.gamelog import GameLogs
from jevbot.jev import JevCaller
from jevbot.server import make_server

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jevbot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="serve bot decision requests on localhost")
    parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _serve(settings)
    return 0


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
