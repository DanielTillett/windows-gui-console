# Validation

Local validation on 12 November 2026 used Windows 11 build 26300, Python
3.13.15 and Visual Studio 18.10.12217.157 with the installed MSVC x86/x64
desktop tools. These are the observed test environment, not minimum versions.

Commands, run sequentially from the standalone repository root:

```powershell
python tools/build.py --arch x86
python tests/run_tests.py --exe build/x86/hybrid-demo.exe --keep
python tools/build.py --arch x64
python tests/run_tests.py --exe build/x64/hybrid-demo.exe --keep
```

Results: **x86 32 passed / 0 failed; x64 32 passed / 0 failed**.
Both builds use `/W4 /WX`; the PE subsystem check passed for both.
The 32 scenarios consist of 27 private-parent cases, three direct CLI cases
and two `cmd.exe start /b /wait` cases. No companion native launcher was built.

The source ZIP was also extracted into a new temporary directory containing
spaces, rebuilt as x86, and tested independently: **32 passed / 0 failed**.
The source archive was checked to exclude build outputs and Git metadata;
each binary archive contains exactly one EXE.

The shell tests use an explicit `exit /b !errorlevel!` in the hosting
`cmd /v:on /c` command to propagate the result to Python, and `/b` to retain
the existing console/redirected streams. This is test-host plumbing; callers
using a live cmd prompt can inspect `%ERRORLEVEL%` after `start /wait`.

Readiness is checked independently for each standard stream. Tests verify
stdio text, fixed CRT descriptor numbers, raw `_write` results, raw `_read`
plus stdio input, `GetStdHandle` consistency and `WriteFile` results. Private
console screen buffers are checked for exact marker counts. Pending output
and descriptor/handle identities are checked across repeated initialization.

## Limits

- GUI display, double-click behaviour and interactive prompt placement have
  not been manually validated on this release build.
- Windows Terminal/ConPTY, Ctrl+C/cancellation, services, other CRTs and older
  Windows versions are not established by these results.
- API/resource failures such as `DuplicateHandle`, `freopen`, `_dup2` and
  `SetStdHandle` failures have not been fault-injected. Setup is not transactional.
- Text-mode streams are used; this is not a Unicode console or binary-I/O
  abstraction. Arguments use wide-character Windows APIs; output samples are ASCII.
- Child-process handle inheritance after initialization is not tested or
  provided as an API by this helper.
- The GitHub Actions workflow has been supplied but has not run on GitHub.
- No application-specific workload, licence system or private data is part of
  this standalone project or its validation.

Before using the helper in a larger application, test that application's GUI,
terminal hosts, cancellation policy, output encoding and stream lifetime rules.
