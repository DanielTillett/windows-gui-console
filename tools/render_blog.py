"""Render the repository's blog draft as a WordPress-ready HTML fragment."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# Optional local install: python -m pip install --target build/docs-tools -r requirements-docs.txt
sys.path.insert(0, str(ROOT / "build" / "docs-tools"))
try:
    import markdown
except ImportError:
    raise SystemExit("Install requirements-docs.txt first; see this script's local-install comment.")

source = (ROOT / "docs" / "blog-post.md").read_text(encoding="utf-8")
title, body = source.split("\n", 1)
assert title.startswith("# ")
html = markdown.markdown(body.strip(), extensions=["fenced_code"])
(ROOT / "docs" / "blog-post.html").write_text(html + "\n", encoding="utf-8")
print(title[2:])
print(ROOT / "docs" / "blog-post.html")
