# mac-game-porter

Turn a Windows game into a double-clickable macOS app on Apple Silicon, using Apple's
**Game Porting Toolkit** (Wine + **D3DMetal**, DirectX 11/12 → Metal). It can install from:

- a **FreeArc-based repack** (FitGirl-style `setup.exe` + `*.bin`), extracted natively on macOS without
  running the Windows installer, or
- an **already-installed Windows game folder** (copied from a PC, Steam library, etc.).

```sh
./porter.sh setup                                                 # one-time: runtimes + native helpers
./porter.sh install "~/Downloads/Some Game [Repack]" --name "Some Game" --dmg
open ~/Games/"Some Game.app"
```

## What `install` does

1. **Extracts the repack natively** (`porter/extract.py`). Each archive's solid blocks are streamed
   through their decoder chain with pipes, so intermediate stages never hit the disk. The decoder for
   every method is chosen from the repack itself (`porter/repack.py`):

   | Method source | How it runs on macOS |
   |---|---|
   | `srep` | native arm64 SREP 3.93 (built from FreeArc source) |
   | FreeArc built-ins (`delta`, `dispack070`, `lzma`, `tornado`, …) | native `fa-filter` |
   | `arc.ini` external with `<stdin> <stdout>` | the repack's Windows tool under Wine, piped |
   | `arc.ini` external using temp files (`$$arcpackedfile$$`, `datafile=`) | Windows tool under Wine on temp files |
   | `xtool` / `rtool` (need a seekable input) | intermediate file in, FIFO out |
   | `cls-<name>.dll` plugins (`magic2`, `lolz`, …) | `clshost.exe` loads the plugin under Wine |
   | `4x4:…:<inner>` | blocks decoded in parallel with the inner stage, written in order |

   Every extracted file is checked against the archive's size table. The repack's own `unarc.dll`
   is never used: it deadlocks under Wine on macOS.
2. **Picks the executable**: Unreal (`*/Binaries/Win64/*-Shipping.exe`, skipping the bootstrap exe that
   hangs under Wine), Unity (`X.exe` next to `X_Data/`), otherwise the largest non-installer exe.
   Override with `--exe`.
3. **Builds `~/Games/<Name>.app`** containing GPTK Wine, a tuned prefix template and the game
   (APFS clones: no extra disk space). `--dmg` also writes a compressed DMG.

## What the generated app does on launch

- Copies the prefix to `~/Library/Application Support/<Name>/prefix` on first run, so the app can run
  from a read-only DMG. Saves live there too.
- **Display**: Wine Retina mode off and borderless fullscreen at the exact screen size in points.
  This avoids the "window overflows the screen" problem and exclusive-mode switches macOS can't do.
  Unreal `GameUserSettings.ini` is corrected on every launch; Unity gets `-window-mode borderless`.
- **Performance**: `D3DM_ENABLE_METALFX=1` (DLSS upscaling requests go to MetalFX, where the game offers
  DLSS), esync, and the Unreal first-run Epic preset is lowered to High. Rosetta advertises AVX.
- **Controllers**: Wine's SDL backend is off, so pads appear as raw HID devices and games can send their
  own DualSense output reports (adaptive triggers). Use a USB-C cable: DualSense haptics are
  4-channel USB audio and don't work over Bluetooth.

Per-user tweaks go in `~/Library/Application Support/<Name>/launch.conf`, for example:

```sh
MTL_HUD_ENABLED=1        # Metal FPS overlay
EXTRA_ARGS="-dx12"       # extra game arguments
```

Logs are written to `~/Library/Application Support/<Name>/last-run.log`.

## Requirements

Apple Silicon Mac on macOS 14 or later, Xcode command line tools, and Homebrew packages
`innoextract rust mingw-w64` (`native/build.sh` checks for them). Runtimes are downloaded on first use and
verified by SHA-256:
[Wine Staging 11.18](https://github.com/Gcenx/macOS_Wine_builds) for the decoders and
[Game Porting Toolkit 3.0](https://github.com/Gcenx/game-porting-toolkit) for games.
Data and caches live in `~/Library/Application Support/MacGamePorter`.

## Layout

```
porter.sh              entry point
porter/cli.py          setup / install / extract / package commands
porter/repack.py       repack detection, payload extraction (innoextract), arc.ini → decoder plan
porter/extract.py      streaming extractor and verification
porter/stagerun.py     header / temp-file / 4x4 stage runner
porter/game.py         engine and executable detection
porter/package.py      prefix template, .app and DMG
templates/launcher.sh  launcher copied into every app
native/                fa-filter, SREP patch, CLS host, FreeArc archive mapper (vendored, MIT)
```

## Notes

- Nothing proprietary is stored in this repo: Apple's D3DMetal comes with the GPTK download, and
  repack decoders are taken from the repack being installed.
- Only install games you are entitled to.
- The repack's stored checksums use a non-standard format, so verification checks sizes and
  structure, not CRC32.
