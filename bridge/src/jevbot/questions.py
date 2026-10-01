from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from typesafe_sdk import Choice, Question

_LANES = ("top", "mid", "bot")


@dataclass(frozen=True)
class KindSpec:
    freshness_class: Literal["macro", "fight"]
    build: Callable[[Mapping[str, Any]], dict[str, Question]]


def _push_criterion(lane: str) -> str:
    return (
        f"The enemy {lane} tower in `towers` is standing, no enemy hero in `enemies_visible` "
        f"is in {lane} lane, and no hero in `allies` has hp bucket `low`."
    )


def _defend_criterion(lane: str) -> str:
    return f"An allied {lane} tower in `towers` is under attack by enemy heroes."


def _build_team_macro(_state: Mapping[str, Any]) -> dict[str, Question]:
    return {
        "objective": Choice(
            instructions=(
                "Which objective should our team pursue next, judged from `towers`, "
                "`allies`, `enemies_visible`, and `enemies_missing`?"
            ),
            criteria={
                "farm": (
                    "No allied tower in `towers` is under attack, and enemy heroes in "
                    "`enemies_visible` guard the standing enemy towers in `towers`."
                ),
                **{f"push_{lane}": _push_criterion(lane) for lane in _LANES},
                **{f"defend_{lane}": _defend_criterion(lane) for lane in _LANES},
                "regroup": (
                    "Heroes in `allies` have hp bucket `low` and enemy heroes are listed "
                    "in `enemies_missing`."
                ),
            },
        )
    }


KINDS: dict[str, KindSpec] = {
    "team_macro": KindSpec(freshness_class="macro", build=_build_team_macro),
}


def lookup(kind: str) -> KindSpec | None:
    return KINDS.get(kind)
