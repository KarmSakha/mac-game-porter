"""Build the per-game Wine prefix template, the .app bundle and (optionally) a DMG."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import game, paths
from .runtime import log

REGISTRY = r'''Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Software\Wine]
"Version"="win10"

[HKEY_CURRENT_USER\Software\Wine\Mac Driver]
"RetinaMode"="n"
"CaptureDisplaysForFullscreen"="n"

[HKEY_LOCAL_MACHINE\System\CurrentControlSet\Services\winebus]
"Enable SDL"=dword:00000000
'''
# RetinaMode off: Wine reports the screen in points, so fullscreen windows match the display.
# Display capture off: Cmd-Tab keeps working. SDL off: pads come from macOS IOHID; whether they reach
# the game raw (DualSense triggers/haptics) or XInput-converted is chosen per game by the launcher.


def clone(src, dst):
    """APFS clone when possible (instant, no extra space), plain copy otherwise."""
    r = subprocess.run(['cp', '-Rc', str(src), str(dst)], stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)


def prefix_template():
    tpl = paths.RUNTIME / 'prefix-template'
    if (tpl / 'system.reg').exists():
        return tpl
    log('creating game Wine prefix template')
    wine = paths.GAME_WINE / 'bin'
    env = dict(os.environ, WINEPREFIX=str(tpl), WINEDEBUG='-all',
               WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run([str(wine / 'wine64'), 'wineboot', '-i'], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    with tempfile.NamedTemporaryFile('w', suffix='.reg', delete=False) as f:
        f.write(REGISTRY)
    subprocess.run([str(wine / 'wine64'), 'regedit', '/S', 'Z:' + f.name.replace('/', '\\')], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run([str(wine / 'wineserver'), '-w'], env=env, check=False)
    os.unlink(f.name)
    return tpl


def make_icon(game_dir, dest_icns):
    src = game.find_icon_source(game_dir)
    if not src:
        return False
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        png, square, iconset = t / 'src.png', t / 'square.png', t / 'icon.iconset'
        iconset.mkdir()
        if subprocess.run(['sips', '-s', 'format', 'png', str(src), '--out', str(png)],
                          capture_output=True).returncode:
            return False
        dims = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(png)],
                              capture_output=True, text=True).stdout.split()
        side = min(int(dims[dims.index('pixelWidth:') + 1]), int(dims[dims.index('pixelHeight:') + 1]))
        subprocess.run(['sips', '-c', str(side), str(side), str(png), '--out', str(square)], capture_output=True)
        for s in (16, 32, 64, 128, 256, 512):
            for scale, suffix in ((1, ''), (2, '@2x')):
                subprocess.run(['sips', '-z', str(s * scale), str(s * scale), str(square), '--out',
                                str(iconset / f'icon_{s}x{s}{suffix}.png')], capture_output=True)
        return subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(dest_icns)]).returncode == 0


def build_app(name, game_dir, info, out_dir, embed=False):
    """embed=False: game stays outside the bundle (fast first-launch security scan)."""
    slug = paths.slug(name)
    app = Path(out_dir) / f'{name}.app'
    if app.exists():
        shutil.rmtree(app)
    res = app / 'Contents/Resources'
    (app / 'Contents/MacOS').mkdir(parents=True)
    res.mkdir(parents=True)
    exe = app / 'Contents/MacOS' / name
    shutil.copy2(paths.REPO / 'templates/launcher.sh', exe)
    exe.chmod(0o755)
    log('assembling app bundle (APFS clones, no extra disk)')
    clone(paths.GAME_WINE, res / 'wine')
    clone(prefix_template(), res / 'prefix-template')
    conf = (f'GAME_NAME={name!r}\nGAME_SLUG={slug!r}\nGAME_EXE={info["exe"]!r}\nENGINE={info["engine"]!r}\n'
            f'CONTROLLER={info.get("controller", "xinput")!r}\n')
    shutil.copy2(paths.REPO / 'templates/winexinput.inf', res / 'winexinput.inf')
    if embed:
        clone(game_dir, res / 'game')
    else:
        conf += f'GAME_DIR={str(Path(game_dir).resolve())!r}\n'
    (res / 'porter.conf').write_text(conf)
    has_icon = make_icon(game_dir, res / 'AppIcon.icns')
    (app / 'Contents/Info.plist').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>local.macgameporter.{slug}</string>
  <key>CFBundleExecutable</key><string>{name}</string>
  {'<key>CFBundleIconFile</key><string>AppIcon</string>' if has_icon else ''}
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
''')
    log(f'app ready: {app}')
    return app


def build_dmg(name, game_dir, info, out_dir):
    """Self-contained app (game embedded) wrapped in a DMG for another Mac."""
    dmg = Path(out_dir) / f'{name}.dmg'
    dmg.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir) as stage:
        app = build_app(name, game_dir, info, stage, embed=True)
        os.symlink('/Applications', Path(stage) / 'Applications')
        log('creating DMG (compressing; large games take a while)')
        subprocess.run(['hdiutil', 'create', '-volname', name, '-srcfolder', stage, '-fs', 'APFS',
                        '-format', 'ULFO', str(dmg)], check=True)
    log(f'dmg ready: {dmg}')
    return dmg
