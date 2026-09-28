"""Download and verify the Wine runtimes (cached once per machine) and build native tools."""
import hashlib
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from . import paths

RUNTIMES = {
    'wine-staging': {
        'url': 'https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.18/wine-staging-11.18-osx64.tar.xz',
        'sha256': 'b63704b91af269bc026a87f12bd297c4a50caaf570c322e600b6621ef918f127',
        'check': paths.DECODER_WINE / 'bin/wine',
    },
    'gptk': {
        'url': 'https://github.com/Gcenx/game-porting-toolkit/releases/download/Game-Porting-Toolkit-3.0-3/'
               'game-porting-toolkit-3.0-3.tar.xz',
        'sha256': 'd377683937340f914823dbb2e1252b329cbf834ff58907d0293db8cebf0e392e',
        'check': paths.GAME_WINE / 'bin/wine64',
    },
}
NATIVE_TOOLS = ['fa-filter', 'srep', 'clshost.exe', 'fg-arc-map']


def log(msg):
    print(f'[porter] {msg}', flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_runtime(name):
    spec = RUNTIMES[name]
    if spec['check'].exists():
        return
    dest = paths.RUNTIME / name
    dest.mkdir(parents=True, exist_ok=True)
    archive = paths.RUNTIME / Path(spec['url']).name
    if not archive.exists() or sha256(archive) != spec['sha256']:
        log(f'downloading {name} ({spec["url"]})')
        urllib.request.urlretrieve(spec['url'], archive)
    if sha256(archive) != spec['sha256']:
        raise SystemExit(f'{archive.name}: checksum mismatch, refusing to use it')
    log(f'unpacking {name}')
    with tarfile.open(archive) as t:
        try:
            t.extractall(dest, filter='tar')
        except TypeError:           # Python < 3.12 (macOS system python is 3.9)
            t.extractall(dest)
    if not spec['check'].exists():
        raise SystemExit(f'{name}: unexpected archive layout ({spec["check"]} missing)')
    # Downloaded runtimes carry quarantine; strip it so Gatekeeper doesn't stall first launch.
    subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(dest)], check=False)


def ensure_tools():
    if all((paths.TOOLS / t).exists() for t in NATIVE_TOOLS):
        return
    log('building native helpers (one-time)')
    subprocess.run([str(paths.REPO / 'native/build.sh'), str(paths.TOOLS)], check=True)
