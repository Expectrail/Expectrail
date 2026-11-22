"""Read a reference-only authoring record and draft existing setup assertions."""

from pathlib import Path, PurePosixPath

from expectrail.contracts import canonical_v1, strict_loads, validate, validate_v1


class ModelError(ValueError):
    """The reference record cannot support an authoring decision."""


def _check(model):
    validate_v1(model, "project-model")
    constraint, capture = model["constraint"], model["reference"]["capture"]
    if not 0 <= constraint["minimum"] < constraint["maximum"] <= capture["viewport"][1]:
        raise ModelError("needs-review: the authored band is outside the reference viewport")
    if capture["ticksPerSecond"] != capture["framesPerSecond"]:
        raise ModelError("needs-review: this authoring path requires one capture frame per tick")
    evidence = model["evidence"]
    if not 0 <= evidence["goalTick"] < evidence["returnTick"] <= evidence["lastTick"] == model["reference"]["route"]["ticks"] - 1:
        raise ModelError("needs-review: the reference evidence does not cover the full out-and-back route")
    for source in model["sources"]:
        path = PurePosixPath(source["path"])
        if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in source["path"]:
            raise ModelError("needs-review: a provenance path leaves the reference")


def write_model(path: Path, model: dict) -> None:
    """Write canonical bytes into a new file so old review provenance stays available."""
    _check(model)
    with path.open("xb") as output:
        output.write(canonical_v1(model))


def read_model(path: Path, reference: dict) -> dict:
    model = strict_loads(path.read_text(encoding="utf-8"))
    _check(model)
    if model["reference"] != reference:
        raise ModelError("needs-review: the reference or its replay inputs changed; make a new setup review")
    return model


def draft_pair(model: dict) -> dict[str, dict]:
    """Produce the rail and movement together for the normal human setup review."""
    _check(model)
    ref, band = model["reference"], model["constraint"]
    subject = band["subject"]
    if subject == "goal":
        raise ModelError("needs-review: the actor and contact mark require distinct roles")
    frame = model["evidence"]["lastTick"]
    common = {
        "format": "expectrail.test-spec/v0",
        "window": {"fromFrame": 0, "toFrame": frame},
        "coverage": {"routes": [ref["route"]["name"]]},
    }
    bounds = [0, band["minimum"], ref["capture"]["viewport"][0], band["maximum"]]
    rail = {
        **common, "id": "reference-rail", "instruction": "Keep the actor inside its authored rail on the out-and-back route.",
        "objects": {subject: {"prompt": "moving actor"}},
        "assertion": {"type": "inside-region", "object": subject, "region": {"box": bounds}},
    }
    movement = {
        **common, "id": "reference-movement", "instruction": "Reach the contact mark when the route commands movement.",
        "objects": {subject: {"prompt": "moving actor"}, "goal": {"prompt": "contact mark"}},
        "assertion": {"type": "reaches", "object": subject, "goal": "goal", "distancePx": 0},
    }
    for spec in (rail, movement):
        validate(spec, "test-spec")
    return {"rail": rail, "movement": movement}
