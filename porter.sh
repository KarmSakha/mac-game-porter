#!/bin/zsh
# Entry point: ./porter.sh install <repack-or-game-folder> --name "Game" [--dmg]
# Prefer the Python bundled inside the app so it also runs on Macs without
# Xcode Command Line Tools installed; fall back to any python3 on PATH.
PYBIN=""
if [[ -n "${PORTER_TOOLS:-}" && -x "$PORTER_TOOLS/python/bin/python3" ]]; then
  PYBIN="$PORTER_TOOLS/python/bin/python3"
else
  PYBIN="$(command -v python3 2>/dev/null)"
fi
if [[ -z "$PYBIN" ]]; then
  echo "python3 is required (bundled copy missing from the app and none found on PATH)" >&2
  exit 1
fi
exec "$PYBIN" -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from porter.cli import main; main()' "${0:A:h}" "$@"
