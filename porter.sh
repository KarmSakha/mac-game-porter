#!/bin/zsh
# Entry point: ./porter.sh install <repack-or-game-folder> --name "Game" [--dmg]
exec /usr/bin/env python3 -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from porter.cli import main; main()' "${0:A:h}" "$@"
