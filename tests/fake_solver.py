"""A stand-in for a user's program; its behaviour depends on the instance name.

usage: fake_solver.py <instance> <seed> <result_file> [--name=value ...]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

instance, seed, result_file, *params = sys.argv[1:]
seed = int(seed)


def write(front):
    Path(result_file).write_text(json.dumps({"front": front, "evaluations": 10, "metadata": {"params": params}}))


if instance == "ok":
    write([[float(seed), 10.0 - seed], [seed / 2, 10.0 - seed / 2 + 1]])
elif instance == "sleepy":
    time.sleep(0.5)
    write([[float(seed), 1.0]])
elif instance == "crash":
    print("something went wrong", flush=True)
    sys.exit(3)
elif instance == "bad":
    write([[1.0]])                      # one value per point, but the project has two objectives
elif instance == "slow":
    time.sleep(60)
elif instance == "spawner":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(result_file).with_name("child.pid").write_text(str(child.pid))
    time.sleep(60)
