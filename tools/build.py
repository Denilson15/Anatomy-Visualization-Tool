"""
Build the publishable app: inline app.js into index.html and copy the data.

Usage:
    python build.py <src_dir> <dist_dir>
"""

import base64
import shutil
import sys
from pathlib import Path


SRC = Path(sys.argv[1])
DIST = Path(sys.argv[2])
DIST.mkdir(parents=True, exist_ok=True)

page = (SRC / "index.html").read_text(encoding="utf-8")
script = (SRC / "app.js").read_text(encoding="utf-8")

tag = '<script type="module" src="app.js"></script>'
assert tag in page, "script tag not found"
page = page.replace(tag, f'<script type="module">\n{script}\n</script>')
(DIST / "index.html").write_text(page, encoding="utf-8")

for name in ["anatomy.json", "body.json", "attachments.json"]:
    shutil.copy(SRC / name, DIST / name)

# The artifact host serves text but not raw binary, so meshes go out as base64.
for path in sorted(SRC.glob("*.bin")):
    (DIST / f"{path.name}.txt").write_text(base64.b64encode(path.read_bytes()).decode("ascii"))

for path in sorted(DIST.iterdir()):
    print(f"{path.name:26} {path.stat().st_size / 1e6:6.2f} MB")
