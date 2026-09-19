import subprocess
import pkg.runner as r


def execute(cmd):
    subprocess.run(cmd)
    return r.run(cmd)
