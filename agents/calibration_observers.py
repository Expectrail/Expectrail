"""Explicit offline adapters for the #330 loop. No default client or network path."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from expectrail.calibration import CalibrationError
from expectrail.contracts import digest
from expectrail.gate.verify import NoAnswer


# A concept name is lowercase ASCII words one space apart, and short. A game's own file and node
# names are text the game's author controls; one that is not already words after splitting camel
# case and the separators _ and - is not proposed at all, never rewritten into words. See
# docs/sam.md, "What text reaches a model" (#745).
CONCEPT_NAME = re.compile(r'[a-z0-9]+(?: [a-z0-9]+)*')
MAX_CONCEPT_NAME = 64


def name_proposals(game, textures):
    """Cheap candidates from binding node/group names and texture stems; no semantic guess wins by default."""
    from expectrail.project_config import read_game
    config = read_game(Path(game))
    names = ['player', *(Path(p).stem for p in textures)]
    if config and 'player' in config['bindings']:
        binding = config['bindings']['player']
        names.extend([binding.get('node', binding.get('group', '')).split('/')[-1]])
    words = [re.sub(r'[ _-]+', ' ', re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n)).strip(' ').lower() for n in names]
    return sorted({w for w in words if len(w) <= MAX_CONCEPT_NAME and CONCEPT_NAME.fullmatch(w)})


class RecordedSam:
    """Only exact PNG/prompt answers from a validated recording; never remap hashes."""
    minimum_floor = 0.0

    def __init__(self, recording):
        from expectrail.recorded import RecordedObserver
        # Reuse the existing exact-recording observer: no general answer cache, and a public
        # recording identity for the calibration guard. A missing answer cannot be filled by cache.
        self.observer = RecordedObserver(recording)
        self.client = self.observer.client
        self.source = copy.deepcopy(recording)

    def propose(self, game, textures):
        prompts = [a['prompt'] for a in self.source['answers'] if a['kind'] == 'segment']
        return sorted(set(prompts + name_proposals(game, textures)))

    def describe(self):
        return dict(identity=self.observer.describe(), evidence='recorded-sam', sourceSha256=digest(self.source))

    def detect(self, prompt, frame):
        from agents.sam_observations import SamError
        try:
            return self.client.segment(frame['png'], prompt)
        except SamError as exc:
            raise NoAnswer(str(exc)) from exc


class Template:
    """The frozen #262 local matcher; scores remain similarities, not probabilities.

    One art candidate, local engine-guided search: this cannot establish global uniqueness
    against enemies elsewhere in the picture. That limit is reported, never inferred away.
    """
    def __init__(self, bank):
        from agents import template_observations as sensor
        self.sensor = sensor
        self.bank = sensor.load_bank(bank)
        self.minimum_floor = self.bank['config']['matchThreshold']
        self.matcher = sensor.matchers_for(self.bank, ['player'])['player']
        self.observer = sensor.TemplateObserver(self.bank)

    def propose(self, game, textures):
        return ['player/robot.webp']

    def describe(self):
        return dict(identity=self.observer.describe(), evidence='no-model', sourceSha256=digest(self.bank))

    def detect(self, prompt, frame):
        if prompt != 'player/robot.webp':
            raise NoAnswer('template adapter requires its explicit player-art candidate')
        foreground = self.bank['config']['algorithm'] != self.sensor.ALGORITHM
        try:
            image = self.sensor._image(frame['png'], mode='RGB' if foreground else 'L')
            row = self.sensor.look(self.matcher, image, frame['expectedBox'], self.bank['config'], foreground)
        except (OSError, ValueError) as exc:
            raise NoAnswer(f'pixel sensor unavailable: {exc}') from exc
        if row['status'] in ('unavailable', 'out-of-frame'):
            raise NoAnswer(row['reason'])
        # Keep displaced matches: it is the common loop, not this adapter, that compares boxes.
        return ([dict(box=row['rawBox'], score=row['score'])] if row['status'] != 'not-found' else [])


def frames_from_run(folder, indices):
    """Use measured collision boxes/camera at the actual capture tick. No guessed dimensions."""
    from agents.template_observations import player_predictions
    folder = Path(folder)
    replay = json.loads((folder/'replay.json').read_text())
    trace = json.loads((folder/'trace.json').read_text())
    fps = replay['capture']['fps']
    boxes = player_predictions(trace, indices, fps)
    return [dict(frame=i, png=folder/'frames'/f'f{i:08d}.png', expectedBox=boxes[i]['player'],
                 replaySha256=digest(replay)) for i in indices]
