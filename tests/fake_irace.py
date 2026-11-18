"""A stand-in for ``Rscript run_irace.R`` (no R in CI): reads the files paretolab wrote, calls the target runner
the way irace does and prints irace's 'best configurations' block. Its log file is JSON, saved after every
evaluation; ``recoveryFile`` skips the evaluations it lists.

Environment: FAKE_IRACE_SLEEP (seconds between evaluations), FAKE_IRACE_CONFIGS (number of configurations).
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

scenario = dict(re.findall(r'^(\w+) = "?([^"\n]*)"?$', Path("scenario.txt").read_text(), re.M))
space = []
for line in Path("parameters.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    name, _, kind, domain = re.match(r'(\S+) "(\S+)" (\S+) \((.*)\)', line).groups()
    space.append((name, kind.split(",")[0], [v.strip().strip('"') for v in domain.split(",")]))
instances = Path("instances.txt").read_text().split()

rng = random.Random(int(scenario["seed"]))
configs = []
if "configurationsFile" in scenario:
    names, values = (line.split() for line in Path(scenario["configurationsFile"]).read_text().splitlines()[:2])
    configs.append(dict(zip(names, values, strict=True)))
for _ in range(int(os.environ.get("FAKE_IRACE_CONFIGS", "6"))):
    config = {}
    for name, kind, domain in space:
        if kind == "r":
            config[name] = f"{rng.uniform(float(domain[0]), float(domain[1])):.4f}"
        elif kind == "i":
            config[name] = str(rng.randint(int(domain[0]), int(domain[1])))
        else:
            config[name] = rng.choice(domain)
    configs.append(config)

done = {}
if "recoveryFile" in scenario:
    print(f"# Recovering from file: '{scenario['recoveryFile']}'", flush=True)
    done = json.loads(Path(scenario["recoveryFile"]).read_text())
for cid, config in enumerate(configs, start=1):
    for iid, instance in enumerate(instances, start=1):
        key = f"{cid}/{iid}"
        if key in done:
            continue
        args = [scenario["targetRunner"], str(cid), str(iid), str(1000 + iid), instance]
        args += [f"--{n}={v}" for n, v in config.items()]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Error: target runner failed: {r.stderr}", flush=True)
            sys.exit(1)
        done[key] = float(r.stdout.strip())
        Path(scenario["logFile"]).write_text(json.dumps(done))
        print(f"evaluated {key}: {done[key]}", flush=True)
        time.sleep(float(os.environ.get("FAKE_IRACE_SLEEP", "0")))

means = {cid: sum(done[f"{cid}/{i}"] for i in range(1, len(instances) + 1)) for cid in range(1, len(configs) + 1)}
best = min(means, key=means.get)
print("# Best configurations as commandlines (first number is the configuration ID; same order as above):")
print(f"{best}  " + " ".join(f"--{n}={v}" for n, v in configs[best - 1].items()))
