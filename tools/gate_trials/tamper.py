"""Prepare the trial, or mutate a local capture copy without extracting any member."""
import argparse
from pathlib import Path
import sys
import zipfile

from .build import TrialError, script


def mutate(capture, out):
    source, destination = Path(capture).resolve(), Path(out).resolve()
    if source == destination or destination.exists():
        raise TrialError('choose a new output file; the original capture is never overwritten')
    if source.stat().st_size > 1024**3:
        raise TrialError('capture exceeds the 1 GiB rehearsal bound')
    created = False
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > 50000 or sum(i.file_size for i in infos) > 1024**3 or any(
                    i.file_size > 128*1024**2 for i in infos):
                raise TrialError('capture exceeds the local rehearsal limits')
            names = [i.filename for i in infos if i.filename.endswith('/trace.json')]
            if not names:
                raise TrialError('capture has no trace.json to mutate')
            changed = sorted(names)[0]
            with destination.open('xb') as handle:
                created = True
                with zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as altered:
                    for info in infos:
                        data = archive.read(info)
                        altered.writestr(info, data+b' ' if info.filename == changed else data)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return changed


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--capture' not in args:
        return script('tamper', args)
    parser = argparse.ArgumentParser(description='Offline rehearsal only: change one trace byte in a new ZIP.')
    parser.add_argument('--capture', required=True)
    parser.add_argument('--out', required=True)
    values = parser.parse_args(args)
    try:
        changed = mutate(values.capture, values.out)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        parser.exit(2, 'Expectrail trial: '+str(exc)+'\n')
    print('LOCAL REHEARSAL ONLY: appended a space to '+changed+'; manifest unchanged.')
    print('Expected judge reason: EVIDENCE_MISMATCH. No hosted artifact was changed or uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
