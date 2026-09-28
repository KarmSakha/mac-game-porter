/* Minimal FreeArc CLS host: clshost.exe <cls-name.dll> [params]
   Streams stdin -> ClsMain(CLS_DECOMPRESS) -> stdout, mirroring FreeArc's C_CLS.cpp. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>

typedef int __cdecl CLS_CALLBACK(void *instance, int op, void *ptr, int n);
typedef int __cdecl CLS_MAIN(int operation, CLS_CALLBACK *callback, void *instance);

enum { CLS_INIT = 1, CLS_DONE = 2, CLS_DECOMPRESS = 4,
       CLS_FULL_READ = 4096, CLS_PARTIAL_READ = 5120, CLS_FULL_WRITE = 6144, CLS_PARTIAL_WRITE = 7168,
       CLS_MALLOC = 1, CLS_FREE = 2, CLS_GET_PARAMSTR = 3,
       CLS_OK = 0, CLS_ERROR_NOT_IMPLEMENTED = -2, CLS_ERROR_NOT_ENOUGH_MEMORY = -3,
       CLS_ERROR_READ = -4, CLS_ERROR_WRITE = -5 };

static const char *params = "";
static HANDLE in, out;
static unsigned long long total_in, total_out;

static int read_some(char *p, int n, int full)
{
    int got = 0;
    while (got < n) {
        DWORD r = 0;
        if (!ReadFile(in, p + got, n - got, &r, NULL) || r == 0) break;  /* EOF or broken pipe */
        got += r;
        if (!full) break;
    }
    total_in += got;
    return got;
}

static int write_all(const char *p, int n)
{
    int done = 0;
    while (done < n) {
        DWORD w = 0;
        if (!WriteFile(out, p + done, n - done, &w, NULL) || w == 0) return CLS_ERROR_WRITE;
        done += w;
    }
    total_out += n;
    return n;
}

static int __cdecl cb(void *instance, int op, void *ptr, int n)
{
    (void)instance;
    if (op >= CLS_FULL_READ && op < CLS_FULL_READ + 1024) return read_some(ptr, n, 1);
    if (op >= CLS_PARTIAL_READ && op < CLS_PARTIAL_READ + 1024) return read_some(ptr, n, 0);
    if (op >= CLS_FULL_WRITE && op < CLS_PARTIAL_WRITE + 1024) return write_all(ptr, n);
    switch (op) {
    case CLS_GET_PARAMSTR:
        strncpy((char *)ptr, params, n);
        ((char *)ptr)[n - 1] = 0;
        return CLS_OK;
    case CLS_MALLOC:
        *(void **)ptr = malloc(n);
        return *(void **)ptr ? CLS_OK : CLS_ERROR_NOT_ENOUGH_MEMORY;
    case CLS_FREE:
        free(ptr);
        return CLS_OK;
    default:
        return CLS_ERROR_NOT_IMPLEMENTED;
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: clshost <cls-dll> [params]\n"); return 2; }
    if (argc > 2) params = argv[2];
    in = GetStdHandle(STD_INPUT_HANDLE);
    out = GetStdHandle(STD_OUTPUT_HANDLE);
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { fprintf(stderr, "clshost: LoadLibrary(%s) failed: %lu\n", argv[1], GetLastError()); return 3; }
    CLS_MAIN *ClsMain = (CLS_MAIN *)GetProcAddress(dll, "ClsMain");
    if (!ClsMain) { fprintf(stderr, "clshost: no ClsMain in %s\n", argv[1]); return 4; }
    ClsMain(CLS_INIT, NULL, NULL);
    int rc = ClsMain(CLS_DECOMPRESS, cb, NULL);
    ClsMain(CLS_DONE, NULL, NULL);
    fprintf(stderr, "clshost: %s rc=%d in=%llu out=%llu\n", argv[1], rc, total_in, total_out);
    return rc < 0 ? 1 : 0;
}
