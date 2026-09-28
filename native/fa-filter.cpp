// fa-filter: decode one FreeArc method (delta, dispack070, 4x4:..., etc.) from stdin to stdout,
// using the original FreeArc 0.67 compression library.
//   fa-filter <method> [external-compressor-ini-file]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "Compression.h"
extern "C" int AddExternalCompressor (char *params);

static unsigned long long total_in = 0, total_out = 0;

static int callback(const char *what, void *data, int size, void *auxdata)
{
    if (strcmp(what, "read") == 0) {
        int got = 0;
        while (got < size) {
            ssize_t r = read(0, (char *)data + got, size - got);
            if (r <= 0) break;
            got += r;
        }
        total_in += got;
        return got;
    }
    if (strcmp(what, "write") == 0) {
        int done = 0;
        while (done < size) {
            ssize_t w = write(1, (char *)data + done, size - done);
            if (w <= 0) return FREEARC_ERRCODE_WRITE;
            done += w;
        }
        total_out += size;
        return size;
    }
    return FREEARC_ERRCODE_NOT_IMPLEMENTED;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: fa-filter <method> [externals.ini]\n"); return 2; }
    if (argc > 2) {
        FILE *f = fopen(argv[2], "rb");
        if (!f) { perror(argv[2]); return 2; }
        static char ini[1 << 16];
        size_t n = fread(ini, 1, sizeof(ini) - 1, f);
        ini[n] = 0;
        fclose(f);
        // One [External compressor:...] section per call, as FreeArc's arc.ini loader does.
        char *p = ini;
        while ((p = strstr(p, "[External compressor:")) != NULL) {
            char *next = strstr(p + 1, "[External compressor:");
            size_t len = next ? (size_t)(next - p) : strlen(p);
            char *section = (char *)malloc(len + 1);
            memcpy(section, p, len);
            section[len] = 0;
            AddExternalCompressor(section);
            p = next ? next : p + len;
        }
    }
    int rc = Decompress(argv[1], callback, NULL);
    fprintf(stderr, "fa-filter: %s rc=%d in=%llu out=%llu\n", argv[1], rc, total_in, total_out);
    return rc < 0 ? 1 : 0;
}
