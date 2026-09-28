"""Stream every solid block of a repack through its decoder chain into the game folder.

Stages are connected with pipes, so nothing touches the disk except where a decoder
requires a seekable input file (xtool/rtool); there the chain is cut into segments and
the intermediate is written once, then read back by the seeking decoder.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import paths, repack
from .runtime import log
from .stagerun import argv_for

CHUNK = 4 << 20
MIN_FREE_GB = 8


def windows_path(p):
    return 'Z:' + str(p).replace('/', '\\')


class Extractor:
    def __init__(self, source, workdir, outdir, status_path=None):
        self.source = Path(source)
        self.work = Path(workdir)
        self.out = Path(outdir)
        self.tmp = self.work / 'tmp'
        self.logs = self.work / 'logs'
        self.prefix = self.work / 'decoder-prefix'
        self.status_path = Path(status_path) if status_path else self.work / 'status.json'
        self.status = {}
        for d in (self.tmp, self.logs, self.out):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- environment ----------
    def prepare(self):
        payload = repack.extract_payload(self.source, self.work / 'payload')
        self.unpack = self.prefix / 'drive_c/unpack'
        wine = paths.DECODER_WINE / 'bin'
        self.env = dict(os.environ, WINEPREFIX=str(self.prefix), PORTER_WINE=str(wine),
                        PORTER_UNPACK=str(self.unpack), TMPDIR=str(self.tmp), WINEDEBUG='-all',
                        WINEDLLOVERRIDES='winemenubuilder.exe=d',
                        PYTHONPATH=str(paths.REPO) + os.pathsep + os.environ.get('PYTHONPATH', ''))
        os.environ.update({k: self.env[k] for k in ('PORTER_WINE', 'PORTER_UNPACK', 'WINEPREFIX')})
        if not (self.prefix / 'system.reg').exists():
            log('creating decoder Wine prefix')
            subprocess.run([str(wine / 'wine'), 'wineboot', '-i'], env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([str(wine / 'wineserver'), '-w'], env=self.env, check=False)
        if not self.unpack.exists():
            shutil.copytree(payload, self.unpack)
        shutil.copy2(paths.TOOLS / 'clshost.exe', self.unpack / 'clshost.exe')
        self.ini = repack.parse_arc_ini(self.unpack)
        # A persistent server avoids start-up races when several Wine decoders launch at once.
        subprocess.run([str(wine / 'wineserver'), '-p'], env=self.env, check=False)

    def shutdown(self):
        subprocess.run([str(paths.DECODER_WINE / 'bin/wineserver'), '-k'], env=self.env, check=False,
                       stderr=subprocess.DEVNULL)

    def update(self, **kw):
        self.status.update(kw, updated=time.time())
        tmp = self.status_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.status))
        os.replace(tmp, self.status_path)
        free = shutil.disk_usage(self.out).free / 1e9
        if free < MIN_FREE_GB:
            raise SystemExit(f'stopping: only {free:.0f} GB free on disk')

    # ---------- stage processes ----------
    def stage_argv(self, stage, infile=None, outfile=None):
        nice = ['/usr/bin/nice', '-n', '10']
        if stage.kind in ('files', '4x4') or (stage.kind == 'pipe' and stage.header):
            return nice + [sys.executable, '-m', 'porter.stagerun', json.dumps(stage.to_json())]
        if stage.kind == 'seek':
            return nice + argv_for(stage, {'{in}': windows_path(infile), '{out}': windows_path(outfile)})
        return nice + argv_for(stage)

    def start_segment(self, segment, source, label, index):
        procs, prev_out, feeder, progress = [], None, None, {'read': 0}
        for i, stage in enumerate(segment):
            name = stage.method.split(':')[0]
            log_f = open(self.logs / f'{label}.seg{index}.{i}.{name}.log', 'wb')
            if i == 0 and stage.kind == 'seek':
                fifo = self.tmp / f'{label}.seg{index}.fifo'
                fifo.unlink(missing_ok=True)
                os.mkfifo(fifo)
                p = subprocess.Popen(self.stage_argv(stage, source[1], fifo), env=self.env,
                                     cwd=self.unpack, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=log_f)
                procs.append(p)
                prev_out = open(fifo, 'rb')          # blocks until the decoder opens it
                continue
            if i == 0 and source[0] == 'file':
                stdin = open(source[1], 'rb')
            elif i == 0:
                stdin = subprocess.PIPE
            else:
                stdin = prev_out
            p = subprocess.Popen(self.stage_argv(stage), stdin=stdin, stdout=subprocess.PIPE,
                                 stderr=log_f, env=self.env, cwd=self.unpack)
            if i == 0 and source[0] == 'archive':
                feeder = threading.Thread(target=self.feed, args=(source, p.stdin, progress), daemon=True)
                feeder.start()
            if prev_out is not None:
                prev_out.close()
            procs.append(p)
            prev_out = p.stdout
            time.sleep(0.5)                           # stagger Wine start-ups
        return procs, prev_out, feeder, progress

    @staticmethod
    def feed(source, sink, progress):
        _, archive, offset, size = source
        try:
            with open(archive, 'rb', buffering=0) as src:
                src.seek(offset)
                left = size
                while left:
                    buf = src.read(min(CHUNK, left))
                    if not buf:
                        raise IOError('archive ended early')
                    sink.write(buf)
                    left -= len(buf)
                    progress['read'] = size - left
        except BrokenPipeError:
            progress['error'] = 'a decoder closed its input early'
        finally:
            try:
                sink.close()
            except BrokenPipeError:
                pass

    @staticmethod
    def finish(procs, feeder, progress, label):
        if feeder:
            feeder.join()
        codes = [p.wait() for p in procs]
        if progress.get('error'):
            raise SystemExit(f'{label}: {progress["error"]}')
        return codes

    # ---------- blocks ----------
    def extract_block(self, archive, block, label):
        stages = repack.plan_chain(block['method'], self.unpack, self.ini)
        segments = [[]]
        for st in stages:
            if st.kind == 'seek' and segments[-1]:
                segments.append([])
            segments[-1].append(st)
        files = block['files']
        total = sum(f['size'] for f in files if not f['dir'])
        source = ('archive', archive, block['offset'], block['compsize'])
        started, temps = time.time(), []
        log(f'{label}: {block["method"]} -> ' + ' | '.join(f'{s.method}[{s.kind}]' for s in stages))

        for si, segment in enumerate(segments[:-1]):
            inter = self.tmp / f'{label}.seg{si}.bin'
            procs, out, feeder, progress = self.start_segment(segment, source, label, si)
            done, last = 0, 0
            with open(inter, 'wb') as o:
                while buf := out.read(CHUNK):
                    o.write(buf)
                    done += len(buf)
                    if time.time() - last > 2:
                        last = time.time()
                        self.update(phase=f'{label}: unpacking (step {si + 1}/{len(segments)})',
                                    read=progress['read'], compsize=block['compsize'], intermediate=done,
                                    written=0, total=total, seconds=int(last - started))
            self.finish(procs, feeder, progress, label)
            if source[0] == 'file':
                os.unlink(source[1])
            source = ('file', inter)
            temps.append(inter)

        procs, out, feeder, progress = self.start_segment(segments[-1], source, label, len(segments) - 1)
        written, last = 0, 0
        for f in files:
            dest = self.out / f['path']
            if f['dir']:
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            left = f['size']
            with open(dest, 'wb') as o:
                while left:
                    buf = out.read(min(CHUNK, left))
                    if not buf:
                        raise SystemExit(f'{label}: stream ended {left} bytes early in {f["path"]}; '
                                         f'decoder logs: {self.logs}')
                    o.write(buf)
                    left -= len(buf)
                    written += len(buf)
                    if time.time() - last > 2:
                        last = time.time()
                        self.update(phase=f'{label}: writing (step {len(segments)}/{len(segments)})',
                                    file=f['path'], written=written, total=total,
                                    read=progress['read'] if source[0] == 'archive' else block['compsize'],
                                    compsize=block['compsize'], seconds=int(last - started))
        extra = out.read(1)
        out.close()
        self.finish(procs, feeder, progress, label)
        if extra:
            raise SystemExit(f'{label}: decoders produced more data than the archive lists')
        for t in temps:
            t.unlink(missing_ok=True)
        for fifo in self.tmp.glob(f'{label}.seg*.fifo'):
            fifo.unlink()
        log(f'{label}: {written / 1e9:.2f} GB in {time.time() - started:.0f}s')

    def run(self):
        self.prepare()
        state_file = self.work / 'extracted.json'
        done = json.loads(state_file.read_text()) if state_file.exists() else []
        try:
            for archive in repack.find_archives(self.source):
                if archive.name in done:
                    log(f'{archive.name}: already extracted')
                    continue
                for i, block in enumerate(repack.map_archive(archive)):
                    if block['compsize'] == 0:
                        for f in block['files']:
                            if f['dir']:
                                (self.out / f['path']).mkdir(parents=True, exist_ok=True)
                        continue
                    self.extract_block(archive, block, f'{archive.stem}#{i}')
                done.append(archive.name)
                state_file.write_text(json.dumps(done))
        finally:
            self.shutdown()
        self.verify()

    def verify(self):
        bad, count, total = [], 0, 0
        for archive in repack.find_archives(self.source):
            for block in repack.map_archive(archive):
                for f in block['files']:
                    if f['dir']:
                        continue
                    p = self.out / f['path']
                    count += 1
                    total += f['size']
                    if not p.is_file() or p.stat().st_size != f['size']:
                        bad.append(f['path'])
        if bad:
            raise SystemExit(f'{len(bad)} files missing or wrong size, e.g. {bad[:3]}')
        log(f'verified {count} files, {total / 1e9:.2f} GB')
