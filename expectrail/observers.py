"""The visual observer of a verification: a vision model over the frames a replay captured.

Expectrail verifies by observing, with two observers on every check (issue #327, Sean's decision of
November 12, 2026): the engine's record, which is exact about positions and free, and a visual
observer, which sees what was drawn. ``expectrail.gate.record.combine`` is the rule that joins what
the two said; this module is the second observer.

    observer = FramesObserver()            # SAM 3.1, or the backend $EXPECTRAIL_VISION_BACKEND names
    observations = observer.look(spec, run)    # expectrail.observations/v0, or NoAnswer

``run`` is one finished replay as the gate holds it: ``trace``, ``replaySha256``, ``framesDir``.
Where the trace holds the level's ground line and the spec has an object named ``ground``, the model
is asked for the other objects only and the ground comes from the engine in frame pixels, as in
``agents/verifier.py`` (the model's box for the player against the engine's ground line).

A live observer sends images to a paid model. Nothing in this module starts one by itself: the
caller constructs the observer. Tests and offline runs give it a ``client`` that answers from
recorded answers.
"""
from __future__ import annotations

from pathlib import Path

from expectrail.gate.verify import NoAnswer

GROUND = "ground"   # the object the engine's ground line stands for (agents.observations.engine_ground_by_frame)
MAX_WHY = 120


class FramesObserver:
    """A vision model over a replay's captured frames (``agents.sam_observations.from_replay``).

    ``client`` is the model client (default: the one the environment names, built on first use);
    ``cache`` the answer cache (default: the adapter's own). ``name`` is what the record calls this
    observer."""

    def __init__(self, *, client=None, cache=None, name: str | None = None, every: int | None = None,
                 workers: int | None = None):
        self._client, self._cache, self._name = client, cache, name
        self._every, self._workers = every, workers

    def _model(self):
        if self._client is None:
            from agents.sam_observations import default_client

            self._client = default_client(verdict=True)
        return self._client

    def segmenter(self):
        """The model client, for questions about a box in a frame (``segment_in``); the gate asks it
        about the player's place on both sides (``expectrail.gate.anchor``). Raises NoAnswer when no
        client can be made."""
        try:
            from agents.sam_observations import SamError
        except ImportError as exc:
            raise NoAnswer("this copy of Expectrail does not carry the vision adapter") from exc
        try:
            client = self._model()
        except SamError as exc:
            raise NoAnswer(f"no visual observer could be set up ({getattr(exc, 'kind', 'unknown')})") from exc
        if not callable(getattr(client, "segment_in", None)):
            raise NoAnswer("this vision model cannot be asked about a box")
        return client

    def describe(self) -> dict:
        """{"name", "provider", "model"} for the record. Raises NoAnswer when no client can be made."""
        try:
            from agents.sam_observations import SamError, vision_backend
        except ImportError as exc:
            raise NoAnswer("this copy of Expectrail does not carry the vision adapter") from exc
        try:
            client = self._model()
            name = self._name or vision_backend()
        except SamError as exc:
            raise NoAnswer(f"no visual observer could be set up ({getattr(exc, 'kind', 'unknown')})") from exc
        return {"name": str(name)[:40], "provider": str(getattr(client, "provider", "meta-model-api"))[:80],
                "model": str(client.model)[:80]}

    def look(self, spec: dict, run: dict, *, keep: bool = True) -> dict:
        """The observations for one spec on one replay. ``keep=False`` reads and writes no answer
        cache (for replays whose frames must leave nothing behind, such as held-out routes)."""
        from agents.observations import engine_ground_by_frame, has_engine_ground
        from agents.sam_observations import Cache, SamError, frame_files, from_replay, png_size

        frames_dir = run.get("framesDir")
        if frames_dir is None or not Path(frames_dir).is_dir():
            raise NoAnswer("the replay captured no frames")
        trace = run.get("trace") or {}
        try:
            engine_objects = None
            if GROUND in (spec.get("objects") or {}) and has_engine_ground(trace):
                frames = frame_files(Path(frames_dir))
                if frames:
                    engine_objects = engine_ground_by_frame(trace, png_size(next(iter(frames.values()))), list(frames))
            return from_replay(trace, replay_sha256=run["replaySha256"], frames_dir=frames_dir, spec=spec,
                               engine_objects=engine_objects, client=self._model(),
                               cache=self._cache if keep else Cache(None), every=self._every, workers=self._workers)
        except SamError as exc:
            # The kind only: a model's error text is not written into a record.
            raise NoAnswer(f"the model did not answer ({str(getattr(exc, 'kind', 'unknown'))[:MAX_WHY]})") from exc
        except OSError as exc:
            raise NoAnswer(f"the frames could not be read ({type(exc).__name__})") from exc
