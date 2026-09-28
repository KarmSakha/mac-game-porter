#!/usr/bin/env python3
"""Patch FreeArc 0.67's SREP 3.93 source so it builds on macOS/arm64.

- BigAlloc/BigFree take a large-page mode argument that the Unix branch of
  Common.h drops; restore the Windows signature on top of MyAlloc/MyFree.
- file_seek_cur is only defined for Windows; use fseeko on Unix.
- `index` collides with <strings.h>'s index(); rename SREP's type.
"""
import sys

path = sys.argv[1]
src = open(path, encoding='latin-1').read()
anchor = '#include "../MultiThreading.cpp"\n'
if anchor not in src:
    sys.exit('patch_srep: unexpected srep.cpp layout')
shim = anchor + '''#ifndef FREEARC_WIN
#undef BigAlloc
#undef BigFree
enum LPType {DEFAULT, FORCE, DISABLE, TRY};
static LPType DefaultLargePageMode = TRY;
static inline void *BigAlloc (int64 size, LPType = DEFAULT) {return MyAlloc(size);}
static inline void  BigFree  (void *p)                       {MyFree(p);}
#undef file_seek
#define file_seek(stream,pos)      (fseeko(stream, (pos), SEEK_SET))
#define file_seek_cur(stream,pos)  (fseeko(stream, (pos), SEEK_CUR))
#define index srep_index
#endif
'''
src = src.replace(anchor, shim, 1).replace('#include "../', '#include "FA/')
open(path, 'w', encoding='latin-1').write(src)
