"""LORD hook launcher for Antigravity: the one launcher every hook command runs.

`hooks.json` invokes it as `python -m lord_hook <event>`: no quotes (Antigravity
keeps literal quotes on Windows) and no absolute path (the IDE has no
plugin-root placeholder). Antigravity runs a hook with the folder holding
hooks.json as its working directory, which is where this file is; that is the
only thing the command relies on.

The runtime is located from this file, never from the working directory and
never by an absolute path: `<plugin>/runtime/lord` in an installed bundle, or
`<repo>/lord` next to `<repo>/plugin/` in a development checkout. The
workspace comes from the payload's `workspacePaths`.

It must never fail: any error prints the event's permissive default and exits
0 (a failing PreToolUse hook denies the tool call).
"""

import json
import os
import sys

_DEFAULTS = {"pre-tool": {"decision": "allow"}}


def runtime_dir(here):
    # no annotations or newer syntax in this file: it must import on any
    # Python 3 so that an old interpreter still gets the permissive default
    for candidate in (os.path.join(here, "runtime"), os.path.dirname(here)):
        if os.path.isfile(os.path.join(candidate, "lord", "__init__.py")):
            return candidate
    return None


def _run() -> int:
    runtime = runtime_dir(os.path.dirname(os.path.abspath(__file__)))
    if runtime is None:
        raise RuntimeError("LORD runtime not found next to the launcher")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    from lord.hooks import main  # noqa: PLC0415

    return main()


def _main() -> None:
    try:
        _run()
    except BaseException:  # noqa: BLE001 - never block the user's work
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        sys.stdout.write(json.dumps(_DEFAULTS.get(event, {})))
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    _main()
