"""
tools/export_release.py — Whitelist-only exporter from d:\\NASA 2\\project to d:\\NASA 2\\vitalverse_release.

Copies strictly the runtime files required to run the Vitalverse website cleanly
while excluding docs/markdown, tests, eval sets, datasets, tools, secrets, and
any artifact exceeding 50 MB.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import shutil
import sys

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MiB / 50 MB hard cap per Rule 8

ROOT_CONFIG_FILES = (
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "open_vitalverse.bat",
    "open_vitalverse.sh",
)

CORE_RUNTIME_FILES = (
    "ai_health_model.py",
    "health_engine.py",
    "offline_ai_chatbot.py",
    "resource_facts.py",
)

AI_RUNTIME_SUPPORT_FILES = (
    "config/demo_credentials.json",
    "config/project_config.json",
    "data_raw/team_supplied/07_health_indicators_schema.json",
    "data/astronaut_health_app.db",
    "models/health_model.joblib",
)

PHASE2_PLUS_SCRIPTS = (
    "scripts/seed_demo.py",
    "scripts/simulate_feed.py",
)

FORBIDDEN_TOP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "docs",
    "tests",
    "eval",
    "references",
    "review",
    "screenshots",
    "frontend_extra",
    "all_project_codes",
    "tools",
    "uploads_private",
}

FORBIDDEN_ROOT_FILES = {
    ".env",
    "analysis_to_excel.py",
    "astronaut_health.db",
    "blind_test.py",
    "chatbot_eval_sets.py",
    "generate_data.py",
    "run_all.py",
    "run_all.sh",
    "test_chatbot.py",
}

FORBIDDEN_EXTS = {".md", ".pdf", ".xlsx", ".zip", ".ipynb", ".pyc", ".pyo", ".pyd"}


def _is_seeded_demo_media(rel_posix: str) -> bool:
    return rel_posix.startswith("uploads_private/A001/demo_") and rel_posix.endswith((".png", ".wav"))


def _is_forbidden(rel_posix: str, allow_generated_data_import: bool = False) -> bool:
    if _is_seeded_demo_media(rel_posix):
        return False
    parts = rel_posix.split("/")
    top = parts[0]
    if top in FORBIDDEN_TOP_DIRS:
        return True
    if "__pycache__" in parts:
        return True
    name = parts[-1]
    ext = Path(name).suffix.lower()
    if ext in FORBIDDEN_EXTS:
        return True
    # Only requirements.txt, font license files inside static/fonts/, and backend prompt templates are allowed among .txt files
    if (
        ext == ".txt"
        and rel_posix != "requirements.txt"
        and rel_posix != "backend/prompts/online_system.txt"
        and not rel_posix.startswith("static/fonts/")
    ):
        return True
    if len(parts) == 1 and name in FORBIDDEN_ROOT_FILES:
        if name == "generate_data.py" and allow_generated_data_import:
            return False
        return True
    if rel_posix.startswith("data/astronaut_health_eval.db"):
        return True
    return False


def _discover_runtime_root_modules(project_root: Path) -> set[str]:
    """Return top-level Python module filenames recursively imported by runtime entrypoints."""
    seed_files: list[Path] = [project_root / name for name in CORE_RUNTIME_FILES if (project_root / name).is_file()]
    app_py = project_root / "app.py"
    if app_py.is_file():
        seed_files.append(app_py)
    backend_dir = project_root / "backend"
    if backend_dir.is_dir():
        seed_files.extend(p for p in backend_dir.rglob("*.py") if "__pycache__" not in p.parts)

    resolved: set[str] = {p.name for p in seed_files if p.parent == project_root}
    queue = list(seed_files)
    seen_paths: set[Path] = set()
    blocked_non_backend = {"blind_test", "chatbot_eval_sets", "test_chatbot", "analysis_to_excel", "run_all"}

    while queue:
        path = queue.pop()
        if path in seen_paths or not path.is_file():
            continue
        seen_paths.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".", 1)[0]]
            for mod in mods:
                if mod in blocked_non_backend:
                    continue
                if mod == "generate_data" and not app_py.is_file():
                    continue
                py_candidate = project_root / f"{mod}.py"
                if py_candidate.is_file() and py_candidate.name not in resolved:
                    resolved.add(py_candidate.name)
                    queue.append(py_candidate)
    return resolved


def collect_whitelist(project_root: Path) -> tuple[list[tuple[Path, str, int]], list[str]]:
    """Collect whitelisted (src_path, rel_posix, byte_size) entries and warnings."""
    entries: dict[str, tuple[Path, int]] = {}
    warnings: list[str] = []

    def _add(rel_posix: str, src: Path, *, allow_generate_data: bool = False) -> None:
        if not src.is_file():
            return
        if _is_forbidden(rel_posix, allow_generated_data_import=allow_generate_data):
            warnings.append(f"Excluded by policy: {rel_posix}")
            return
        size = src.stat().st_size
        if size > MAX_FILE_BYTES:
            warnings.append(f"Skipped (>50 MB limit): {rel_posix} ({size:,} bytes)")
            return
        entries[rel_posix] = (src, size)

    # 1. All runtime frontend assets under static/
    static_dir = project_root / "static"
    if static_dir.is_dir():
        for src in sorted(static_dir.rglob("*")):
            if src.is_file():
                rel = src.relative_to(project_root).as_posix()
                _add(rel, src)

    # 2. Root runtime metadata / environment files
    for rel in ROOT_CONFIG_FILES:
        _add(rel, project_root / rel)

    # 3. AI Model & AI Chatbot runtime modules + required runtime config/schema/db/model files
    runtime_mods = _discover_runtime_root_modules(project_root)
    app_py = project_root / "app.py"
    for mod_rel in sorted(runtime_mods):
        _add(mod_rel, project_root / mod_rel, allow_generate_data=(app_py.is_file() and mod_rel == "generate_data.py"))

    for rel in AI_RUNTIME_SUPPORT_FILES:
        _add(rel, project_root / rel)

    # Selected runtime artifacts from models/ if referenced in config/runtime_artifacts.txt
    selected_manifest = project_root / "config" / "runtime_artifacts.txt"
    if selected_manifest.is_file():
        for raw_line in selected_manifest.read_text(encoding="utf-8").splitlines():
            rel = raw_line.strip().replace("\\", "/")
            if rel and not rel.startswith("#"):
                _add(rel, project_root / rel)

    # 4. Web backend files (Phase 2+ once app.py / scripts exist)
    if app_py.is_file():
        _add("app.py", app_py)
        backend_dir = project_root / "backend"
        if backend_dir.is_dir():
            for src in sorted(backend_dir.rglob("*.py")):
                rel = src.relative_to(project_root).as_posix()
                _add(rel, src)
            prompts_dir = backend_dir / "prompts"
            if prompts_dir.is_dir():
                for src in sorted(prompts_dir.rglob("*.txt")):
                    rel = src.relative_to(project_root).as_posix()
                    _add(rel, src)
        for rel in PHASE2_PLUS_SCRIPTS:
            _add(rel, project_root / rel)
        demo_uploads_dir = project_root / "uploads_private" / "A001"
        if demo_uploads_dir.is_dir():
            for src in sorted(demo_uploads_dir.iterdir()):
                if src.is_file():
                    rel = src.relative_to(project_root).as_posix()
                    if _is_seeded_demo_media(rel):
                        _add(rel, src)

    sorted_items = [(src, rel, size) for rel, (src, size) in sorted(entries.items(), key=lambda kv: kv[0])]
    return sorted_items, warnings


def export_release(
    project_root: Path,
    release_root: Path,
    dry_run: bool = False,
    clean_stale: bool = False,
) -> int:
    items, warnings = collect_whitelist(project_root)
    if not items:
        print("[ERROR] Whitelist resolved 0 files.", file=sys.stderr)
        return 1

    expected_rels = {rel for _, rel, _ in items}
    stale_files: list[str] = []
    if release_root.is_dir():
        for existing in sorted(release_root.rglob("*")):
            if existing.is_file() and ".git" not in existing.relative_to(release_root).parts:
                rel = existing.relative_to(release_root).as_posix()
                if rel not in expected_rels:
                    stale_files.append(rel)

    if not dry_run:
        if not (release_root / ".git").exists():
            print(f"[ERROR] {release_root} is not a git repository.", file=sys.stderr)
            return 1
        for src, rel, _size in items:
            dst = release_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if clean_stale:
            for rel in stale_files:
                target = release_root / rel
                if target.is_file():
                    target.unlink()
            # Prune empty directories cleanly (excluding .git)
            for d in sorted((p for p in release_root.rglob("*") if p.is_dir() and ".git" not in p.parts), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass

    total_bytes = sum(size for _, _, size in items)
    mode = "DRY-RUN" if dry_run else ("EXPORT+CLEAN" if clean_stale else "EXPORT")
    print(f"[{mode}] Project: {project_root}")
    print(f"[{mode}] Target : {release_root}")
    print(f"[{mode}] Files  : {len(items)} ({total_bytes:,} bytes / {total_bytes / (1024 * 1024):.2f} MiB)")
    print("-" * 72)
    for _src, rel, size in items:
        print(f"{size:10d}  {rel}")
    if stale_files:
        print("-" * 72)
        action = "Removed stale files" if (not dry_run and clean_stale) else "Existing non-whitelisted files in release target"
        print(f"[{mode}] {action} ({len(stale_files)}):")
        for rel in stale_files:
            print(f"            {rel}")
    if warnings:
        print("-" * 72)
        for w in warnings:
            print(f"[WARN] {w}")
    return 0


def main() -> None:
    default_project = Path(__file__).resolve().parent.parent
    default_release = default_project.parent / "vitalverse_release"
    parser = argparse.ArgumentParser(description="Export Vitalverse runtime whitelist to release repo.")
    parser.add_argument("--project", type=Path, default=default_project)
    parser.add_argument("--target", type=Path, default=default_release)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean", action="store_true", help="Remove files in target not in current whitelist")
    args = parser.parse_args()
    sys.exit(export_release(args.project.resolve(), args.target.resolve(), dry_run=args.dry_run, clean_stale=args.clean))


if __name__ == "__main__":
    main()
