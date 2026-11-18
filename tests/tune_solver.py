"""A program whose quality depends on its parameters, for the tuning tests; the best is x=0.7, k=3, op=b.

usage: tune_solver.py <multi|single> <seed> <result_file> [--name=value ...]
"""
import json
import random
import sys
from pathlib import Path

mode, seed, result_file, *params = sys.argv[1:]
values = dict(p[2:].split("=", 1) for p in params)
x, k, op = float(values.get("x", 0.1)), int(values.get("k", 1)), values.get("op", "a")
rng = random.Random(int(seed))
penalty = abs(x - 0.7) + 0.1 * abs(k - 3) + (0.0 if op == "b" else 0.2) + rng.uniform(0, 0.02)
if mode == "single":
    front = [[100.0 * (1 + penalty)]]
else:   # objectives: cost (min), power (max)
    front = [[t + penalty, 10.0 * (1 - t * t) - 5 * penalty] for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
Path(result_file).write_text(json.dumps({"front": front}))
