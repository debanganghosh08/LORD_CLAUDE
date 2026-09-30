"""Packaging LORD as an Antigravity plugin: validate, install, uninstall, roll back.

Source (tracked, in the LORD repository):
    plugin/                 plugin.json, hooks.json, lord_hook.py, lord_cli.py,
                            rules/, skills/, agents/, README.md
    lord/                   the runtime (one copy of the logic)

Installed bundle (`<plugins dir>/lord/`, built from the source):
    plugin.json  hooks.json  lord_hook.py  lord_cli.py  README.md  LICENSE
    rules/  skills/  agents/
    runtime/lord/...        the runtime, copied at install time
    install.json            version, source commit, file hashes, CLI registration
    .rollback.zip           the previous installed version (after an update)

The installed `hooks.json` is the source file unchanged: `python -m lord_hook
<event>`, no quotes, no absolute path. Antigravity runs a hook with the folder
holding hooks.json as its working directory (shipped docs; observed for plugin
hooks in Phase 6 and workspace hooks in Phase 8A), which is where the launcher
is; the launcher then finds `runtime/` from its own file. An absolute path was
rejected: the IDE substitutes no plugin-root placeholder, and on Windows
Antigravity keeps literal quotes (observed in Phase 6: Google's own quoted
telemetry hook fails with MODULE_NOT_FOUND), so a quoted path breaks and an
unquoted one breaks on any path with a space. Nothing in the bundle is
machine-specific except install.json.

Installation never touches anything but the target plugin directory and,
when asked, one `lord-harness.pth` file in the Python user site that makes
`python -m lord` import the installed runtime. It refuses to overwrite a
directory it did not install. No model API, no key, no network.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import site
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from lord import __version__
from lord.paths import PLUGIN_MANIFEST, PLUGIN_NAME, global_plugins_dir, runtime_home
from lord.report import CONFIRMED, ERROR, INFO, OK, WARN, Finding, Report

INSTALL_RECORD = "install.json"
ROLLBACK_ARCHIVE = ".rollback.zip"
CLI_PTH = "lord-harness.pth"
SOURCE_HOOK_PREFIX = "python -m lord_hook "
MANIFEST_KEYS = frozenset({"$schema", "name", "description"})  # the documented schema (additionalProperties: false)
NAME_RE = re.compile(r"^[a-zA-Z0-9-_]+$")
RULE_TRIGGERS = frozenset({"always_on", "model_decision", "glob", "manual"})
RULE_MAX_CHARS = 12000
SKIP_PARTS = frozenset({"__pycache__", ".pytest_cache"})
# Development-only runtime modules: the acceptance tooling knows the scenario
# prompts and their expected answers, so it never ships (an evaluated agent
# could otherwise read the answers from the installed plugin).
DEV_ONLY_MODULES = frozenset({"acceptance.py"})
SECRET_NAME_RE = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.pfx$|^id_(rsa|ed25519)|^credentials\.json$|^oauth_creds\.json$|^tokens?\.json$|\.token$)", re.I)
SECRET_TEXT_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAIza[0-9A-Za-z_-]{30,}|\bsk-[A-Za-z0-9]{20,}|\bghp_[A-Za-z0-9]{30,}")


# --- source ---------------------------------------------------------------------------

def source_dirs() -> tuple[Path, Path]:
    """(plugin source, runtime package) of the development checkout this runs from."""
    home = runtime_home()
    return home / "plugin", home / "lord"


def _files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file() and not SKIP_PARTS & set(p.relative_to(base).parts) and p.suffix != ".pyc")


def bundle_map(plugin_src: Path, runtime_src: Path) -> dict[str, Path]:
    """Installed relative path -> source file."""
    out = {p.relative_to(plugin_src).as_posix(): p for p in _files(plugin_src)}
    out.update({"runtime/lord/" + p.relative_to(runtime_src).as_posix(): p for p in _files(runtime_src)
                if p.suffix == ".py" and p.relative_to(runtime_src).as_posix() not in DEV_ONLY_MODULES})
    license_file = runtime_src.parent / "LICENSE"
    if license_file.is_file():
        out["LICENSE"] = license_file
    return out


def _stdlib_violations(runtime_src: Path) -> list[str]:
    """Runtime modules importing anything outside the standard library."""
    import ast

    allowed = set(sys.stdlib_module_names) | {"lord", "__future__"}
    bad = []
    for path in _files(runtime_src):
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for name in names:
                if name.split(".")[0] not in allowed:
                    bad.append(f"{path.relative_to(runtime_src.parent).as_posix()}: imports {name}")
    return bad


def validate_source(plugin_src: Path, runtime_src: Path, forbidden_paths: tuple[str, ...] = ()) -> list[str]:
    """Problems that make the source unfit to package. Empty = valid."""
    from lord.context import frontmatter
    from lord.doctor import validate_hooks_config

    errors: list[str] = []
    manifest = plugin_src / PLUGIN_MANIFEST
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{PLUGIN_MANIFEST}: unreadable ({exc})"]
    if not isinstance(data, dict):
        return [f"{PLUGIN_MANIFEST}: must be an object"]
    extra = set(data) - MANIFEST_KEYS
    if extra:
        errors.append(f"{PLUGIN_MANIFEST}: undocumented field(s) {sorted(extra)}")
    if not NAME_RE.match(str(data.get("name", ""))):
        errors.append(f"{PLUGIN_MANIFEST}: name must match {NAME_RE.pattern}")
    if not str(data.get("description", "")).strip():
        errors.append(f"{PLUGIN_MANIFEST}: description is empty")

    try:
        hooks = json.loads((plugin_src / "hooks.json").read_text(encoding="utf-8"))
        errors += [f"hooks.json: {e}" for e in validate_hooks_config(hooks)]
        for name, cfg in (hooks.items() if isinstance(hooks, dict) else []):
            for event, entries in cfg.items():
                if event == "enabled":
                    continue
                for entry in entries:
                    for handler in entry.get("hooks", [entry]):
                        if not str(handler.get("command", "")).startswith(SOURCE_HOOK_PREFIX):
                            errors.append(f"hooks.json: {name}.{event} must run the launcher (`{SOURCE_HOOK_PREFIX}<event>`)")
    except (OSError, ValueError) as exc:
        errors.append(f"hooks.json: unreadable ({exc})")
    if not (plugin_src / "lord_hook.py").is_file():
        errors.append("lord_hook.py (the launcher) is missing")

    for rule in sorted((plugin_src / "rules").glob("*.md")):
        text = rule.read_text(encoding="utf-8")
        if frontmatter(text).get("trigger") not in RULE_TRIGGERS:
            errors.append(f"rules/{rule.name}: trigger must be one of {sorted(RULE_TRIGGERS)}")
        if len(text) > RULE_MAX_CHARS:
            errors.append(f"rules/{rule.name}: longer than {RULE_MAX_CHARS} characters")
    for skill in sorted((plugin_src / "skills").glob("*/SKILL.md")):
        fm = frontmatter(skill.read_text(encoding="utf-8"))
        if not fm.get("description"):
            errors.append(f"skills/{skill.parent.name}: description is required")
        if fm.get("name") and fm["name"] != skill.parent.name:
            errors.append(f"skills/{skill.parent.name}: name {fm['name']!r} differs from its folder")
    for agent in sorted((plugin_src / "agents").glob("*.md")):
        fm = frontmatter(agent.read_text(encoding="utf-8"))
        if not fm.get("name") or not fm.get("description"):
            errors.append(f"agents/{agent.name}: name and description are required")

    for rel, path in bundle_map(plugin_src, runtime_src).items():
        if SECRET_NAME_RE.search(path.name):
            errors.append(f"{rel}: secret-like file name")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if SECRET_TEXT_RE.search(text):
            errors.append(f"{rel}: secret-like content")
        for forbidden in forbidden_paths:
            if forbidden and forbidden.lower() in text.lower():
                errors.append(f"{rel}: contains the machine path {forbidden!r}")
    errors += _stdlib_violations(runtime_src)
    return errors


# --- targets ----------------------------------------------------------------------------

def resolve_plugins_dir(dest: Path | None = None, workspace: Path | None = None, use_global: bool = False) -> Path:
    if (dest is not None) + (workspace is not None) + bool(use_global) != 1:
        raise ValueError("give exactly one of --dest <plugins dir>, --workspace <dir> or --global")
    if use_global:
        found = global_plugins_dir()
        if found is None:
            raise ValueError("no home directory")
        return found
    if workspace is not None:
        return workspace.resolve() / ".agents" / "plugins"
    assert dest is not None
    return dest.resolve()


def _anchor(plugins_dir: Path) -> Path:
    """What must already exist before LORD creates `plugins_dir`: Antigravity's
    config folder for the global location, the workspace for `.agents/plugins`,
    otherwise the parent of the given directory."""
    if plugins_dir.parent.name == "config" and plugins_dir.parent.parent.name == ".gemini":
        return plugins_dir.parent
    if plugins_dir.name == "plugins" and plugins_dir.parent.name == ".agents":
        return plugins_dir.parent.parent
    return plugins_dir.parent


def _read_record(target: Path) -> dict | None:
    try:
        data = json.loads((target / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("name") == PLUGIN_NAME else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_commit(repo: Path) -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "plugin", "lord"], cwd=repo, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"
    return (head or "unknown") + ("+dirty" if dirty else "")


def build_contents(plugin_src: Path, runtime_src: Path) -> dict[str, bytes]:
    """Every installed file's bytes (install.json excluded)."""
    return {rel: path.read_bytes() for rel, path in bundle_map(plugin_src, runtime_src).items()}


def _installed_hashes(target: Path) -> dict[str, str]:
    return {p.relative_to(target).as_posix(): _sha(p.read_bytes()) for p in _files(target)
            if p.name not in (INSTALL_RECORD, ROLLBACK_ARCHIVE)}


def _zip_dir(target: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in _files(target):
            if p.name != ROLLBACK_ARCHIVE:
                archive.write(p, p.relative_to(target).as_posix())
    return buffer.getvalue()


def _clear_dir(target: Path) -> None:
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _write_tree(target: Path, contents: dict[str, bytes]) -> None:
    for rel, data in contents.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


# --- CLI registration (`python -m lord` imports the installed runtime) ----------------------

def user_site() -> Path | None:
    if not site.ENABLE_USER_SITE:
        return None
    try:
        return Path(site.getusersitepackages())
    except (AttributeError, OSError):
        return None


def register_cli(runtime: Path, site_dir: Path | None) -> str:
    if site_dir is None:
        return "not registered: this interpreter has no user site (virtual environment?); use `python <plugin>/lord_cli.py`"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / CLI_PTH).write_text(str(runtime) + "\n", encoding="utf-8")
    return f"registered {site_dir / CLI_PTH} -> {runtime}"


def cli_resolution(cwd: Path) -> str:
    """Where `python -m lord` resolves from a neutral directory, as the agent's terminal would."""
    try:
        completed = subprocess.run([sys.executable, "-c", "import lord, os; print(os.path.dirname(os.path.dirname(os.path.abspath(lord.__file__))))"],
                                   cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unknown ({exc})"
    return completed.stdout.strip() if completed.returncode == 0 else "not importable"


# --- operations ---------------------------------------------------------------------------

def install(plugins_dir: Path, dry_run: bool = False, cli: bool = True, site_dir: Path | None = None, source: tuple[Path, Path] | None = None) -> Report:
    plugin_src, runtime_src = source or source_dirs()
    target = plugins_dir / PLUGIN_NAME
    report = Report(title="LORD plugin install" + (" (dry run)" if dry_run else ""), meta={"target": str(target), "version": __version__, "dry_run": dry_run})
    errors = validate_source(plugin_src, runtime_src, forbidden_paths=(str(runtime_src.parent), runtime_src.parent.as_posix()))
    if errors:
        report.add(Finding(kind="source", summary=f"plugin source invalid: {len(errors)} problem(s)", severity=ERROR, confidence=CONFIRMED, evidence=errors[:20]))
        return report
    report.add(Finding(kind="source", summary="plugin source valid (manifest, hooks, rules, skills, agents, no machine paths, no secrets, stdlib-only runtime)", severity=OK, confidence=CONFIRMED))
    anchor = _anchor(plugins_dir)
    if not anchor.is_dir():
        report.add(Finding(kind="target", summary=f"{anchor} does not exist; refusing to create it", severity=ERROR, confidence=CONFIRMED,
                           recommendation="for --global, start Antigravity once so ~/.gemini/config exists; otherwise pass an existing directory"))
        return report
    record = _read_record(target) if target.exists() else None
    if target.exists() and record is None and any(target.iterdir()):
        report.add(Finding(kind="target", summary=f"{target} exists and was not installed by LORD; refusing to overwrite it", severity=ERROR, confidence=CONFIRMED,
                           recommendation="move it away yourself, or choose another --dest"))
        return report

    contents = build_contents(plugin_src, runtime_src)
    new_hashes = {rel: _sha(data) for rel, data in contents.items()}
    old_hashes = _installed_hashes(target) if target.exists() else {}
    added = sorted(set(new_hashes) - set(old_hashes))
    removed = sorted(set(old_hashes) - set(new_hashes))
    changed = sorted(r for r in set(new_hashes) & set(old_hashes) if new_hashes[r] != old_hashes[r])
    report.meta.update({"added": added, "changed": changed, "removed": removed})
    runtime = target / "runtime"
    pth = (site_dir if site_dir is not None else user_site())
    pth_ok = not cli or (pth is not None and (pth / CLI_PTH).is_file() and (pth / CLI_PTH).read_text(encoding="utf-8").strip() == str(runtime))
    if not (added or changed or removed) and record is not None and pth_ok:
        report.add(Finding(kind="install", summary=f"already installed and identical (version {record.get('version')}); nothing changed", severity=OK, confidence=CONFIRMED))
        return report
    summary = f"{'would install' if dry_run else 'installed'} LORD {__version__} at {target}: +{len(added)} ~{len(changed)} -{len(removed)} file(s)"
    if dry_run:
        report.add(Finding(kind="install", summary=summary, severity=INFO, confidence=CONFIRMED, evidence=[f"+ {r}" for r in added[:15]] + [f"~ {r}" for r in changed[:15]] + [f"- {r}" for r in removed[:15]]))
        report.add(Finding(kind="cli", summary=f"would register `python -m lord` via {(pth / CLI_PTH) if pth else '(no user site)'}" if cli else "CLI registration skipped (--no-cli)", severity=INFO, confidence=CONFIRMED))
        return report

    previous = _zip_dir(target) if target.exists() and record is not None else None
    target.mkdir(parents=True, exist_ok=True)
    try:
        _clear_dir(target)
        _write_tree(target, contents)
        if previous is not None:
            (target / ROLLBACK_ARCHIVE).write_bytes(previous)
        cli_note = register_cli(runtime, pth) if cli else "CLI registration skipped (--no-cli)"
        install_record = {"name": PLUGIN_NAME, "version": __version__, "source_commit": _source_commit(runtime_src.parent), "installed": date.today().isoformat(),
                          "hooks_command": SOURCE_HOOK_PREFIX + "<event> (run from the plugin folder)", "cli_pth": str(pth / CLI_PTH) if (cli and pth is not None) else "",
                          "files": new_hashes}
        (target / INSTALL_RECORD).write_text(json.dumps(install_record, indent=1) + "\n", encoding="utf-8")
    except OSError as exc:
        if previous is not None:
            _clear_dir(target)
            with zipfile.ZipFile(io.BytesIO(previous)) as archive:
                archive.extractall(target)
        report.add(Finding(kind="install", summary=f"install failed and was rolled back: {exc}", severity=ERROR, confidence=CONFIRMED))
        return report
    report.add(Finding(kind="install", summary=summary, severity=OK, confidence=CONFIRMED, evidence=[f"+ {r}" for r in added[:10]] + [f"~ {r}" for r in changed[:10]] + [f"- {r}" for r in removed[:10]],
                       recommendation="enable it in the Antigravity side panel (Customizations) if it is not enabled; open a trusted workspace"))
    report.add(Finding(kind="cli", summary=cli_note, severity=OK if cli and pth is not None else WARN, confidence=CONFIRMED))
    if previous is not None:
        report.add(Finding(kind="rollback", summary=f"previous version kept in {ROLLBACK_ARCHIVE}; `lord plugin rollback` restores it", severity=INFO, confidence=CONFIRMED))
    return report


def uninstall(plugins_dir: Path, site_dir: Path | None = None) -> Report:
    target = plugins_dir / PLUGIN_NAME
    report = Report(title="LORD plugin uninstall", meta={"target": str(target)})
    record = _read_record(target)
    if record is None:
        report.add(Finding(kind="uninstall", summary=f"no LORD install at {target}; nothing removed", severity=INFO if not target.exists() else WARN, confidence=CONFIRMED))
        return report
    pth = site_dir if site_dir is not None else user_site()
    removed_pth = ""
    if pth is not None and (pth / CLI_PTH).is_file() and (pth / CLI_PTH).read_text(encoding="utf-8").strip() == str(target / "runtime"):
        (pth / CLI_PTH).unlink()
        removed_pth = str(pth / CLI_PTH)
    shutil.rmtree(target)
    report.add(Finding(kind="uninstall", summary=f"removed {target} (version {record.get('version')})", severity=OK, confidence=CONFIRMED,
                       evidence=[f"removed CLI registration {removed_pth}"] if removed_pth else []))
    return report


def rollback(plugins_dir: Path) -> Report:
    """Swap the installed version with the one kept in the rollback archive."""
    target = plugins_dir / PLUGIN_NAME
    report = Report(title="LORD plugin rollback", meta={"target": str(target)})
    archive_path = target / ROLLBACK_ARCHIVE
    if _read_record(target) is None or not archive_path.is_file():
        report.add(Finding(kind="rollback", summary="nothing to roll back to (no LORD install or no previous version)", severity=WARN, confidence=CONFIRMED))
        return report
    previous = archive_path.read_bytes()
    current = _zip_dir(target)
    _clear_dir(target)
    with zipfile.ZipFile(io.BytesIO(previous)) as archive:
        archive.extractall(target)
    (target / ROLLBACK_ARCHIVE).write_bytes(current)
    record = _read_record(target) or {}
    report.add(Finding(kind="rollback", summary=f"restored version {record.get('version')} ({record.get('source_commit')}); the replaced version is now the rollback archive", severity=OK, confidence=CONFIRMED))
    return report


def status(plugins_dir: Path, site_dir: Path | None = None) -> Report:
    target = plugins_dir / PLUGIN_NAME
    report = Report(title="LORD plugin status", meta={"target": str(target)})
    record = _read_record(target)
    if record is None:
        report.add(Finding(kind="installed", summary=f"not installed at {target}", severity=INFO, confidence=CONFIRMED))
        return report
    expected = record.get("files", {})
    actual = _installed_hashes(target)
    drift = sorted(r for r in set(expected) | set(actual) if expected.get(r) != actual.get(r))
    report.meta.update({"version": record.get("version"), "source_commit": record.get("source_commit"), "drift": drift})
    report.add(Finding(kind="installed", summary=f"LORD {record.get('version')} ({record.get('source_commit')}, installed {record.get('installed')})", severity=OK, confidence=CONFIRMED))
    report.add(Finding(kind="integrity", summary="installed files match the install record" if not drift else f"{len(drift)} file(s) differ from the install record",
                       severity=OK if not drift else WARN, confidence=CONFIRMED, evidence=drift[:15]))
    pth = site_dir if site_dir is not None else user_site()
    registered = pth is not None and (pth / CLI_PTH).is_file() and (pth / CLI_PTH).read_text(encoding="utf-8").strip() == str(target / "runtime")
    with tempfile.TemporaryDirectory() as neutral:
        resolves = cli_resolution(Path(neutral))
    report.add(Finding(kind="cli", summary=f"`python -m lord` resolves to {resolves}" + ("" if registered else " (this install is not registered)"),
                       severity=OK if registered and resolves == str(target / "runtime") else WARN, confidence=CONFIRMED,
                       recommendation="" if registered else f"`python -m lord plugin install ...` registers it; or run `python \"{target / 'lord_cli.py'}\" <command>`"))
    return report
