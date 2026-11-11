# Windows GUI and console in one EXE

A small C example of a **single Windows-subsystem executable** that shows a GUI
when opened without a console and writes to a parent console or inherited
files/pipes when used from a command line.

It preserves redirection independently for stdin, stdout and stderr, including
`NUL`. It connects C streams, CRT descriptors 0–2 and Windows standard handles
to the same destinations. It neither allocates a new console nor simulates keys.
There is no `.com` companion, console launcher or second application EXE.

**Console attachment does not make the shell wait.** In interactive `cmd.exe`,
use `start "" /b /wait hybrid-demo.exe --cli` when completion matters. The empty
quoted argument is the `start` window title; `/b` keeps the existing command
window. Batch files and other hosts have
their own waiting rules. This example does not change them.

## Build and try it

Requirements: Windows, Python 3.10+, and Visual Studio 2022 or newer with the
Desktop development with C++ workload. The code targets MSVC's UCRT, not a
portable replacement for every Windows C runtime. Build from the repo root:

```powershell
python tools/build.py --arch x86
python tests/run_tests.py --exe build/x86/hybrid-demo.exe --keep
```

Use `--arch x64` and `build/x64/hybrid-demo.exe` for the 64-bit build. Both use
`/W4 /WX`, optimisation, `/MT` and `/SUBSYSTEM:WINDOWS`. `/MT` links the C runtime
into the EXE; Windows system DLLs are still required. Build output stays in
`build/`. The application is `hybrid-demo.exe`; Python is only needed to build
and test it.

Double-click the EXE to see the GUI. From `cmd.exe` in the build directory:

```bat
start "" /b /wait hybrid-demo.exe --cli
start "" /b /wait hybrid-demo.exe --help > help.txt 2> errors.txt
start "" /b /wait hybrid-demo.exe --echo < input.txt > output.txt
start "" /b /wait hybrid-demo.exe --cli --exit 23
echo %ERRORLEVEL%
```

From PowerShell, an explicit wait can be written as:

```powershell
$p = Start-Process .\hybrid-demo.exe -ArgumentList '--cli', '--exit', '23' -NoNewWindow -Wait -PassThru
$p.ExitCode
```

`--gui` by itself shows a message box. No arguments chooses text output if a parent
console or output destination is available; otherwise it shows the GUI.
`--cli`, `--echo` and `--help` explicitly request command-line behaviour and never
fall back to a dialog on failure. `--echo` reads until EOF. `--wait-ms 2000`
adds a short delay for manual prompt-behaviour checks. Normal exit codes are
0 (success), 1 (argument allocation), 2 (invalid arguments), 3 (required stream
unavailable), and 4 (I/O failure), or the requested `--exit` value.

## Use the helper in your program

Add `src/hybrid_console.c` and `include/hybrid_console.h` to an MSVC Windows
application. Call the helper on the startup thread, before stdio operations,
descriptor changes or other threads:

```c
const hc_state *io = hc_initialize();
if (io->stream[1].ready) {
    puts("Text output is available");
}
```

Your application decides when to use a GUI. The helper only sets up I/O.
`attached` describes the console association; `stream[i].ready` describes each
usable connection. `attach_error == ERROR_ACCESS_DENIED` means the process was
already attached. A missing parent console is compatible with valid redirected
I/O. Errors in a requested connection are reported through `win_error` or
`crt_error`; a failed attempt is not silently replaced with console output.

The implementation:

1. Duplicates valid inherited handles before calling `AttachConsole`.
2. Tries to attach to the parent's console and recognises an existing attachment.
3. Uses `CONIN$` or `CONOUT$` only for streams without an inherited destination.
4. Gives missing UCRT streams their fixed descriptors before binding the handles.
5. Sets the Windows standard-handle entries to the CRT-owned handles.
6. Makes only console stdout unbuffered. Redirected streams keep normal CRT policy.

Successful connections last for the process lifetime. Do not independently
close handles returned by `GetStdHandle`: the CRT owns those connected handles.
If you later close/reassign a CRT standard stream, update the Windows standard
handle table too. Child-process inheritance is a separate policy: explicitly
select and pass handles when creating children. There is no automatic teardown
or support for repeated attach/detach cycles. A second `hc_initialize()` call
returns the saved state without changing handles or buffered output. It does
not retry a failed initialization.

Setup is best-effort per stream, not transactional. In particular, failure
while repairing a missing CRT stream can leave it unavailable or pointing at
the temporary `NUL` device. Check `ready`; do not keep writing after setup fails.
Preserving a destination does not guarantee it remains writable (for example,
a pipe reader can exit). The demonstration checks its normal stdout writes.

## Tests

The test runner checks the EXE's PE subsystem and runs 32 scenarios per
architecture. Its Python workers create hidden private consoles or run without
a console. They launch the same Windows-subsystem EXE directly; no native
launcher is built. Tests cover:

- Files, pipes, mixed redirection, merged output and `NUL`.
- Ordinary console handles with no redirection.
- Missing stdin, stdout, stderr, or all three, with and without a console.
- Raw descriptor reads/writes, stdio output and Win32 `WriteFile` output.
- Fixed descriptor numbers and matching Windows standard handles.
- An already attached process and repeated setup with pending output.
- CLI output, stdin echo and exit codes.
- The documented `cmd.exe` `start /b /wait` invocation and its exit code.

`--keep` prints a temporary artifact directory with `results.json`, captured
output and per-case state. A nonzero runner exit means failure. Diagnostic
`--probe FILE`, `--probe-input` and `--probe-attached` options belong to this
same demonstration EXE and are used by the tests; they are not necessary in
an application integrating the helper. Probe success returns 37.

Merged stdout/stderr is checked for the exact lines and their counts, allowing
buffering to affect cross-stream order. Other output is compared byte-for-byte.
Console screen buffers are inspected to confirm output actually reaches them.

See [validation](docs/validation.md) for results and limits. Interactive GUI,
Windows Terminal/ConPTY, Ctrl+C and resource-failure injection require additional
testing. The console screen-buffer tests assume a Windows host with classic
console API support; they do not establish terminal-host compatibility.

## Background and licence

This revisits my old [2013 GUI/console article](https://www.tillett.info/2013/05/13/how-to-create-a-windows-program-that-works-as-both-as-a-gui-and-console-application/).
The new implementation preserves redirection and omits the simulated Enter key.

MIT licensed; see [LICENSE](LICENSE).
