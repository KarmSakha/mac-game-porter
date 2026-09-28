"""Understand a FreeArc-based repack (FitGirl and similar): its archives, its bundled
decoders, and how to run each method of a compression chain on macOS.

Every method in a chain becomes a Stage:
  native  - an arm64 tool we build (srep, FreeArc built-ins via fa-filter)
  pipe    - a Windows decoder reading stdin / writing stdout, run under Wine
  seek    - a Windows decoder that must read a real file (xtool/rtool); writes to a FIFO
  files   - a Windows decoder that works on temp files named in arc.ini ($$arcpackedfile$$ ...)
  4x4     - FreeArc's block-parallel container around another Stage
The repack's own arc.ini and cls-*.dll plugins decide which applies, so new repacks
need no code changes as long as they use the same mechanisms.
"""
import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

ARC_FOOTER = b'ArC\x01'
# FreeArc built-ins compiled into fa-filter.
FA_BUILTINS = {'delta', 'dispack', 'dispack070', 'lzma', 'lzma2', 'exe', 'bcj', 'dict', 'rep', 'lzp',
               'tornado', 'grzip', 'mm', 'tta', 'ppmd', 'lz4', 'storing'}
SEEKABLE_TOOLS = re.compile(r'^(xtool|rtool)', re.I)   # read input with seeks; pipes stall them


@dataclass
class Stage:
    method: str
    kind: str
    cmd: list = field(default_factory=list)       # argv; '{in}'/'{out}' placeholders for seek
    packed: str = ''                               # files: name of the input file the tool reads
    unpacked: str = ''                             # files: name of the output file it writes
    header: bool = False                           # files/pipe: FreeArc 1-byte header present
    inner: 'Stage' = None                          # 4x4: per-block stage

    def to_json(self):
        d = dict(self.__dict__)
        d['inner'] = self.inner.to_json() if self.inner else None
        return d

    @staticmethod
    def from_json(d):
        d = dict(d)
        if d.get('inner'):
            d['inner'] = Stage.from_json(d['inner'])
        return Stage(**d)


def is_freearc(path):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            return ARC_FOOTER in f.read()
    except OSError:
        return False


def find_archives(source):
    source = Path(source)
    archives = sorted(p for p in source.iterdir()
                      if p.is_file() and p.suffix.lower() in ('.bin', '.arc', '.0') and is_freearc(p))
    return archives


def is_repack(source):
    source = Path(source)
    return source.is_dir() and (source / 'setup.exe').exists() and bool(find_archives(source))


def extract_payload(source, dest):
    """Pull the installer's embedded helpers (arc.ini, decoders, cls-*.dll) without running it."""
    dest = Path(dest)
    unpack = dest / 'tmp'
    if (unpack / 'arc.ini').exists() or (unpack / 'unarc.dll').exists():
        return unpack
    if not shutil.which('innoextract'):
        raise SystemExit('innoextract is required: brew install innoextract')
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(['innoextract', '-s', '-d', str(dest), '--include', 'tmp', str(Path(source) / 'setup.exe')],
                   check=True)
    if not unpack.exists():
        raise SystemExit('setup.exe payload has no {tmp} files; not a FreeArc repack installer')
    return unpack


def parse_arc_ini(unpack):
    """Return {method_name: section_dict} from the repack's arc.ini (External compressor sections)."""
    ini = Path(unpack) / 'arc.ini'
    sections = {}
    if not ini.exists():
        return sections
    current = None
    for raw in ini.read_text(errors='replace').splitlines():
        line = raw.strip()
        m = re.match(r'\[External compressor:(.+)\]', line, re.I)
        if m:
            current = {'header': '1'}
            for name in m.group(1).split(','):
                sections[name.strip().lower()] = current
            continue
        if line.startswith('['):
            current = None
            continue
        if current is not None and '=' in line and not line.startswith(';'):
            k, v = line.split('=', 1)
            current[k.strip().lower()] = v.strip()
    return sections


def _find_cls(unpack, name):
    for p in Path(unpack).iterdir():
        if p.name.lower() == f'cls-{name}.dll':
            return p.name
    return None


def split_4x4(method):
    """'4x4:b128mb:rzw' -> ('4x4:b128mb', 'rzw'); mirrors parse_4x4 in FreeArc."""
    parts = method.split(':')
    for i, p in enumerate(parts[1:], 1):
        if not (p[:1].isdigit() or p[1:2].isdigit()):
            return ':'.join(parts[:i]), ':'.join(parts[i:])
    raise SystemExit(f'cannot find inner method in {method}')


def plan_stage(method, unpack, ini):
    name, _, params = method.partition(':')
    lname = name.lower()
    if lname == 'srep':
        return Stage(method, 'native', [str(paths.TOOLS / 'srep'), '-d', '-', '-'])
    if lname == '4x4':
        _, inner = split_4x4(method)
        return Stage(method, '4x4', inner=plan_stage(inner, unpack, ini))
    if lname in ini:
        sec = ini[lname]
        cmd = sec.get('unpackcmd', '')
        if not cmd:
            raise SystemExit(f'{method}: arc.ini has no unpackcmd')
        header = sec.get('header', '1') != '0'
        cmd = cmd.replace('{options}', '').replace('{compressor}', name)
        if '<stdin>' in cmd or '<stdout>' in cmd:
            argv = shlex.split(cmd.replace('<stdin>', '').replace('<stdout>', ''), posix=False)
            if SEEKABLE_TOOLS.match(Path(argv[0]).name):
                dashes = [i for i, a in enumerate(argv) if a == '-']
                if len(dashes) >= 2:
                    argv[dashes[-2]], argv[dashes[-1]] = '{in}', '{out}'
                    return Stage(method, 'seek', argv, header=header)
            return Stage(method, 'pipe', argv, header=header)
        packed = sec.get('packedfile', '$$arcpackedfile$$.tmp')
        unpacked = sec.get('datafile', '$$arcdatafile$$.tmp')
        return Stage(method, 'files', shlex.split(cmd, posix=False), packed=packed, unpacked=unpacked, header=header)
    cls = _find_cls(unpack, lname)
    if cls:
        return Stage(method, 'pipe', ['clshost.exe', cls, params])
    if lname in FA_BUILTINS:
        return Stage(method, 'native', [str(paths.TOOLS / 'fa-filter'), method])
    raise SystemExit(f'no decoder for method {method!r} (not in arc.ini, no cls-{lname}.dll, not a FreeArc built-in)')


def plan_chain(chain, unpack, ini):
    """FreeArc chains list encode order ('a+b+c'); decoding runs right to left."""
    return [plan_stage(m.strip(), unpack, ini) for m in chain.split('+')][::-1]


def map_archive(archive):
    out = subprocess.run([str(paths.TOOLS / 'fg-arc-map'), str(archive)], check=True, capture_output=True)
    return json.loads(out.stdout)['blocks']
