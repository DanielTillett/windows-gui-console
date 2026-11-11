/* SPDX-License-Identifier: MIT */
#include "hybrid_console.h"
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#include <io.h>

static int report_probe(const wchar_t *path, int input, int preattach) {
    static const DWORD ids[3] = {STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE};
    const hc_state *s;
    intptr_t before[3] = {0, 0, 0};
    int fds[3], repeat = 1, raw[2] = {-1, -1}, read_count = -1;
    DWORD written[2] = {0, 0};
    int win_ok[2] = {0, 0}, matches[3] = {0, 0, 0}, i;
    char line[128], prefix[4];
    FILE *file;
    if (preattach) AttachConsole(ATTACH_PARENT_PROCESS);
    s = hc_initialize();
    for (i = 0; i < 3; ++i)
        if (s->stream[i].ready) before[i] = _get_osfhandle(i);
    if (s->stream[1].ready) fputs("BEFORE\n", stdout);
    if (hc_initialize() != s) repeat = 0;
    fds[0] = _fileno(stdin); fds[1] = _fileno(stdout); fds[2] = _fileno(stderr);
    for (i = 0; i < 3; ++i) {
        if (s->stream[i].ready) {
            if (before[i] != _get_osfhandle(i)) repeat = 0;
            matches[i] = GetStdHandle(ids[i]) == (HANDLE)_get_osfhandle(i);
        }
    }
    if (s->stream[1].ready) fputs("AFTER\nSTDIO_OUT\n", stdout);
    if (s->stream[2].ready) fputs("STDIO_ERR\n", stderr);
    if (input && s->stream[0].ready) {
        read_count = _read(0, prefix, sizeof(prefix));
        if (read_count == 4 && memcmp(prefix, "RAW\n", 4)) read_count = -2;
        if (fgets(line, sizeof(line), stdin) && s->stream[1].ready)
            printf("INPUT:%s", line);
    }
    fflush(NULL); /* Explicit boundary before mixing stdio and raw I/O. */
    for (i = 1; i < 3; ++i) {
        if (s->stream[i].ready) {
            raw[i - 1] = _write(i, i == 1 ? "RAW_OUT\n" : "RAW_ERR\n", 8);
            win_ok[i - 1] = WriteFile(GetStdHandle(ids[i]),
                i == 1 ? "WIN_OUT\r\n" : "WIN_ERR\r\n", 9, &written[i - 1], NULL) != 0;
        }
    }
    file = _wfopen(path, L"w");
    if (!file) return 90;
    fprintf(file, "{\"attached\":%d,\"attach_error\":%lu,\"ready\":[%d,%d,%d],"
        "\"fds\":[%d,%d,%d],\"matches\":[%d,%d,%d],\"repeat\":%d,"
        "\"raw\":[%d,%d],\"win_ok\":[%d,%d],\"written\":[%lu,%lu],\"read\":%d,"
        "\"win_error\":[%lu,%lu,%lu],\"crt_error\":[%d,%d,%d]}\n",
        s->attached, (unsigned long)s->attach_error,
        s->stream[0].ready, s->stream[1].ready, s->stream[2].ready,
        fds[0], fds[1], fds[2], matches[0], matches[1], matches[2], repeat,
        raw[0], raw[1], win_ok[0], win_ok[1],
        (unsigned long)written[0], (unsigned long)written[1], read_count,
        (unsigned long)s->stream[0].win_error, (unsigned long)s->stream[1].win_error,
        (unsigned long)s->stream[2].win_error,
        s->stream[0].crt_error, s->stream[1].crt_error, s->stream[2].crt_error);
    if (fclose(file)) return 91;
    return 37;
}

static int application(int argc, wchar_t **argv) {
    const hc_state *s;
    int i, gui = 0, cli = 0, echo = 0, input = 0, preattach = 0, help = 0;
    int exit_code = 0, invalid = 0;
    DWORD delay = 0;
    const wchar_t *probe = NULL;
    for (i = 1; i < argc; ++i) {
        if (!wcscmp(argv[i], L"--gui")) gui = 1;
        else if (!wcscmp(argv[i], L"--cli")) cli = 1;
        else if (!wcscmp(argv[i], L"--echo")) { echo = 1; cli = 1; }
        else if (!wcscmp(argv[i], L"--help")) { help = 1; cli = 1; }
        else if (!wcscmp(argv[i], L"--probe-input")) input = 1;
        else if (!wcscmp(argv[i], L"--probe-attached")) preattach = 1;
        else if (!wcscmp(argv[i], L"--probe") && i + 1 < argc) probe = argv[++i];
        else if ((!wcscmp(argv[i], L"--exit") || !wcscmp(argv[i], L"--wait-ms")) && i + 1 < argc) {
            int wait = !wcscmp(argv[i], L"--wait-ms");
            wchar_t *end;
            long value = wcstol(argv[++i], &end, 10);
            if (!*argv[i] || *end || value < 0 || value > (wait ? 10000 : 255)) invalid = 1;
            else if (wait) delay = (DWORD)value;
            else exit_code = (int)value;
            cli = 1;
        } else invalid = 1;
    }
    if (gui && (cli || probe || input || preattach)) invalid = 1;
    if (!probe && (input || preattach)) invalid = 1;
    if (gui && !invalid) {
        MessageBoxW(NULL, L"This is the GUI in the same Windows-subsystem EXE.\n"
            L"Run with --cli for text output.", L"Windows GUI and console", MB_OK);
        return 0;
    }
    if (probe && !invalid) return report_probe(probe, input, preattach);
    s = hc_initialize();
    if (invalid) {
        if (s->stream[2].ready) fputs("Invalid arguments. Use --help.\n", stderr);
        return 2;
    }
    if (!cli && argc == 1 && !s->attached &&
        !s->stream[1].ready && !s->stream[2].ready) {
        MessageBoxW(NULL, L"Started without a console or redirected output.\n"
            L"This is the GUI in the same EXE.", L"Windows GUI and console", MB_OK);
        return 0;
    }
    if (!s->stream[1].ready) return 3;
    if (delay) Sleep(delay);
    if (help) {
        puts("Usage: hybrid-demo [--cli | --gui] [--echo] [--exit 0..255] [--wait-ms 0..10000]\n"
             "No arguments: use a parent console/redirected output, otherwise show a GUI.\n"
             "--echo reads stdin until EOF. --gui always shows the GUI.\n"
             "Interactive cmd: use start \"\" /b /wait hybrid-demo.exe --cli to wait for completion.");
    } else if (echo) {
        char buffer[4096];
        size_t count;
        if (!s->stream[0].ready) return 3;
        while ((count = fread(buffer, 1, sizeof(buffer), stdin)) != 0)
            if (fwrite(buffer, 1, count, stdout) != count) return 4;
        if (ferror(stdin)) return 4;
    } else puts("Hello from the console side of the same EXE.");
    if (fflush(stdout) || ferror(stdout)) return 4;
    return exit_code;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show) {
    int argc, result;
    wchar_t **argv;
    (void)instance; (void)previous; (void)command; (void)show;
    argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return 1;
    result = application(argc, argv);
    LocalFree(argv);
    return result;
}
