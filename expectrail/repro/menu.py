"""Menu probes: play a library probe, then open the game's pause menu and look at it (issue #285, step 3).

    python3 -m expectrail.repro menu --menu-action toggle_pause                         # prints them; no engine
    python3 -m expectrail.repro evidence --defect coin-counter-stuck --menu-action toggle_pause --menu-only \\
        --out runs/repro-menu                                                            # replays; no model, no key

Some of what a game keeps is drawn only on a menu. On the bundled game the coin counter is drawn
only on the pause menu (``game/platformer/gui/pause_menu.tscn``), so two of the public bench's
defects (``coin-counter-stuck``, ``coin-counts-twice``) changed nothing on any route of the baseline
run: the action catalog (move, jump, shoot) has no way to open it. Their hand finding is
``route-never-reaches``.

A menu probe is a library probe that covers ground, then a short wait, one tap of the menu action and
time for the menu to be drawn. Which library probes: those of ``FAMILIES`` (the walks), because what
a menu shows about play is what play has gathered by then. It is a route, not a judgement: nothing
here reads the record or the frames.

**The menu action is named by the caller, and refused unless the game binds it.** It is not in the
mechanics profile's action catalog (``discovery/platformer.profile.json`` is read by every offer of
the generator, and adding an action there would change the baseline's prompt and the reach probes).
Where a project's input actions are declared is #259's ``expectrail.project/v1``; until then the name
is checked against the ``[input]`` section of the game's ``project.godot``, and a name it does not
declare is an error, never a route that presses nothing.

**Not offered to generated checks.** No offer of ``expectrail/jit/offer.py`` imports this module. A
menu probe's difference on the coin counter is on the screen only (the engine's record has no field
for a label's text), so a check written in today's closed language could not use it; that is #286.
What it changes is what the evidence (``expectrail.repro.evidence``) can see.

The harness keeps running while the game pauses its tree (``harness/godot/expectrail_harness.gd``,
``tests/test_pause_input.py``); before November 13, 2026 a route that paused never reached its end.
"""
from __future__ import annotations

import re
from pathlib import Path

from expectrail.discovery.route_compiler import ProgramError, compile_route

FAMILY = "menu"
FAMILIES = ("hold", "reverse")   # the library's walks
SETTLE_TICKS = 30                 # after the walk, before the menu is opened
TAP_TICKS = 4
OPEN_TICKS = 90                   # the bundled menu fades in over 0.3 s; the compiler's tail adds more
MAX_MENU_ACTIONS = 2
MAX_PROBES = 6
MAX_ID_CHARS = 60
NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SECTION = re.compile(r"^\[([^\]]+)\]\s*$")
_ACTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=\{\s*$")
MAX_PROJECT_BYTES = 1024 * 1024


class MenuError(ValueError):
    """The menu probes cannot be made."""


def declared_actions(project_file: Path) -> list[str]:
    """The input actions a Godot ``project.godot`` declares in its ``[input]`` section, in file order."""
    path = Path(project_file)
    if not path.is_file():
        raise MenuError(f"no project file at {path.name}")
    data = path.read_bytes()
    if len(data) > MAX_PROJECT_BYTES:
        raise MenuError("the project file is over 1 MiB")
    section, found = None, []
    for line in data.decode("utf-8", errors="replace").splitlines():
        head = _SECTION.match(line)
        if head:
            section = head.group(1)
            continue
        if section == "input":
            m = _ACTION.match(line)
            if m and m.group(1) not in found:
                found.append(m.group(1))
    return found


def check_menu_actions(menu_actions, actions, declared) -> list[str]:
    """The menu actions, refused when one is not a plain name, is named twice, is already in the
    action catalog, or is not declared by the game."""
    menu = list(menu_actions)
    if not menu:
        raise MenuError("no menu action given")
    if len(menu) > MAX_MENU_ACTIONS:
        raise MenuError(f"{len(menu)} menu actions (max {MAX_MENU_ACTIONS})")
    if len(set(menu)) != len(menu) or not all(isinstance(a, str) and NAME.match(a) for a in menu):
        raise MenuError("a menu action is not a plain action name, or is named twice")
    for a in menu:
        if a in actions:
            raise MenuError(f"{a} is already in the action catalog: it is not a menu action here")
        if a not in declared:
            raise MenuError(f"the game declares no input action {a}")
    return menu


def _probe(base: dict, menu_action: str) -> dict:
    program = base["program"]
    tail = [{"op": "wait", "durationTicks": SETTLE_TICKS},
            {"op": "tap", "action": menu_action, "durationTicks": TAP_TICKS},
            {"op": "wait", "durationTicks": OPEN_TICKS}]
    # Flattened into the base's own sequence, so the program is no deeper than the base's.
    steps = [*program["steps"], *tail] if program.get("op") == "sequence" else [program, *tail]
    pid = f"{base['id']}-then-{menu_action.replace('_', '-')}"
    if len(pid) > MAX_ID_CHARS:
        raise MenuError(f"the probe name for {base['id']} with {menu_action} is over {MAX_ID_CHARS} characters")
    return {"id": pid, "family": FAMILY,
            "description": f"{base['description'].rstrip('.')}. Then wait {SETTLE_TICKS} ticks, tap {menu_action} "
                           f"once and wait {OPEN_TICKS} ticks while the menu is drawn.",
            "program": {"op": "sequence", "steps": steps}, "tags": sorted({FAMILY, *base.get("tags", [])})}


def menu_probes(library: list[dict], menu_actions, actions, declared) -> list[dict]:
    """One menu probe for each library probe of FAMILIES and each menu action, in library order.

    Each is compiled with the catalog plus the menu actions, by the same compiler and limits as any
    probe; one it refuses is an error, never left out quietly."""
    menu = check_menu_actions(menu_actions, actions, declared)
    names = [*actions, *menu]
    taken = {p["id"] for p in library}
    made = []
    for base in library:
        if base.get("family") not in FAMILIES:
            continue
        for action in menu:
            probe = _probe(base, action)
            if probe["id"] in taken:
                raise MenuError(f"a probe is already called {probe['id']}")
            try:
                compile_route(probe["program"], name=probe["id"], description=probe["description"], actions=names)
            except ProgramError as exc:
                raise MenuError(f"{probe['id']}: {exc}") from exc
            taken.add(probe["id"])
            made.append(probe)
    if not made:
        raise MenuError(f"the library has no probe of the families {', '.join(FAMILIES)} to open the menu after")
    if len(made) > MAX_PROBES:
        raise MenuError(f"{len(made)} menu probes (max {MAX_PROBES})")
    return made


def with_menu_actions(profile: dict, menu_actions) -> dict:
    """A copy of the profile whose catalog also has the menu actions, for compiling menu probes only."""
    return {**profile, "actions": [*profile["actions"], *menu_actions]}
