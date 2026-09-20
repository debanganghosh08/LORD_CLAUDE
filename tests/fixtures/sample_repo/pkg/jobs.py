import subprocess
import pkg.runner as r
from pkg import runner


def execute(cmd):
    subprocess.run(cmd)
    runner.run(cmd)
    return r.run(cmd)
