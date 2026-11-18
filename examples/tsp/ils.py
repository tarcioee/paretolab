"""Iterated local search for the TSP: the single-objective example of paretolab.

usage: ils.py <instance file> <variant> <seed> <max evaluations> <result file> [--name=value ...]

variants: two_opt (2-opt local search) or swap (exchange two cities); parameters: --strength (double-bridge kicks
per perturbation) and --accept (better: keep the best tour; always: continue from the new local optimum).
An evaluation is one move whose length change is computed.
"""
import json
import random
import sys
import time

import tsplib


def main(argv) -> None:
    path, variant, seed, budget, result_file, *options = argv
    params = dict(o[2:].split("=", 1) for o in options)
    strength, accept = int(params.get("strength", 1)), params.get("accept", "better")
    rng = random.Random(int(seed))
    d = tsplib.read(path)
    n = len(d)
    budget = int(budget)
    started = time.perf_counter()
    evaluations = 0
    trace = []

    def local_search(tour):
        nonlocal evaluations
        improved = True
        while improved and evaluations < budget:
            improved = False
            for i in range(n - 1):
                for j in range(i + 2 if variant == "two_opt" else i + 1, n):
                    if evaluations >= budget:
                        return tour
                    evaluations += 1
                    if variant == "two_opt":
                        a, b, c, e = tour[i], tour[i + 1], tour[j], tour[(j + 1) % n]
                        if a == e:
                            continue
                        delta = d[a][c] + d[b][e] - d[a][b] - d[c][e]
                        if delta < 0:
                            tour[i + 1:j + 1] = reversed(tour[i + 1:j + 1])
                            improved = True
                    else:
                        before = tsplib.length(tour, d)
                        tour[i], tour[j] = tour[j], tour[i]
                        if tsplib.length(tour, d) < before:
                            improved = True
                        else:
                            tour[i], tour[j] = tour[j], tour[i]
        return tour

    def double_bridge(tour):
        for _ in range(strength):
            a, b, c = sorted(rng.sample(range(1, n), 3))
            tour = tour[:a] + tour[c:] + tour[b:c] + tour[a:b]
        return tour

    current = list(range(n))
    rng.shuffle(current)
    current = local_search(current)
    best = list(current)
    trace.append({"evaluations": evaluations, "front": [[tsplib.length(best, d)]]})
    while evaluations < budget:
        candidate = local_search(double_bridge(list(current)))
        if tsplib.length(candidate, d) < tsplib.length(best, d):
            best = list(candidate)
            trace.append({"evaluations": evaluations, "front": [[tsplib.length(best, d)]]})
        if accept == "always" or tsplib.length(candidate, d) <= tsplib.length(current, d):
            current = candidate

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({"front": [[tsplib.length(best, d)]], "evaluations": evaluations,
                   "wall_time_s": round(time.perf_counter() - started, 4), "variables": [best],
                   "convergence_trace": trace}, f)


if __name__ == "__main__":
    main(sys.argv[1:])
