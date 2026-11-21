"""Build an Ubuntu amd64 desktop package from the Expectrail release wheel, offline."""
import argparse
from email.parser import Parser
import os
from pathlib import Path
import re
import subprocess
import tempfile

from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile


DIST_PACKAGES = '/usr/lib/python3/dist-packages'
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Expectrail
Exec=/usr/bin/python3 -I -m expectrail.cli app --open-browser
Terminal=false
Categories=Development;
"""


def build(wheel, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir) as tmp, WheelFile.open(wheel) as source:
        stage = Path(tmp) / 'root'
        metadata = Parser().parsestr(source.read_dist_info('METADATA'))
        wheel_info = Parser().parsestr(source.read_dist_info('WHEEL'))
        version = metadata['Version']
        if (source.distribution != 'expectrail' or metadata['Name'] != 'expectrail'
                or wheel_info['Root-Is-Purelib'] != 'true' or wheel_info.get_all('Tag') != ['py3-none-any']):
            raise ValueError('Expected the pure Python Expectrail release wheel')
        if version != source.version or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version):
            raise ValueError('Expected a numeric release version matching the wheel filename')
        floor = re.fullmatch(r'>=([0-9]+(?:\.[0-9]+)+)', metadata.get('Requires-Python', ''))
        if not floor:
            raise ValueError('Expected a single minimum Python version in Requires-Python')
        source.validate_record()
        destination = SchemeDictionaryDestination(
            {'purelib': DIST_PACKAGES, 'scripts': '/usr/bin'},
            interpreter='/usr/bin/python3', script_kind='posix', destdir=str(stage),
        )
        install(source, destination, additional_metadata={})
        desktop = stage / 'usr/share/applications/expectrail.desktop'
        desktop.parent.mkdir(parents=True)
        desktop.write_text(DESKTOP_ENTRY, encoding='utf-8')
        control = stage / 'DEBIAN/control'
        control.parent.mkdir()
        control.write_text(f"""Package: expectrail
Version: {version}
Architecture: amd64
Maintainer: Expectrail integrator (ChatGPT) <noreply@openai.com>
Section: devel
Priority: optional
Depends: python3 (>= {floor[1]}), python3-tk, xdg-utils, xvfb, xauth, libgl1-mesa-dri, libglx-mesa0,
 libfontconfig1, libxcursor1, libxinerama1, libxrandr2, libxi6, libxrender1, libxext6, libx11-6,
 patch, curl, unzip, ca-certificates
Recommends: bubblewrap, git
Description: Expectrail desktop app for verifying game changes
""", encoding='utf-8')
        artifact = Path(tmp) / f'expectrail_{version}_amd64.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', stage, artifact], check=True)
        return artifact.replace(output_dir / artifact.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    # A root-owned package must be readable by desktop users even if the
    # account building it has a restrictive umask.
    os.umask(0o022)
    try:
        print(build(args.wheel, args.output_dir))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
