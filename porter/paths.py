"""Filesystem layout shared by every porter command."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('PORTER_HOME', Path.home() / 'Library/Application Support/MacGamePorter'))
TOOLS = Path(os.environ.get('PORTER_TOOLS', REPO / 'build/tools'))
RUNTIME = DATA / 'runtime'
WORK = DATA / 'work'
GAME_DATA = DATA / 'games'          # extracted games live here, outside the .app bundles
GAMES = Path(os.environ.get('PORTER_GAMES', Path.home() / 'Games'))

# Wine used only for the repack's Windows decoders (known-good with them).
DECODER_WINE = RUNTIME / 'wine-staging/Wine Staging.app/Contents/Resources/wine'
# Wine + Apple D3DMetal used to run games.
GAME_WINE = RUNTIME / 'gptk/Game Porting Toolkit.app/Contents/Resources/wine'


def slug(name):
    return ''.join(c if c.isalnum() else '-' for c in name).strip('-').lower() or 'game'
