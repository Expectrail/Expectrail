"""Local commit inputs: config-free Git object reads, never checkout or archive.

The private Git view has no hooks, filters, remotes, replace refs or user config.
Only local object files and reference/index data are made available to it. Raw
objects are hashed again before their bytes enter a job-owned snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading

MAX_BLOB = 128 * 1024**2
MAX_TOTAL = 2 * 1024**3
MAX_FILES = 100000
OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class CommitError(ValueError):
    pass


def remove_tree(root):
    """Remove only an owned snapshot/view; never chmod hard-linked object files."""
    root = Path(root)
    if not root.exists():
        return
    for folder, dirs, _files in os.walk(root, followlinks=False):
        if not Path(folder).is_symlink():
            Path(folder).chmod(0o700)
    shutil.rmtree(root)


def seal(root):
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = Path(folder) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        Path(folder).chmod(0o555)


def regular(path, limit):
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(path, flags), 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise CommitError('repository metadata is not a bounded regular file')
            data = f.read(limit + 1)
            if len(data) > limit:
                raise CommitError('repository metadata exceeds its limit')
            return data
    except OSError as exc:
        raise CommitError('cannot read a regular repository file') from exc


def layout(repository):
    path = Path(repository).expanduser().resolve()
    if not path.is_dir():
        raise CommitError('repository path is not a Git repository')
    for root in (path, *path.parents):
        dot = root / '.git'
        if dot.is_symlink():
            raise CommitError('a symlinked Git directory is not supported')
        if dot.is_dir():
            git = dot
            working = root
            break
        if dot.is_file():
            text = regular(dot, 8192).decode('utf-8').strip()
            if not text.startswith('gitdir: ') or '\n' in text:
                raise CommitError('repository has an invalid gitdir file')
            git = (root / text[8:]).resolve()
            working = root
            break
        if (root / 'HEAD').is_file() and (root / 'objects').is_dir():
            git, working = root, None
            break
    else:
        raise CommitError('repository path is not a Git repository')
    common = git
    if (git / 'commondir').exists():
        text = regular(git / 'commondir', 8192).decode('utf-8').strip()
        if not text or any(ord(c) < 32 for c in text):
            raise CommitError('repository has an invalid common directory')
        common = (git / text).resolve()
    if not (common / 'objects').is_dir() or not (git / 'HEAD').is_file():
        raise CommitError('repository path is not a Git repository')
    return working, git, common


class Objects:
    def __init__(self, repository, folder, timeout):
        self.working, git, common = layout(repository)
        self.repo = str((self.working or common).resolve())
        self.folder = Path(folder)
        self.folder.mkdir()
        self.git = shutil.which('git')
        if not self.git:
            raise CommitError('Git is not installed; install Git before using --repo')
        self.env = {'PATH': os.defpath, 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_SYSTEM': os.devnull, 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
                    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}
        self.timeout = min(timeout, 300)
        (self.folder / 'config').write_text('[core]\nrepositoryformatversion=0\nbare=true\n')
        config = self.folder / 'source-config'
        config.write_bytes(regular(common / 'config', 1024**2) if (common / 'config').exists() else b'')
        def setting(name):
            result = self.command('config', '--no-includes', '--file', str(config), '--get', name, check=False)
            if result.returncode not in (0, 1):
                raise CommitError('repository configuration cannot be read')
            return result.stdout.decode().strip()
        algorithm = setting('extensions.objectFormat') or 'sha1'
        if algorithm not in ('sha1', 'sha256') or setting('extensions.refStorage') not in ('', 'files'):
            raise CommitError('repository object/ref format is not supported')
        self.algorithm = algorithm
        self.oid_bytes = 20 if algorithm == 'sha1' else 32
        if algorithm == 'sha256':
            (self.folder / 'config').write_text('[core]\nrepositoryformatversion=1\nbare=true\n[extensions]\nobjectFormat=sha256\n')
        config.unlink()
        for name, source in [('HEAD', git / 'HEAD'), ('packed-refs', common / 'packed-refs'),
                             ('index', git / 'index'), ('info/exclude', common / 'info/exclude')]:
            if source.exists() or source.is_symlink():
                target = self.folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(regular(source, 64 * 1024**2))
        for source in git.glob('sharedindex.*'):
            (self.folder / source.name).write_bytes(regular(source, 64 * 1024**2))
        refs = common / 'refs'
        if refs.is_symlink():
            raise CommitError('repository references may not be symlinks')
        count = 0
        if refs.exists():
            for parent, dirs, names in os.walk(refs, followlinks=False):
                for name in dirs:
                    if (Path(parent) / name).is_symlink():
                        raise CommitError('repository references may not be symlinks')
                for name in names:
                    count += 1
                    if count > MAX_FILES:
                        raise CommitError('too many repository references')
                    source = Path(parent) / name
                    target = self.folder / source.relative_to(common)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(regular(source, 8192))
        (self.folder / 'refs').mkdir(exist_ok=True)
        objects = common / 'objects'
        if objects.is_symlink():
            raise CommitError('repository object directory may not be a symlink')
        if (objects / 'info').is_symlink():
            raise CommitError('repository object metadata may not be symlinked')
        alternates = objects / 'info/alternates'
        if alternates.exists() or alternates.is_symlink():
            if regular(alternates, 65536).strip():
                raise CommitError('external Git object alternates are not supported; use a self-contained local repository')
        for entry in objects.iterdir():
            if entry.name == 'info':
                if entry.is_symlink():
                    raise CommitError('repository object metadata may not be symlinked')
                continue
            if entry.is_symlink():
                raise CommitError('repository object storage may not contain symlinks')
            if entry.name != 'pack' and not re.fullmatch('[0-9a-f]{2}', entry.name):
                continue
            if not entry.is_dir():
                raise CommitError('invalid Git object directory')
            target = self.folder / 'objects' / entry.name
            target.mkdir(parents=True, exist_ok=True)
            for source in entry.iterdir():
                count += 1
                if count > MAX_FILES:
                    raise CommitError('too many local Git object files')
                if source.is_symlink() or not source.is_file():
                    raise CommitError('repository object files must be regular files')
                if entry.name == 'pack' and source.suffix not in ('.pack', '.idx', '.rev'):
                    continue  # no promisor markers, remotes, alternates or auxiliary commands
                dest = target / source.name
                try:
                    os.link(source, dest, follow_symlinks=False)
                    if not stat.S_ISREG(dest.lstat().st_mode):
                        raise CommitError('repository object files must be regular files')
                except OSError:
                    dest.write_bytes(regular(source, MAX_TOTAL))
        (self.folder / 'objects').mkdir(exist_ok=True)
        self.process = subprocess.Popen(self.argv('cat-file', '--batch'), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self.env, start_new_session=True)
        self.timer = threading.Timer(self.timeout, self.process.kill)
        self.timer.start()

    def argv(self, *args, working=False):
        return [self.git, '--no-pager', '--no-replace-objects', '--git-dir=' + str(self.folder),
                *(['--work-tree=' + str(self.working)] if working else []),
                '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
                '-c', 'protocol.allow=never', '-c', 'protocol.file.allow=never',
                '-c', 'core.warnAmbiguousRefs=true', *args]

    def command(self, *args, check=True, working=False, data=None):
        try:
            result = subprocess.run(self.argv(*args, working=working), input=data, capture_output=True,
                                    env=self.env, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CommitError('local Git operation failed or timed out; nothing was replayed') from exc
        if check and result.returncode:
            raise CommitError('local Git data could not be read; no network fetch is attempted')
        return result

    def close(self):
        if hasattr(self, 'process'):
            self.timer.cancel()
            self.process.kill() if self.process.poll() is None else None
            self.process.wait()
            self.process.stdin.close(); self.process.stdout.close()

    def resolve(self, ref):
        if not isinstance(ref, str) or not ref or len(ref) > 1024 or any(ord(c) < 32 for c in ref):
            raise CommitError('give a nonempty, single-line Git reference')
        if '@{' in ref:
            raise CommitError('reflog/worktree selectors are not supported; use a commit ID or branch/tag')
        if re.fullmatch('[0-9a-fA-F]{4,' + str(self.oid_bytes*2-1) + '}', ref):
            matches = self.command('rev-parse', '--disambiguate=' + ref.lower()).stdout.splitlines()
            if len(matches) > 1:
                raise CommitError(f'ambiguous short reference {ref!r}; give a full commit ID or qualified ref')
        result = self.command('rev-parse', '--verify', '--end-of-options', ref + '^{commit}', check=False)
        if b'ambiguous' in result.stderr.lower():
            raise CommitError(f'ambiguous reference {ref!r}; give a full commit ID or qualified ref')
        value = result.stdout.decode('ascii', errors='replace').strip()
        if result.returncode or not OID.fullmatch(value) or len(value) != self.oid_bytes*2:
            raise CommitError(f'reference {ref!r} does not resolve to a local commit; no fetch was attempted')
        return value

    def read(self, oid, kind):
        try:
            self.process.stdin.write(oid.encode() + b'\n'); self.process.stdin.flush()
            header = self.process.stdout.readline(256).split()
            if len(header) != 3 or header[:2] != [oid.encode(), kind.encode()]:
                raise CommitError('required local Git object is missing or has the wrong type; no fetch is attempted')
            size = int(header[2])
            if not 0 <= size <= MAX_BLOB:
                raise CommitError('Git object exceeds the 128 MiB snapshot object limit')
            parts, remaining = [], size
            while remaining:
                chunk = self.process.stdout.read(min(remaining, 1024**2))
                if not chunk:
                    raise CommitError('local Git object read ended early or timed out')
                parts.append(chunk); remaining -= len(chunk)
            data = b''.join(parts)
            if self.process.stdout.read(1) != b'\n':
                raise CommitError('invalid local Git object framing')
            h = hashlib.new(self.algorithm, kind.encode() + b' ' + str(size).encode() + b'\0' + data)
            if h.hexdigest() != oid:
                raise CommitError('local Git object bytes do not match their object ID')
            return data
        except (OSError, ValueError) as exc:
            if isinstance(exc, CommitError):
                raise
            raise CommitError('cannot read a verified local Git object') from exc

    def extract(self, commit, destination):
        data = self.read(commit, 'commit')
        first = data.split(b'\n', 1)[0]
        tree = first[5:].decode('ascii') if first.startswith(b'tree ') else ''
        if not OID.fullmatch(tree):
            raise CommitError('commit has no valid tree')
        entries = []
        def walk(oid, prefix, depth):
            if depth > 64:
                raise CommitError('commit tree exceeds the directory depth limit')
            raw = self.read(oid, 'tree'); pos = 0
            while pos < len(raw):
                space = raw.index(b' ', pos); nul = raw.index(b'\0', space)
                mode = raw[pos:space]; name = raw[space+1:nul].decode('utf-8')
                end = nul + 1 + self.oid_bytes
                if end > len(raw) or name in ('', '.', '..') or name.casefold() == '.git' or any(
                        ord(c) < 32 or c in '/\\' for c in name):
                    raise CommitError('commit contains an unsafe path')
                child = raw[nul+1:end].hex(); pos = end
                relative = prefix + name
                if len(relative) > 4096:
                    raise CommitError('commit contains an overlong path')
                if mode in (b'40000', b'040000'):
                    walk(child, relative+'/', depth+1)
                elif mode in (b'100644', b'100755'):
                    entries.append((relative, child, mode == b'100755'))
                    if len(entries) > MAX_FILES:
                        raise CommitError('commit exceeds the 100000-file snapshot limit')
                elif mode == b'120000':
                    raise CommitError(f'commit contains a symlink at {relative!r}; snapshots refuse symlinks')
                elif mode == b'160000':
                    raise CommitError(f'commit contains submodule {relative!r}; submodule fetching is disabled')
                else:
                    raise CommitError('commit contains an unsupported tree entry')
        walk(tree, '', 0)
        destination.mkdir(parents=True)
        total = 0
        for name, oid, executable in entries:
            data = self.read(oid, 'blob'); total += len(data)
            if total > MAX_TOTAL:
                raise CommitError('commit exceeds the 2 GiB snapshot limit')
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as f:f.write(data)
            target.chmod(0o755 if executable else 0o644)
        from harness.tree import digest
        return {'commit':commit,'gitTree':tree,'snapshotDigest':digest(destination),
                'checkout':str(destination)}

    def dirty(self, commit, snapshot):
        if self.working is None:
            return False
        result = self.command('diff-index', '--cached', '--quiet', '--no-ext-diff', '--no-textconv',
                              commit, '--', check=False)
        if result.returncode:
            return True
        from harness.tree import files
        tracked = {name:path for name,path in files(snapshot)}
        extra = []
        for parent, dirs, names in os.walk(self.working, followlinks=False):
            if Path(parent) == self.working:
                dirs[:] = [d for d in dirs if d != '.git']
                names = [n for n in names if n != '.git']
            for name in dirs:
                if (Path(parent)/name).is_symlink():return True
            for name in names:
                path=Path(parent)/name; relative=path.relative_to(self.working).as_posix()
                if path.is_symlink():return True
                if relative not in tracked:extra.append(relative)
                if len(extra)>MAX_FILES:raise CommitError('working tree is too large to check HEAD safely')
        for name, expected in tracked.items():
            path=self.working/name
            if not path.is_file() or path.is_symlink():return True
            if regular(path,MAX_BLOB)!=expected.read_bytes():return True
            if bool(path.stat().st_mode & 0o111)!=bool(expected.stat().st_mode & 0o111):return True
        if extra:
            result=self.command('check-ignore','--no-index','-z','--stdin',check=False,working=True,
                                data=b''.join(p.encode()+b'\0' for p in extra))
            if result.returncode not in (0,1):return True
            ignored=set(result.stdout.split(b'\0'))
            if any(p.encode() not in ignored for p in extra):return True
        return False


class Prepared:
    def __init__(self, request, root):
        self.request=request;self.root=root;self.adopted=False

    def adopt(self, destination):
        old=self.root
        # Moving a directory updates its parent entry; keep its contents sealed
        # while the owning store transfers it, then seal the container again.
        old.chmod(0o700)
        old.rename(destination);self.root=destination
        destination.chmod(0o555)
        for side in ('head','base'):
            self.request[side]['checkout']=str(destination/Path(self.request[side]['checkout']).relative_to(old))
            item=self.request['commitInputs']['resolved'][side]
            item['checkout']=str(destination/Path(item['checkout']).relative_to(old))
        self.adopted=True

    def close(self):
        if not self.adopted:remove_tree(self.root)


def prepare(store, request):
    """Resolve again even if a caller supplied checkout, commit or resolved claims."""
    from expectrail.orchestrator import request as req
    request=copy.deepcopy(request);selection=request['commitInputs']
    # Do not create the job store before checking HEAD: an inside-repository
    # store would itself turn a clean working tree into a dirty one.
    working, _git, _common = layout(selection['repository'])
    temporary = Path(tempfile.gettempdir()).resolve()
    if working is not None and temporary.is_relative_to(working):
        raise CommitError('temporary storage must be outside the source working tree; set TMPDIR accordingly')
    root=Path(tempfile.mkdtemp(prefix='expectrail-commit-inputs-',dir=temporary))
    objects=None
    try:
        objects=Objects(selection['repository'],root/'git-view',request['limits']['timeoutSeconds'])
        commits={side:objects.resolve(selection[side+'Ref']) for side in ('base','head')}
        if commits['base']==commits['head']:
            raise CommitError('base and head resolve to the same commit; choose two different commits')
        resolved={side:objects.extract(commits[side],root/'raw'/side) for side in ('base','head')}
        for side in ('base','head'):
            if selection[side+'Ref'] in ('HEAD','@') and objects.dirty(commits[side],root/'raw'/side):
                raise CommitError(f"HEAD means committed snapshot {commits[side]}, not the working tree; "
                    'the repository has index or working-tree changes. Commit/stash them, use a full commit ID, '
                    'or use folder inputs to verify working-tree bytes. Nothing was replayed')
        repository=objects.repo
        objects.close();objects=None;remove_tree(root/'git-view')
        store.root.mkdir(parents=True,exist_ok=True)
        temporary_root = root
        root = Path(tempfile.mkdtemp(prefix='commit-inputs-',dir=store.root))
        try:
            # Move when on one filesystem; copy raw regular files otherwise.
            shutil.move(str(temporary_root/'raw'),str(root/'raw'))
        finally:
            remove_tree(temporary_root)
        for side in ('base','head'):
            resolved[side]['checkout'] = str(root/'raw'/side)
        if 'projectPath' in selection:
            from expectrail import project_job
            options={k:request[k] for k in ('intent','bug') if k in request}
            options.update(execution_class=request['executionClass'],
                timeout_seconds=request['limits']['timeoutSeconds'],idempotency_key=request['idempotencyKey'],
                head_commit=commits['head'],base_commit=commits['base'])
            selected=project_job.prepare(store,root/'raw/head'/selection['projectPath'],
                                         root/'raw/base'/selection['projectPath'],**options)
            pair=Path(selected['head']['checkout']).parent;pair.rename(root/'selected')
            for side in ('base','head'):selected[side]['checkout']=str(root/'selected'/side)
            if 'autoFix' in request:selected['autoFix']=request['autoFix']
            request=selected
        else:
            for side in ('base','head'):
                request[side]={'checkout':str(root/'raw'/side),'commit':commits[side]}
        request['commitInputs']={**selection,'repository':repository,
                                 'resolved':resolved}
        seal(root)
        req.check(request)
        return Prepared(request,root)
    except BaseException:
        if objects is not None:objects.close()
        remove_tree(root)
        raise


def sources(request):
    selection=request.get('commitInputs')
    if selection is None:
        return {side:{'kind':'folder'} if request[side] is not None else None for side in ('head','base')}
    resolved=selection.get('resolved')
    if not resolved:
        raise CommitError('commit inputs have not been resolved by the job store')
    return {side:{'kind':'commit','repository':selection['repository'],'ref':selection[side+'Ref'],
                  **{key:resolved[side][key] for key in ('commit','gitTree','snapshotDigest')}}
            for side in ('head','base')}


def snapshot_problems(request):
    """Check retained raw snapshots without revisiting the caller's repository/ref."""
    from harness import tree
    problems=[]
    for side,item in request.get('commitInputs',{}).get('resolved',{}).items():
        root=Path(item['checkout'])
        try:
            if tree.digest(root)!=item['snapshotDigest']:
                problems.append(f'the resolved {side} commit snapshot changed after creation')
            for parent,dirs,files in os.walk(root):
                if Path(parent).stat().st_mode & 0o222 or any((Path(parent)/n).stat().st_mode & 0o222 for n in files):
                    problems.append(f'the resolved {side} commit snapshot is no longer read-only');break
        except (OSError,ValueError):
            problems.append(f'the resolved {side} commit snapshot cannot be verified')
    return problems
