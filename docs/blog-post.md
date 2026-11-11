# A Windows GUI and console application in one EXE, revisited

Back in 2013 I wrote about [making a Windows application work as both a GUI and a console program](https://www.tillett.info/2013/05/13/how-to-create-a-windows-program-that-works-as-both-as-a-gui-and-console-application/). The idea was simple: build a Windows-subsystem EXE so that double-clicking it does not open a console window, then use `AttachConsole(ATTACH_PARENT_PROCESS)` when it is run from a command prompt.

I still like the single-EXE approach. However, there are a few things I would now do differently. The most useful change is to preserve redirected input and output. The least useful part of the old example was the simulated Enter key, which I would leave out entirely.

The example described here builds one Windows-subsystem EXE. There is no companion `.com` file and no console launcher. It can show a GUI, write to a parent's console, or work with files and pipes when there is no console at all. There is one limitation worth stating upfront: attaching to a console does not make the command shell wait for the program to finish.

## Preserve redirection before attaching

The original example reopens stdout and stderr on `CONOUT$`. This gets text onto the console, but it also overrides the destination the caller requested. For example:

```bat
hybrid-demo.exe --help > help.txt 2> errors.txt
```

Opening `CONOUT$` for both streams sends the output back to the console instead of those files. The same issue affects pipes. Simply checking whether a console exists is therefore not enough.

The new helper saves a duplicate of each valid standard handle before calling `AttachConsole`. This ordering matters because attaching can change the process's standard-handle table. It then considers stdin, stdout and stderr independently. An existing destination is kept. Only a missing stream is connected to `CONIN$` or `CONOUT$`, and only when there is a console to connect to. Microsoft's [standard-handle documentation](https://learn.microsoft.com/en-us/windows/console/getstdhandle) describes both redirected handles and the changes made during attachment.

This also preserves deliberate output to `NUL`. A valid non-console destination should not be treated as missing just because it is not a regular file. Mixed redirection works too: stdout can go to a file while stderr goes to a console or a pipe.

## A console and an output stream are different things

It is tempting to return one Boolean from the setup function: console or no console. That loses useful information.

A process can have no console and still have perfectly good stdout and stderr pipes. It can also attach successfully but fail to connect one of its C streams. There is another wrinkle: `AttachConsole` fails with `ERROR_ACCESS_DENIED` when the process is already attached. That is different from having no parent console. These cases are documented in [AttachConsole](https://learn.microsoft.com/en-us/windows/console/attachconsole).

The helper therefore returns a small state structure containing the attachment result and separate status for each stream. Application code can ask the question it actually needs answered:

```c
const hc_state *io = hc_initialize();
if (io->stream[1].ready) {
    puts("Text output is available");
}
```

The helper does not decide whether to show a GUI. The demonstration chooses a GUI when started without arguments, a parent console or an output destination. `--gui` explicitly selects the GUI, while `--cli` explicitly selects command-line behaviour. If a required stream is unavailable in CLI mode, the program returns an error rather than showing an unexpected dialog in a script.

## The easily missed CRT descriptor problem

Windows has standard `HANDLE` values, the C runtime has integer file descriptors, and stdio has `FILE` streams. Connecting one layer does not necessarily fix the others.

In an MSVC GUI application, `_fileno(stdout)` can return `-2` when no stdout stream is associated with it. Microsoft calls out this case in the [_fileno documentation](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/fileno?view=msvc-170).

A seemingly reasonable repair is to reopen stdout on `NUL` and duplicate the required handle onto that descriptor. In testing, this exposed a subtle error: stdout could end up on descriptor 4 instead of descriptor 1. `printf()` worked and the text appeared on the screen, but `_write(1, ...)` failed. A test that looked only for printed text passed despite the incorrect binding.

The new code repairs the missing standard descriptor before allocating the descriptor for the saved handle. It verifies that stdin, stdout and stderr are associated with 0, 1 and 2 respectively, then connects the saved destination using `_open_osfhandle` and `_dup2`. It also sets the corresponding Windows standard handle to the CRT-owned handle, so `WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), ...)` uses the same destination.

There is some important ownership bookkeeping here. Once `_open_osfhandle` succeeds, the CRT owns the handle passed to it. Closing both the descriptor and that handle would be wrong. The helper duplicates handles explicitly and closes each temporary resource according to who owns it. See Microsoft's documentation for [_open_osfhandle](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170) and [_dup2](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/dup-dup2?view=msvc-170).

This setup belongs at the start of the program, before using stdio or starting worker threads. It is not a general-purpose function for repeatedly detaching and reattaching a running application. Repeated initialization returns the saved state without changing descriptors or discarding buffered text. If initialization failed, it does not silently retry.

## Keep buffering where it is useful

The old helper disabled buffering after attaching. Immediate console output is useful, but a redirected file or pipe need not use the same policy.

The new version makes console stdout unbuffered and leaves redirected stdout with its normal CRT buffering. It also leaves stdin and stderr at their defaults. This avoids imposing a write for every small stdout operation when output is redirected.

An implication for tests is that merged stdout and stderr do not necessarily retain the order of the original `printf` and `fprintf` calls. If ordering matters, flush at the required boundaries or deliberately choose a different buffering policy. The test probe explicitly flushes stdio before it exercises raw descriptor and Windows writes.

## Why I removed the simulated Enter key

The original post described sending Enter at exit as a way to release the command prompt. The more accurate explanation is that interactive `cmd.exe` normally does not wait for a Windows-subsystem application. The prompt may already be active while the application is producing output.

Sending Enter does not change that waiting behaviour. It is another keyboard event, potentially submitted while the user is typing something else. Checking the foreground console window does not turn it into a reliable completion mechanism, and modern terminal hosts make window-based assumptions less useful. In a pseudoconsole, `GetConsoleWindow` does not refer to the visible terminal window in the usual way. [Microsoft documents that distinction here](https://learn.microsoft.com/en-us/windows/console/getconsolewindow).

For this single-EXE approach, I would rather make the waiting requirement explicit:

```bat
start "" /b /wait hybrid-demo.exe --cli
start "" /b /wait hybrid-demo.exe --help > help.txt 2> errors.txt
start "" /b /wait hybrid-demo.exe --echo < input.txt > output.txt
```

The empty quoted string is the window title expected by `start`. `/b` avoids starting a separate command window, and `/wait` asks the shell to wait for completion. Command scripts and other shells have their own behaviour; Microsoft's [start documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/start) specifically distinguishes interactive GUI launches from command-script execution. `/b` also has documented implications for Ctrl+C handling, so an application's cancellation behaviour still needs testing.

This is the tradeoff. One Windows-subsystem EXE can provide both interfaces without a console appearing on an ordinary GUI launch. `AttachConsole` alone cannot also guarantee synchronous behaviour in every shell.

## Testing the actual Windows behaviour

These details are difficult to establish with mocked API calls. The test system launches the real EXE from Python parents with either a hidden private console or no console. Python is part of the test harness only; the application remains one EXE.

The tests exercise files, pipes, `NUL`, merged output, ordinary console handles, missing standard handles and an already attached process. They check text written through stdio, descriptors 1 and 2, and Windows `WriteFile`. They also check the descriptor numbers, standard-handle consistency, input, repeat initialization and exit codes. Console output is read back from the private screen buffer rather than inferred from an empty pipe.

The build uses MSVC's UCRT and supports x86 and x64 builds. The suite checks the PE header to make sure the executable really uses the Windows subsystem. The repository's validation notes record the local results and the remaining manual checks, including GUI behaviour, Windows Terminal and Ctrl+C. Passing the automated suite does not establish compatibility with every terminal or C runtime.

## Building the example

With Python 3.10 or newer and Visual Studio 2022 or newer with the C++ desktop tools installed, run these commands from the repository root:

```powershell
python tools/build.py --arch x86
python tests/run_tests.py --exe build/x86/hybrid-demo.exe --keep
```

The output is `build/x86/hybrid-demo.exe`. Use `x64` in both commands for a 64-bit build. Double-click it for the GUI, or run it from a command prompt using the examples above.

For another application, the reusable pieces are `hybrid_console.h` and `hybrid_console.c`. The demonstration and tests show the calling contract, error handling and descriptor checks. The code is MIT licensed. The part I would carry forward from the original approach is attempting to attach to the parent's console; the parts I would change are preserving the caller's streams and leaving the keyboard alone.
