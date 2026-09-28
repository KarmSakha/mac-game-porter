"""Identify what kind of Windows game a folder holds and which executable to launch."""
from pathlib import Path

SKIP = ('unins', 'setup', 'crash', 'redist', 'vc_redist', 'vcredist', 'dxsetup', 'dxwebsetup', 'dotnet',
        'unitycrashhandler', 'epicwebhelper', 'crashreportclient', 'launcherpatcher', 'easyanticheat',
        'eac', 'battleye', 'uplay', 'quicksfv', 'cefprocess', 'helper')


def _skippable(p):
    n = p.name.lower()
    return any(s in n for s in SKIP)


def controller_mode(exe_path):
    """'raw' when the game drives DualSense/DualShock itself over HID (so Wine must expose the real
    device), otherwise 'xinput' (Wine converts pads to XInput, which most games expect)."""
    import mmap
    try:
        with open(exe_path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            uses_hid = m.find(b'HID.DLL') >= 0 or m.find(b'hid.dll') >= 0
            knows_sony = any(m.find(s) >= 0 for s in (b'DualSense', b'libScePad', b'DualShock'))
    except (OSError, ValueError):
        return 'xinput'
    return 'raw' if uses_hid and knows_sony else 'xinput'


def detect(game_dir, exe_override=None):
    """Return {'engine': ..., 'exe': path relative to game_dir, 'controller': 'raw'|'xinput'}."""
    info = _detect(game_dir, exe_override)
    info['controller'] = controller_mode(Path(game_dir) / info['exe'])
    return info


def _detect(game_dir, exe_override=None):
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
