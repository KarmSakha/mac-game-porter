#!/bin/zsh
# Build the native helpers the porter needs into $1 (default: ../build/tools).
#   fa-filter   FreeArc 0.67 built-in decoders (delta, dispack, lzma, tornado, ...) as a stdin/stdout filter
#   srep        SREP 3.93 decoder, patched for macOS/arm64
#   clshost.exe 32-bit Windows host for FreeArc CLS plugins (runs under Wine)
#   fg-arc-map  FreeArc archive mapper (solid blocks, offsets, file lists) as JSON
set -euo pipefail
HERE="${0:A:h}"
OUT="${1:-$HERE/../build/tools}"
SRC="$HERE/../build/src"
mkdir -p "$OUT" "$SRC"

need() { command -v "$1" >/dev/null || { echo "missing $1 — install with: $2" >&2; exit 1; }; }
need clang++ "xcode-select --install"
need cargo "brew install rust"
need i686-w64-mingw32-gcc "brew install mingw-w64"
need git "xcode-select --install"

if [[ ! -d "$SRC/freearc" ]]; then
  git clone -q --depth 1 https://github.com/M-Gonzalo/FreeArc "$SRC/freearc"
fi
C="$SRC/freearc/Compression"
mkdir -p "$SRC/shim"; echo '#include <stdlib.h>' > "$SRC/shim/malloc.h"
DEFS=(-DFREEARC_UNIX -DFREEARC_INTEL_BYTE_ORDER -DFREEARC_64BIT -D_SC_AVPHYS_PAGES=_SC_PHYS_PAGES
      -DRUSAGE_THREAD=RUSAGE_SELF -w -Wno-c++11-narrowing -I"$C" -I"$SRC/shim")

echo "==> fa-filter"
CODECS=("$C/Delta/C_Delta.cpp" "$C/DisPack/C_DisPack.cpp" "$C/4x4/C_4x4.cpp" "$C/External/C_External.cpp"
        "$C/LZMA2/C_LZMA.cpp" "$C/LZMA2/C_BCJ.cpp" "$C/Dict/C_Dict.cpp" "$C/REP/C_REP.cpp" "$C/LZP/C_LZP.cpp"
        "$C/Tornado/C_Tornado.cpp" "$C/GRZip/C_GRZip.cpp" "$C/MM/C_MM.cpp" "$C/MM/C_TTA.cpp" "$C/PPMD/C_PPMD.cpp"
        "$C/LZ4/C_LZ4.cpp")
OBJS=()
for f in "$C/Common.cpp" "$C/CompressionLibrary.cpp" "$C/MultiThreading.cpp" "$HERE/fa-filter.cpp" "${CODECS[@]}"; do
  o="$SRC/obj/${f:t:r}.o"; mkdir -p "$SRC/obj"
  if clang++ -c -O2 -fno-exceptions -fno-rtti -DFREEARC_DECOMPRESS_ONLY -D_NO_EXCEPTIONS ${DEFS[@]} "$f" -o "$o" 2>"$o.log"; then
    OBJS+=("$o")
  else
    echo "   skipped ${f:t} (does not build on macOS; see $o.log)"
  fi
done
clang++ ${OBJS[@]} -lpthread -o "$OUT/fa-filter"

echo "==> srep"
rm -rf "$SRC/srep"; mkdir -p "$SRC/srep"; cp "$C"/SREP/*.cpp "$SRC/srep/"; ln -sfn "$C" "$SRC/srep/FA"
python3 "$HERE/patch_srep.py" "$SRC/srep/srep.cpp"
( cd "$SRC/srep" && clang++ -O3 ${DEFS[@]} -I. -IFA -IFA/_Encryption -IFA/_Encryption/headers -IFA/_Encryption/hashes \
    FA/Common.cpp srep.cpp -lpthread -o "$OUT/srep" )

echo "==> clshost.exe"
i686-w64-mingw32-gcc -O2 -s -static -o "$OUT/clshost.exe" "$HERE/clshost.c"

echo "==> fg-arc-map"
( cd "$HERE/freearc-map" && cargo build --release -q --bin fg-arc-map --target-dir "$SRC/cargo" )
cp "$SRC/cargo/release/fg-arc-map" "$OUT/fg-arc-map"

echo "built into $OUT"
