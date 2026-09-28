"""Run one decoder Stage as a stdin -> stdout filter.

  python3 -m porter.stagerun '<stage json>'

Handles what can't be a plain exec: FreeArc's 1-byte header, decoders that work on
temp files, and the 4x4 block container (blocks decoded in parallel, written in order).
Wine location comes from PORTER_WINE (bin dir) / PORTER_PREFIX / PORTER_UNPACK.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .repack import Stage

CHUNK = 4 << 20


def wine_env():
    env = dict(os.environ)
    env.setdefault('WINEDEBUG', '-all')
    env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
    return env


def resolve_exe(name):
    """Map an arc.ini program token to C:\\unpack\\<file> (case-insensitive, optional .exe)."""
    unpack = Path(os.environ['PORTER_UNPACK'])
    name = name.strip('"')
    lower = {p.name.lower(): p.name for p in unpack.iterdir()}
    for cand in (name, name + '.exe'):
        if cand.lower() in lower:
            return 'C:\\unpack\\' + lower[cand.lower()]
    raise SystemExit(f'decoder {name} not found in the repack payload')


def argv_for(stage, subst=None):
    """Full argv for a stage's command (Windows tools are run through Wine)."""
    cmd = [a if not subst else subst.get(a, a) for a in stage.cmd]
    if stage.kind in ('native',):
        return cmd
    return [os.path.join(os.environ['PORTER_WINE'], 'wine'), resolve_exe(cmd[0])] + cmd[1:]


def pump(src, dst):
    try:
        while True:
            buf = src.read(CHUNK)
            if not buf:
                break
            dst.write(buf)
    finally:
        try:
            dst.close()
        except BrokenPipeError:
            pass


def read_header(stream, stage):
    """Returns (run_decoder, prefix_bytes) per FreeArc C_External.cpp."""
    if not stage.header:
        return True, b''
    b = stream.read(1)
    if not b:
        return False, b''
    if b[0] == 0:
        return False, b''      # stored without compression
    if b[0] == 1:
        return True, b''
    return True, b              # old-format data: byte belongs to the payload


def run_files(stage, data_path, workdir):
    """Decode a temp-file based external: data_path holds the packed input."""
    packed = workdir / stage.packed
    unpacked = workdir / stage.unpacked
    if data_path != packed:
        shutil.move(data_path, packed)
    for _ in range(2):            # Wine start-up occasionally fails once under load
        unpacked.unlink(missing_ok=True)
        r = subprocess.run(argv_for(stage), cwd=workdir, env=wine_env(),
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if unpacked.exists():
            return unpacked
    raise RuntimeError(f'{stage.method}: decoder exited {r.returncode} without writing {stage.unpacked}')


def decode_block(stage, data, index, root):
    """Decode one in-memory block (for 4x4). Returns a path to the decoded bytes."""
    work = Path(tempfile.mkdtemp(prefix=f'blk{index:05d}-', dir=root))
    src = work / 'in.bin'
    src.write_bytes(data)
    if stage.kind == 'files':
        with open(src, 'rb') as f:
            run, prefix = read_header(f, stage)
            rest = f.read()
        if not run:
            (work / 'out.bin').write_bytes(rest)
            return work, work / 'out.bin'
        (work / 'body.bin').write_bytes(prefix + rest)
        src.unlink()
        return work, run_files(stage, work / 'body.bin', work)
    out = work / 'out.bin'
    with open(src, 'rb') as i, open(out, 'wb') as o:
        r = subprocess.run(argv_for(stage), stdin=i, stdout=o, stderr=subprocess.DEVNULL, env=wine_env(),
                           cwd=os.environ.get('PORTER_UNPACK'))
    if r.returncode != 0 and out.stat().st_size == 0:
        raise RuntimeError(f'4x4 block {index}: {stage.method} failed ({r.returncode})')
    return work, out


def run_4x4(stage, stdin, stdout, jobs=4):
    """FreeArc 4x4: int32 version 0, then blocks of int32 orig size (-1 = stored), int32 packed size, data."""
    head = stdin.read(4)
    if len(head) != 4 or struct.unpack('<I', head)[0] != 0:
        raise SystemExit('4x4: not a version-0 stream')
    root = tempfile.mkdtemp(prefix='porter-4x4-')
    pending, index = [], 0
    try:
        with ThreadPoolExecutor(jobs) as pool:
            def flush():
                kind, item = pending.pop(0)
                if kind == 'raw':
                    stdout.write(item)
                    return
                work, out = item.result()
                with open(out, 'rb') as f:
                    shutil.copyfileobj(f, stdout, CHUNK)
                shutil.rmtree(work, ignore_errors=True)
            while True:
                hdr = stdin.read(8)
                if not hdr:
                    break
                if len(hdr) != 8:
                    raise SystemExit('4x4: truncated block header')
                orig, size = struct.unpack('<ii', hdr)
                data = stdin.read(size)
                if len(data) != size:
                    raise SystemExit(f'4x4: block {index} truncated')
                if orig == -1:
                    pending.append(('raw', data))
                else:
                    pending.append(('job', pool.submit(decode_block, stage.inner, data, index, root)))
                index += 1
                while len(pending) > jobs * 2:
                    flush()
            while pending:
                flush()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    stage = Stage.from_json(__import__('json').loads(sys.argv[1]))
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    if stage.kind == '4x4':
        run_4x4(stage, stdin, stdout, int(os.environ.get('PORTER_JOBS', '4')))
    elif stage.kind == 'files':
        work = Path(tempfile.mkdtemp(prefix='porter-files-'))
        try:
            run, prefix = read_header(stdin, stage)
            body = work / 'body.bin'
            with open(body, 'wb') as f:
                f.write(prefix)
                shutil.copyfileobj(stdin, f, CHUNK)
            out = run_files(stage, body, work) if run else body
            with open(out, 'rb') as f:
                shutil.copyfileobj(f, stdout, CHUNK)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:   # pipe with header
        run, prefix = read_header(stdin, stage)
        if not run:
            shutil.copyfileobj(stdin, stdout, CHUNK)
        else:
            p = subprocess.Popen(argv_for(stage), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 env=wine_env(), cwd=os.environ.get('PORTER_UNPACK'))
            if prefix:
                p.stdin.write(prefix)
            t = threading.Thread(target=pump, args=(stdin, p.stdin), daemon=True)
            t.start()
            shutil.copyfileobj(p.stdout, stdout, CHUNK)
            t.join()
            p.wait()
    stdout.flush()


if __name__ == '__main__':
    main()
