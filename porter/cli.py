"""mac-game-porter command line.

  porter install <repack-or-game-folder> --name "Game Name" [--exe relative\\path.exe] [--dmg] [--keep-extracted]
  porter extract <repack-folder> <output-folder>
  porter package <game-folder> --name "Game Name" [--exe ...] [--dmg]
  porter setup                               download runtimes and build native helpers
"""
import argparse
import os
import shutil
import signal
from pathlib import Path

from . import game, package, paths, repack, runtime
from .extract import Extractor
from .runtime import log


def cmd_setup(_):
    runtime.ensure_tools()
    runtime.ensure_runtime('wine-staging')
    runtime.ensure_runtime('gptk')
    package.prefix_template()
    log('setup complete')


def extract_repack(source, name, outdir=None):
    runtime.ensure_tools()
    runtime.ensure_runtime('wine-staging')
    work = paths.WORK / paths.slug(name)
    out = Path(outdir) if outdir else paths.GAME_DATA / paths.slug(name)
    Extractor(source, work, out).run()
    return out, work


def cmd_extract(a):
    extract_repack(a.source, Path(a.output).name, a.output)


def cmd_package(a):
    runtime.ensure_runtime('gptk')
    info = game.detect(a.source, a.exe)
    log(f'engine: {info["engine"]}, executable: {info["exe"]}')
    out = Path(a.out or paths.GAMES)
    out.mkdir(parents=True, exist_ok=True)
    app = package.build_app(a.name, a.source, info, out)
    if a.dmg:
        package.build_dmg(a.name, a.source, info, out)
    return app


def cmd_install(a):
    source = Path(a.source).expanduser()
    if repack.is_repack(source):
        log(f'{source.name}: FreeArc repack with {len(repack.find_archives(source))} archive(s)')
        game_dir, work = extract_repack(source, a.name)
    elif source.is_dir():
        game_dir, work = paths.GAME_DATA / paths.slug(a.name), None
        if not game_dir.exists():
            log(f'copying game into {game_dir} (APFS clone when on the same disk)')
            game_dir.parent.mkdir(parents=True, exist_ok=True)
            package.clone(source, game_dir)
    else:
        raise SystemExit(f'{source}: not a folder')
    a.source = game_dir
    app = cmd_package(a)
    if work and not a.keep_extracted:
        shutil.rmtree(work, ignore_errors=True)       # decoder prefix, payload, logs
    log(f'done. Launch: open "{app}"')


def _stop(signum, _frame):
    # Cancel from the GUI (or Ctrl-C): stop every decoder in our process group, then unwind so
    # cleanup (Wine server shutdown) still runs.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.killpg(0, signal.SIGTERM)
    raise SystemExit('cancelled')


def main():
    try:
        os.setpgrp()                 # own process group, so a cancel reaches all decoder processes
    except OSError:
        pass
    signal.signal(signal.SIGTERM, _stop)
    ap = argparse.ArgumentParser(prog='porter', description='Port Windows games to macOS (GPTK + D3DMetal).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('setup')
    s.set_defaults(func=cmd_setup)
    for name in ('install', 'package'):
        s = sub.add_parser(name)
        s.add_argument('source')
        s.add_argument('--name', required=True)
        s.add_argument('--exe', help='game executable relative to the game folder (auto-detected otherwise)')
        s.add_argument('--out', help=f'where to put the .app/.dmg (default {paths.GAMES})')
        s.add_argument('--dmg', action='store_true', help='also build a DMG')
        if name == 'install':
            s.add_argument('--keep-extracted', action='store_true', help='keep the decoder work folder')
        s.set_defaults(func=cmd_install if name == 'install' else cmd_package)
    s = sub.add_parser('extract')
    s.add_argument('source')
    s.add_argument('output')
    s.set_defaults(func=cmd_extract)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
