#!/usr/bin/env python3
"""Prepare a mounted data directory, then run the web server unprivileged."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_PATH = os.environ.get("TAJ_APP_PATH") or ("/app/server.py" if Path("/app/server.py").exists() else str(Path(__file__).resolve().parent / "server.py"))


def chown_tree(path: Path, uid: int, gid: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not hasattr(os, "chown"):
        return
    for root, dirs, files in os.walk(path, followlinks=False):
        try:
            os.chown(root, uid, gid, follow_symlinks=False)
        except FileNotFoundError:
            continue
        for name in dirs + files:
            target = os.path.join(root, name)
            try:
                os.chown(target, uid, gid, follow_symlinks=False)
            except FileNotFoundError:
                pass


def main() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        import pwd
        app = pwd.getpwnam("app")
        volume = os.environ.get("TAJ_VOLUME_PATH") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "/data"
        chown_tree(Path(volume).resolve(), app.pw_uid, app.pw_gid)
        os.initgroups(app.pw_name, app.pw_gid)
        os.setgid(app.pw_gid)
        os.setuid(app.pw_uid)
    os.execv(sys.executable, [sys.executable, APP_PATH])


if __name__ == "__main__":
    main()
