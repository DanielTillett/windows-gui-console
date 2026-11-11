"""Integration tests for the one Windows-subsystem EXE. No native launcher."""
import argparse
from contextlib import ExitStack
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve()


def winapi():
    api = ct.WinDLL("kernel32", use_last_error=True)
    api.GetStdHandle.argtypes = [wt.DWORD]
    api.GetStdHandle.restype = wt.HANDLE
    api.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p,
                               wt.DWORD, wt.DWORD, wt.HANDLE]
    api.CreateFileW.restype = wt.HANDLE
    api.CloseHandle.argtypes = [wt.HANDLE]
    return api


def capture_console(api):
    class Coord(ct.Structure):
        _fields_ = [("x", ct.c_short), ("y", ct.c_short)]

    class Rect(ct.Structure):
        _fields_ = [(n, ct.c_short) for n in ("left", "top", "right", "bottom")]

    class Info(ct.Structure):
        _fields_ = [("size", Coord), ("cursor", Coord), ("attributes", wt.WORD),
                    ("window", Rect), ("maximum", Coord)]

    api.GetConsoleScreenBufferInfo.argtypes = [wt.HANDLE, ct.POINTER(Info)]
    api.ReadConsoleOutputCharacterW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD,
                                               Coord, ct.POINTER(wt.DWORD)]
    handle = api.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
    if handle == wt.HANDLE(-1).value:
        return None
    try:
        info = Info()
        if not api.GetConsoleScreenBufferInfo(handle, ct.byref(info)):
            raise ct.WinError(ct.get_last_error())
        count = info.size.x * info.size.y
        buffer = ct.create_unicode_buffer(count + 1)
        read = wt.DWORD()
        if not api.ReadConsoleOutputCharacterW(handle, buffer, count, Coord(0, 0), ct.byref(read)):
            raise ct.WinError(ct.get_last_error())
        return buffer[:read.value]
    finally:
        api.CloseHandle(handle)


def worker(config_path):
    """Python is the test parent only; it is not shipped with the demo."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api = winapi()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESTDHANDLES
    handles = [api.GetStdHandle(ct.c_ulong(-10 - i).value) for i in range(3)]
    for i in config["drop"]:
        handles[i] = 0
    startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
    command = [config["exe"], "--probe", config["state"]]
    if config["read"]:
        command.append("--probe-input")
    if config["preattach"]:
        command.append("--probe-attached")
    child = subprocess.Popen(command, startupinfo=startup, close_fds=False)
    try:
        code = child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        code = 99
    screen = capture_console(api)
    Path(config["worker_report"]).write_text(json.dumps({"code": code, "screen": screen}), encoding="utf-8")
    return code


def check_pe(exe):
    data = exe.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise AssertionError("Not a PE executable")
    # Subsystem offset is the same in PE32 and PE32+ optional headers.
    if struct.unpack_from("<H", data, pe + 24 + 68)[0] != 2:
        raise AssertionError("The executable must use /SUBSYSTEM:WINDOWS")


def scenario(exe, work, number, parent, sink="pipes", drop=(), read=False, preattach=False):
    name = f"{parent}/{sink}/drop={list(drop)}/input={read}/already={preattach}"
    config = dict(exe=str(exe), state=str(work / f"{number}.state.json"),
                  worker_report=str(work / f"{number}.worker.json"), drop=list(drop),
                  read=read, preattach=preattach)
    config_path = work / f"{number}.config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    flags = subprocess.CREATE_NEW_CONSOLE if parent == "console" else subprocess.DETACHED_PROCESS
    out_file, err_file = work / f"{number}.out", work / f"{number}.err"
    with ExitStack() as stack:
        out, err = subprocess.PIPE, subprocess.PIPE
        if sink in ("files", "mixed"):
            out = stack.enter_context(out_file.open("wb"))
        if sink == "files":
            err = stack.enter_context(err_file.open("wb"))
        if sink == "nul":
            out = stack.enter_context(open(os.devnull, "wb"))
        if sink == "merged":
            err = subprocess.STDOUT
        if sink == "console":
            out = err = None
        result = subprocess.run([sys.executable, str(HERE), "--worker", str(config_path)],
                                input=None if sink == "console" else b"RAW\nsample input\n",
                                stdout=out, stderr=err, startupinfo=startup,
                                creationflags=flags, timeout=20)
    stdout = out_file.read_bytes() if sink in ("files", "mixed") else result.stdout or b""
    stderr = err_file.read_bytes() if sink == "files" else result.stderr or b""
    state = json.loads(Path(config["state"]).read_text())
    parent_state = json.loads(Path(config["worker_report"]).read_text(encoding="utf-8"))
    ready = [int(parent == "console" or i not in drop) for i in range(3)]
    expected = [b"BEFORE\r\nAFTER\r\nSTDIO_OUT\r\n", b"STDIO_ERR\r\n"]
    if read and ready[0]:
        expected[0] += b"INPUT:sample input\r\n"
    expected[0] += b"RAW_OUT\r\nWIN_OUT\r\n"
    expected[1] += b"RAW_ERR\r\nWIN_ERR\r\n"
    for i in (1, 2):
        if not ready[i] or sink == "console" or i in drop or (i == 1 and sink == "nul"):
            expected[i - 1] = b""
    if sink == "merged":
        expected[0] += expected[1]
        expected[1] = b""
    checks = dict(exit_code=result.returncode == parent_state["code"] == 37,
                  stdout=sorted(stdout.splitlines()) == sorted(expected[0].splitlines())
                  if sink == "merged" else stdout == expected[0],
                  stderr=stderr == expected[1], ready=state["ready"] == ready,
                  attachment=bool(state["attached"]) == (parent == "console"),
                  fixed_descriptors=all(not ready[i] or state["fds"][i] == i for i in range(3)),
                  win32_matches=state["matches"] == ready,
                  raw_writes=state["raw"] == [8 if ready[i] else -1 for i in (1, 2)],
                  win32_writes=state["win_ok"] == ready[1:],
                  write_counts=state["written"] == [9 if ready[i] else 0 for i in (1, 2)],
                  repeated_setup=state["repeat"] == 1,
                  no_setup_errors=state["win_error"] == [0, 0, 0] and state["crt_error"] == [0, 0, 0])
    if read:
        checks["raw_input"] = state["read"] == (4 if ready[0] else -1)
    if preattach:
        checks["already_attached"] = state["attach_error"] == 5
    if parent == "console":
        screen = parent_state["screen"] or ""
        checks["console_capture"] = parent_state["screen"] is not None
        for i, markers in ((1, ("BEFORE", "AFTER", "STDIO_OUT", "RAW_OUT", "WIN_OUT")),
                           (2, ("STDIO_ERR", "RAW_ERR", "WIN_ERR"))):
            for marker in markers:
                checks["screen_" + marker] = screen.count(marker) == int(sink == "console" or i in drop)
    return dict(name=name, passed=all(checks.values()), checks=checks, state=state,
                stdout=stdout.decode("ascii", "replace"), stderr=stderr.decode("ascii", "replace"))


def run(exe, work):
    check_pe(exe)
    cases = [(parent, sink, (), False, False)
             for parent in ("console", "detached")
             for sink in ("pipes", "files", "mixed", "merged", "nul")]
    cases += [("console", "console", drop, False, False) for drop in ((), (0,), (1,), (2,), (0, 1, 2))]
    cases += [(parent, "pipes", drop, False, False)
              for parent in ("console", "detached")
              for drop in ((0,), (1,), (2,), (0, 1, 2))]
    cases += [(parent, "pipes", (), True, False) for parent in ("console", "detached")]
    cases += [("console", "pipes", (), False, True), ("console", "console", (), False, True)]
    results = []
    for number, case in enumerate(cases):
        try:
            result = scenario(exe, work, number, *case)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            result = dict(name=str(case), passed=False, error=str(error))
        results.append(result)
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['name']}", flush=True)
        if not result["passed"]:
            print(json.dumps(result, indent=2))
    # Direct invocation uses no helper EXE and waits through the process API.
    for args, input_data, expected, code in (
        (["--cli", "--exit", "23"], None, b"Hello from the console side of the same EXE.\r\n", 23),
        (["--echo"], b"hello\nworld\n", b"hello\r\nworld\r\n", 0),
        (["--invalid"], None, b"", 2),
    ):
        result = subprocess.run([str(exe), *args], input=input_data, capture_output=True, timeout=10)
        ok = result.returncode == code and result.stdout == expected
        results.append(dict(name="direct " + " ".join(args), passed=ok))
        print(f"{'PASS' if ok else 'FAIL'} {results[-1]['name']}")
    # Exercise the documented cmd.exe waiting syntax, including quoted paths.
    # No custom launcher participates: cmd.exe is the caller's shell.
    commands = [
        (f'start "" /b /wait "{exe}" --cli --exit 23', None,
         b"Hello from the console side of the same EXE.\r\n", 23),
        (f'start "" /b /wait "{exe}" --echo', b"shell input\n", b"shell input\r\n", 0),
    ]
    for number, (command, data, expected, code) in enumerate(commands):
        # cmd parses quotes itself; list2cmdline's C-runtime escaping is wrong
        # for embedded shell syntax such as start's empty title.
        result = subprocess.run(f'cmd.exe /d /v:on /s /c "{command} & exit /b !errorlevel!"', input=data,
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=15)
        ok = result.returncode == code and result.stdout == expected
        results.append(dict(name=f"cmd start /wait {number}", passed=ok,
                            exit_code=result.returncode, stdout=result.stdout.decode("ascii", "replace")))
        print(f"{'PASS' if ok else 'FAIL'} {results[-1]['name']}")
    passed = sum(r["passed"] for r in results)
    summary = dict(passed=passed, failed=len(results) - passed, windows_subsystem=True, cases=results)
    (work / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"{passed} passed, {len(results) - passed} failed; PE subsystem is Windows")
    return 0 if passed == len(results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows is required")
    if args.worker:
        return worker(args.worker)
    if not args.exe:
        parser.error("Supply --exe build/x86/hybrid-demo.exe (or x64)")
    exe = args.exe.resolve(strict=True)
    if args.keep:
        work = Path(tempfile.mkdtemp(prefix="windows_gui_console_"))
        print(f"Artifacts: {work}", flush=True)
        return run(exe, work)
    with tempfile.TemporaryDirectory(prefix="windows_gui_console_") as directory:
        return run(exe, Path(directory))


if __name__ == "__main__":
    raise SystemExit(main())
