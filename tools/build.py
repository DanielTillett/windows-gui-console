"""Build the single Windows-subsystem demo with installed MSVC desktop tools."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(arch):
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output(
        [str(vswhere), "-latest", "-products", "*", "-requires",
         "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
        text=True).strip()
    if not install:
        raise RuntimeError("Install Visual Studio with Desktop development with C++.")
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvarsall.bat"
    out = ROOT / "build" / arch
    out.mkdir(parents=True, exist_ok=True)
    script = out / "build.cmd"
    script.write_text(
        f'@echo off\ncall "{vcvars}" {arch} >nul\nif errorlevel 1 exit /b 1\n'
        'cl /nologo /W4 /WX /O2 /MT /TC /utf-8 /D_CRT_SECURE_NO_WARNINGS '
        '/I"..\\..\\include" "..\\..\\src\\hybrid_console.c" "..\\..\\src\\demo.c" '
        '/Fe:hybrid-demo.exe /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib\n'
        'exit /b %errorlevel%\n', encoding="utf-8")
    result = subprocess.run(["cmd.exe", "/d", "/c", str(script)], cwd=out,
                            capture_output=True, text=True, timeout=120)
    (out / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    print(out / "hybrid-demo.exe")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("x86", "x64"), default="x86")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This example requires Windows.")
    build(args.arch)
