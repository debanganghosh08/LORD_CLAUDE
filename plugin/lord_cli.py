"""Run the LORD command line from the plugin: `python "<plugin>/lord_cli.py" <command> ...`.

The fallback when `python -m lord` is not importable (the installer's CLI
registration was skipped, or the terminal uses another interpreter). It
locates the runtime exactly as the hook launcher does.
"""

import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lord_hook import runtime_dir  # noqa: E402

    runtime = runtime_dir(os.path.dirname(os.path.abspath(__file__)))
    if runtime is None:
        sys.stderr.write("LORD runtime not found next to lord_cli.py\n")
        sys.exit(2)
    sys.path.insert(0, runtime)
    from lord.cli import main  # noqa: E402

    sys.exit(main())
