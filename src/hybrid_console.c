/* SPDX-License-Identifier: MIT */
#include "hybrid_console.h"
#include <stdio.h>
#include <stdint.h>
#include <errno.h>
#include <io.h>
#include <fcntl.h>

static hc_state state;
static int initialized;
static const DWORD std_ids[3] = {
    STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
};

static int valid_handle(HANDLE h) {
    DWORD type;
    if (!h || h == INVALID_HANDLE_VALUE) return 0;
    SetLastError(ERROR_SUCCESS);
    type = GetFileType(h);
    return type != FILE_TYPE_UNKNOWN || GetLastError() == ERROR_SUCCESS;
}

/* source remains caller-owned. The duplicate becomes CRT-owned. */
static int bind_stream(HANDLE source, int id, hc_stream *result) {
    HANDLE copy;
    DWORD console_mode;
    int fd, flags = (id == 0 ? _O_RDONLY : _O_WRONLY) | _O_TEXT;
    FILE *stream = id == 0 ? stdin : id == 1 ? stdout : stderr;
    if (!DuplicateHandle(GetCurrentProcess(), source, GetCurrentProcess(),
                         &copy, 0, FALSE, DUPLICATE_SAME_ACCESS)) {
        result->win_error = GetLastError();
        return 0;
    }
    /* UCRT reserves descriptors 0..2, but a GUI FILE can report -2. Merely
       freopen-ing it can allocate descriptor 3 or later. Reclaim its fixed
       slot BEFORE allocating the source descriptor, and verify the result. */
    if (_fileno(stream) < 0) {
        int placeholder = _open("NUL", flags);
        if (placeholder < 0) goto crt_failure;
        if (_dup2(placeholder, id) != 0) {
            int saved_errno = errno;
            _close(placeholder);
            errno = saved_errno;
            goto crt_failure;
        }
        if (placeholder != id) _close(placeholder);
        if (_close(id) != 0) goto crt_failure;
        if (!freopen("NUL", id == 0 ? "r" : "w", stream)) goto crt_failure;
    }
    if (_fileno(stream) != id) {
        errno = EINVAL;
        goto crt_failure;
    }
    fd = _open_osfhandle((intptr_t)copy, flags);
    if (fd < 0) goto crt_failure;
    /* From here, do not CloseHandle(copy): the descriptor owns it. */
    if (_dup2(fd, id) != 0) {
        result->crt_error = errno;
        _close(fd);
        return 0;
    }
    if (fd != id) _close(fd);
    clearerr(stream);
    if (!SetStdHandle(std_ids[id], (HANDLE)_get_osfhandle(id))) {
        result->win_error = GetLastError();
        return 0;
    }
    result->is_console = GetConsoleMode(source, &console_mode) != 0;
    /* Keep normal buffering for files/pipes. stdin/stderr retain CRT policy. */
    if (id == 1 && result->is_console && setvbuf(stream, NULL, _IONBF, 0)) {
        result->crt_error = errno ? errno : EIO;
        return 0;
    }
    return 1;

crt_failure:
    result->crt_error = errno ? errno : EIO;
    CloseHandle(copy);
    return 0;
}

const hc_state *hc_initialize(void) {
    HANDLE saved[3] = {NULL, NULL, NULL};
    int i;
    if (initialized) return &state;
    initialized = 1;
    /* Snapshot independently. AttachConsole can replace the standard table.
       A failed duplicate must NOT turn a redirected stream into console I/O. */
    for (i = 0; i < 3; ++i) {
        HANDLE h = GetStdHandle(std_ids[i]);
        if (valid_handle(h)) {
            state.stream[i].inherited = 1;
            if (!DuplicateHandle(GetCurrentProcess(), h, GetCurrentProcess(),
                                 &saved[i], 0, FALSE, DUPLICATE_SAME_ACCESS))
                state.stream[i].win_error = GetLastError();
        }
    }
    state.attached = AttachConsole(ATTACH_PARENT_PROCESS) != 0;
    if (!state.attached) {
        state.attach_error = GetLastError();
        if (state.attach_error == ERROR_ACCESS_DENIED) state.attached = 1;
    }
    for (i = 0; i < 3; ++i) {
        HANDLE h = saved[i];
        if (!h && !state.stream[i].inherited && state.attached) {
            h = CreateFileW(i == 0 ? L"CONIN$" : L"CONOUT$",
                            i == 0 ? GENERIC_READ : GENERIC_WRITE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                            OPEN_EXISTING, 0, NULL);
            if (h == INVALID_HANDLE_VALUE) state.stream[i].win_error = GetLastError();
        }
        if (h && h != INVALID_HANDLE_VALUE) {
            state.stream[i].ready = bind_stream(h, i, &state.stream[i]);
            CloseHandle(h);
        }
    }
    return &state;
}
