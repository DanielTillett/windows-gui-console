/* SPDX-License-Identifier: MIT */
#ifndef HYBRID_CONSOLE_H
#define HYBRID_CONSOLE_H
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

typedef struct hc_stream {
    int ready;              /* stdio, descriptor and Windows handle are connected */
    int inherited;          /* destination was valid before AttachConsole */
    int is_console;
    DWORD win_error;
    int crt_error;
} hc_stream;

typedef struct hc_state {
    int attached;
    DWORD attach_error;     /* ERROR_ACCESS_DENIED means already attached */
    hc_stream stream[3];    /* stdin, stdout, stderr */
} hc_state;

/* Call on the startup thread, before stdio use, other threads or descriptor
   manipulation. Repeated calls return the same state without rebinding.
   Missing streams stay unavailable if no parent console exists.
   Do not CloseHandle(GetStdHandle(...)): the connected handles belong to CRT
   descriptors. This is process-lifetime setup, not an attach/detach manager. */
const hc_state *hc_initialize(void);
#endif
