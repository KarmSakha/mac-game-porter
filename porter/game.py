"""Identify what kind of Windows game a folder holds and which executable to launch."""
from pathlib import Path

SKIP = ('unins', 'setup', 'crash', 'redist', 'vc_redist', 'vcredist', 'dxsetup', 'dxwebsetup', 'dotnet',
        'unitycrashhandler', 'epicwebhelper', 'crashreportclient', 'launcherpatcher', 'easyanticheat',
        'eac', 'battleye', 'uplay', 'quicksfv', 'cefprocess', 'helper')


def _skippable(p):
    n = p.name.lower()
    return any(s in n for s in SKIP)


def detect(game_dir, exe_override=None):
    """Return {'engine': ..., 'exe': path relative to game_dir}."""
    root = Path(game_dir)
    if exe_override:
        exe = root / exe_override
        if not exe.is_file():
            raise SystemExit(f'--exe {exe_override} not found in {root}')
        return {'engine': 'custom', 'exe': str(exe.relative_to(root))}

    # Unreal Engine: the real game binary is <Project>/Binaries/Win64/<Project>-Win64-Shipping.exe;
    # the small bootstrap exe at the root only relaunches it (and hangs under Wine).
    shipping = [p for p in root.glob('*/Binaries/Win64/*-Shipping.exe') if not p.parts[-4].lower() == 'engine']
    if shipping:
        return {'engine': 'unreal', 'exe': str(shipping[0].relative_to(root))}

    exes = [p for p in root.rglob('*.exe') if not _skippable(p)]
    # Unity: <Name>.exe next to <Name>_Data/.
    for p in exes:
        if (p.parent / f'{p.stem}_Data').is_dir():
            return {'engine': 'unity', 'exe': str(p.relative_to(root))}
    if not exes:
        raise SystemExit(f'no game executable found in {root}')
    # Fallback: the biggest executable closest to the root.
    best = max(exes, key=lambda p: (p.stat().st_size, -len(p.parts)))
    return {'engine': 'generic', 'exe': str(best.relative_to(root))}


def find_icon_source(game_dir):
    """An image usable as the app icon, if the game ships one (Unreal splash screens usually do)."""
    root = Path(game_dir)
    for pattern in ('*/Content/Splash/Splash.bmp', '*/Content/Splash/*.bmp', '*_Data/Resources/UnityPlayer.png',
                    '*.ico', '*/*.ico'):
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None
