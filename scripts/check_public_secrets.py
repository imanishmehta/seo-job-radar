"""Fail deployment if the configured credential appears in public files."""
import base64
import os
from pathlib import Path
import subprocess

key = os.environ.get("SERPER_API_KEY", "")
if key:
    raw = key.encode()
    patterns = (raw, base64.b64encode(raw))
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    paths = {Path(p) for p in tracked if p} | set(Path("site").rglob("*"))
    for path in paths:
        if path.is_file() and any(pattern in path.read_bytes() for pattern in patterns):
            raise SystemExit("Deployment blocked: credential detected in public output. Rotate credential and remove the exposure.")
print("Public-output credential check passed.")
