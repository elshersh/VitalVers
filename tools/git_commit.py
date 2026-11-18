"""
tools/git_commit.py — Pure-Python Git repository initializer and commit writer.

Creates standard Git loose objects (blob, tree, commit), refs/heads/main, HEAD,
and logs/HEAD when the system `git` binary is not installed on the host machine.
"""
import hashlib
import os
import stat
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT_DIR = os.path.join(ROOT, ".git")

IGNORE_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache"}
IGNORE_EXTS = {".pyc", ".db", ".joblib", ".xlsx"}


def _write_object(obj_type: str, data: bytes) -> str:
    header = f"{obj_type} {len(data)}\0".encode("utf-8")
    store = header + data
    sha1 = hashlib.sha1(store).hexdigest()
    obj_dir = os.path.join(GIT_DIR, "objects", sha1[:2])
    obj_path = os.path.join(obj_dir, sha1[2:])
    if not os.path.exists(obj_path):
        os.makedirs(obj_dir, exist_ok=True)
        with open(obj_path, "wb") as f:
            f.write(zlib.compress(store))
    return sha1


def _build_tree(dir_path: str) -> str:
    entries = []
    for name in sorted(os.listdir(dir_path)):
        if name in IGNORE_DIRS:
            continue
        full = os.path.join(dir_path, name)
        if os.path.isdir(full):
            sub_sha = _build_tree(full)
            if sub_sha:
                entries.append((b"40000", name.encode("utf-8"), bytes.fromhex(sub_sha)))
        elif os.path.isfile(full):
            _, ext = os.path.splitext(name)
            if ext in IGNORE_EXTS:
                continue
            with open(full, "rb") as f:
                blob_sha = _write_object("blob", f.read())
            mode = b"100755" if name.endswith(".sh") else b"100644"
            entries.append((mode, name.encode("utf-8"), bytes.fromhex(blob_sha)))
    # Git sorts tree entries as if directories have a trailing '/'
    entries.sort(key=lambda e: e[1] + (b"/" if e[0] == b"40000" else b""))
    tree_bytes = b"".join(mode + b" " + name + b"\0" + sha_bin for mode, name, sha_bin in entries)
    return _write_object("tree", tree_bytes)


def init_repo():
    os.makedirs(os.path.join(GIT_DIR, "objects"), exist_ok=True)
    os.makedirs(os.path.join(GIT_DIR, "refs", "heads"), exist_ok=True)
    os.makedirs(os.path.join(GIT_DIR, "logs", "refs", "heads"), exist_ok=True)
    head_file = os.path.join(GIT_DIR, "HEAD")
    if not os.path.exists(head_file):
        with open(head_file, "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/main\n")


def commit(message: str, author: str = "NASA Space Apps Team <team@spaceapps.local>") -> str:
    init_repo()
    tree_sha = _build_tree(ROOT)
    ref_path = os.path.join(GIT_DIR, "refs", "heads", "main")
    parent_sha = None
    if os.path.exists(ref_path):
        with open(ref_path, "r", encoding="utf-8") as f:
            parent_sha = f.read().strip() or None

    ts = int(time.time())
    tz = "+0200"
    lines = [f"tree {tree_sha}"]
    if parent_sha:
        lines.append(f"parent {parent_sha}")
    lines.append(f"author {author} {ts} {tz}")
    lines.append(f"committer {author} {ts} {tz}")
    lines.append("")
    lines.append(message.strip())
    commit_data = ("\n".join(lines) + "\n").encode("utf-8")
    commit_sha = _write_object("commit", commit_data)

    with open(ref_path, "w", encoding="utf-8") as f:
        f.write(commit_sha + "\n")

    old_sha = parent_sha or ("0" * 40)
    log_line = f"{old_sha} {commit_sha} {author} {ts} {tz}\tcommit: {message.strip().splitlines()[0]}\n"
    for lp in (os.path.join(GIT_DIR, "logs", "HEAD"), os.path.join(GIT_DIR, "logs", "refs", "heads", "main")):
        with open(lp, "a", encoding="utf-8") as f:
            f.write(log_line)

    print(f"[git] [{commit_sha[:8]}] {message.strip().splitlines()[0]}")
    return commit_sha


def log():
    log_path = os.path.join(GIT_DIR, "logs", "HEAD")
    if not os.path.exists(log_path):
        print("No commits yet.")
        return
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            print(line.strip())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--log":
        log()
    else:
        msg = " ".join(sys.argv[1:]) or "Update project"
        commit(msg)
