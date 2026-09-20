"""LORD hook launcher for Antigravity (`python -m lord_hook <event>`).

Antigravity runs workspace hooks with `.agents/` as the working directory
(confirmed live in Phase 8A from the hook log's cwd field), so this launcher
lives in `.agents/` and is found by `python -m lord_hook` from there. It
locates the LORD package from its own location, never from the cwd, and it
must never fail: any error prints the event's permissive default and exits 0
(a failing PreToolUse hook denies the tool call).
"""

import json
import os
import sys

_DEFAULTS = {"pre-tool": {"decision": "allow"}}


def _run() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    home = None
    for candidate in (here, os.path.dirname(here)):
        if os.path.isdir(os.path.join(candidate, "lord")):
            home = candidate
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            break
    from pathlib import Path  # noqa: PLC0415

    from lord.hooks import main  # noqa: PLC0415

    # The workspace comes from the payload's workspacePaths; the repository
    # this launcher lives in is only the fallback when that is unusable.
    return main(root=Path(home) if home else None)


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
