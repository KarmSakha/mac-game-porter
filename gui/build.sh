#!/bin/zsh
# Build "Mac Game Porter.app" (SwiftUI front end + bundled porter code and native tools).
#   gui/build.sh [output-dir]      default: build/
set -euo pipefail
REPO="${0:A:h:h}"
OUT="${1:-$REPO/build}"
APP="$OUT/Mac Game Porter.app"
TOOLS="$REPO/build/tools"

for t in fa-filter srep clshost.exe fg-arc-map; do
  [[ -x "$TOOLS/$t" ]] || { "$REPO/native/build.sh" "$TOOLS"; break; }
done

if [[ "$(xcode-select -p 2>/dev/null)" == *CommandLineTools* ]]; then
  echo "warning: xcode-select points at Command Line Tools; SwiftUI macro plugins can be missing." >&2
  echo "         If the build fails with 'SwiftUIMacros not found', run:" >&2
  echo "         sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/porter-src" "$APP/Contents/Resources/tools"
swiftc -O -parse-as-library -target arm64-apple-macos14 "$REPO/gui/MacGamePorter.swift" -o "$APP/Contents/MacOS/MacGamePorter"
cp -R "$REPO/porter" "$REPO/templates" "$REPO/porter.sh" "$APP/Contents/Resources/porter-src/"
rm -rf "$APP/Contents/Resources/porter-src/porter/__pycache__"
cp "$TOOLS"/{fa-filter,srep,clshost.exe,fg-arc-map} "$APP/Contents/Resources/tools/"

# Bundle innoextract so the released app needs no Homebrew. Prefer a prebuilt
# binary in $TOOLS (the release workflow builds one with no Homebrew deps).
INNO=""
if [[ -x "$TOOLS/innoextract" ]]; then
  INNO="$TOOLS/innoextract"
elif command -v innoextract >/dev/null; then
  INNO="$(command -v innoextract)"
fi
if [[ -n "$INNO" ]]; then
  cp "$INNO" "$APP/Contents/Resources/tools/innoextract"
  # Pull in any non-system dylibs the binary needs (e.g. a Homebrew build);
  # a self-contained binary links only /usr/lib and needs no libs/ dir.
  if command -v dylibbundler >/dev/null && \
     otool -L "$APP/Contents/Resources/tools/innoextract" | tail -n +2 \
       | awk '{print $1}' | grep -v '^/usr/lib/\|^/System/\|^@' | grep -q .; then
    mkdir -p "$APP/Contents/Resources/tools/libs"
    dylibbundler -of -b -x "$APP/Contents/Resources/tools/innoextract" \
      -d "$APP/Contents/Resources/tools/libs" -p @executable_path/libs >/dev/null
  fi
else
  echo "note: innoextract not found — repack installs in this build will need 'brew install innoextract'" >&2
fi

# Bundle a standalone Python so the app runs on Macs without Xcode CLT/python3.
# Downloaded once into $TOOLS (cached across rebuilds), then copied into the app.
PYSTANDALONE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.13.18+20261110-aarch64-apple-darwin-install_only_stripped.tar.gz"
if [[ ! -x "$TOOLS/python/bin/python3" ]]; then
  mkdir -p "$TOOLS"
  echo "downloading standalone Python for bundling..." >&2
  curl -fsSL "$PYSTANDALONE_URL" -o "$TOOLS/python.tar.gz"
  rm -rf "$TOOLS/.python-tmp" && mkdir "$TOOLS/.python-tmp"
  tar -xzf "$TOOLS/python.tar.gz" -C "$TOOLS/.python-tmp"
  if [[ -x "$TOOLS/.python-tmp/python/bin/python3" ]]; then
    mv "$TOOLS/.python-tmp/python" "$TOOLS/python"
  else
    mv "$TOOLS/.python-tmp" "$TOOLS/python"
  fi
  rm -rf "$TOOLS/.python-tmp" "$TOOLS/python.tar.gz"
fi
cp -R "$TOOLS/python" "$APP/Contents/Resources/tools/python"
swift "$REPO/gui/make_icon.swift" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Mac Game Porter</string>
  <key>CFBundleIdentifier</key><string>io.github.karmsakha.macgameporter</string>
  <key>CFBundleExecutable</key><string>MacGamePorter</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "built: $APP"
