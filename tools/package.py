"""Create source and optional per-architecture binary release archives."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", action="store_true", help="Include built x86/x64 EXEs in separate archives")
    args = parser.parse_args()
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    files = [ROOT / name for name in ("README.md", "LICENSE", ".gitignore", ".gitattributes", "requirements-docs.txt")]
    for directory in ("include", "src", "tools", "tests", "docs", ".github"):
        files += [p for p in (ROOT / directory).rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    archives = []
    source = out / "windows-gui-console-source.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, "windows-gui-console/" + path.relative_to(ROOT).as_posix())
    archives.append(source)
    if args.binaries:
        for arch in ("x86", "x64"):
            exe = ROOT / "build" / arch / "hybrid-demo.exe"
            if not exe.is_file():
                raise SystemExit(f"Build {arch} first: python tools/build.py --arch {arch}")
            target = out / f"windows-gui-console-{arch}.zip"
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in (exe, ROOT / "LICENSE", ROOT / "README.md"):
                    archive.write(path, path.name)
            archives.append(target)
    manifest = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in archives)
    (out / "SHA256SUMS.txt").write_text(manifest, encoding="ascii")
    for path in archives:
        print(path)


if __name__ == "__main__":
    main()
