"""A small NSGA-II and a random search on ZDT1 (30 variables, both objectives minimized): the multi-objective
example of paretolab, in Python.

usage: moea.py <variant> <seed> <max evaluations> <result file> [--name=value ...]

variants: nsga2 or random; parameters (nsga2 only): --pop_size, --crossover_prob, --mutation_eta.
The true Pareto front of ZDT1 is f2 = 1 - sqrt(f1), f1 in [0, 1].
"""
import json
import sys
import time

import numpy as np

N_VARIABLES = 30


def zdt1(x: np.ndarray) -> np.ndarray:
    f1 = x[:, 0]
    g = 1.0 + 9.0 * x[:, 1:].sum(axis=1) / (x.shape[1] - 1)
    return np.column_stack([f1, g * (1.0 - np.sqrt(f1 / g))])


def nondominated(f: np.ndarray) -> np.ndarray:
    """Mask of the points of ``f`` not dominated by any other (minimization)."""
    le = (f[:, None, :] <= f[None, :, :]).all(axis=2)
    lt = (f[:, None, :] < f[None, :, :]).any(axis=2)
    return ~(le & lt).any(axis=0)


def fronts(f: np.ndarray) -> list:
    left = np.arange(len(f))
    out = []
    while len(left):
        mask = nondominated(f[left])
        out.append(left[mask])
        left = left[~mask]
    return out


def crowding(f: np.ndarray) -> np.ndarray:
    distance = np.zeros(len(f))
    for m in range(f.shape[1]):
        order = np.argsort(f[:, m])
        span = f[order[-1], m] - f[order[0], m] or 1.0
        distance[order[[0, -1]]] = np.inf
        distance[order[1:-1]] += (f[order[2:], m] - f[order[:-2], m]) / span
    return distance


def select(f: np.ndarray, size: int) -> np.ndarray:
    chosen = []
    for front in fronts(f):
        if len(chosen) + len(front) <= size:
            chosen += list(front)
        else:
            order = np.argsort(-crowding(f[front]))
            chosen += list(front[order[:size - len(chosen)]])
            break
    return np.array(chosen)


def sbx(a, b, rng, eta=15.0):
    u = rng.random(a.shape)
    beta = np.where(u <= 0.5, (2 * u) ** (1 / (eta + 1)), (1 / (2 * (1 - u))) ** (1 / (eta + 1)))
    child = 0.5 * ((1 + beta) * a + (1 - beta) * b)
    return np.clip(child, 0.0, 1.0)


def mutate(x, rng, eta):
    u = rng.random(x.shape)
    delta = np.where(u < 0.5, (2 * u) ** (1 / (eta + 1)) - 1, 1 - (2 * (1 - u)) ** (1 / (eta + 1)))
    mask = rng.random(x.shape) < 1.0 / x.shape[1]
    return np.clip(x + mask * delta, 0.0, 1.0)


def main(argv) -> None:
    variant, seed, budget, result_file, *options = argv
    params = dict(o[2:].split("=", 1) for o in options)
    rng = np.random.default_rng(int(seed))
    budget = int(budget)
    started = time.perf_counter()

    if variant == "random":
        x = rng.random((budget, N_VARIABLES))
        f = zdt1(x)
        f = f[np.lexsort((f[:, 1], f[:, 0]))]                       # by f1, then f2: one sweep keeps the front
        keep = f[:, 1] < np.minimum.accumulate(np.concatenate([[np.inf], f[:-1, 1]]))
        front, evaluations = f[keep], budget
    else:
        size = int(params.get("pop_size", 50))
        p_cross = float(params.get("crossover_prob", 0.9))
        eta = float(params.get("mutation_eta", 20))
        x = rng.random((size, N_VARIABLES))
        f = zdt1(x)
        evaluations = size
        while evaluations + size <= budget:
            rank = np.empty(size)
            for level, front in enumerate(fronts(f)):
                rank[front] = level
            pairs = rng.integers(0, size, (size, 2))
            parents = np.where(rank[pairs[:, 0]] <= rank[pairs[:, 1]], pairs[:, 0], pairs[:, 1])
            mates = rng.permutation(parents)
            children = np.where(rng.random((size, 1)) < p_cross, sbx(x[parents], x[mates], rng), x[parents])
            children = mutate(children, rng, eta)
            all_x, all_f = np.vstack([x, children]), np.vstack([f, zdt1(children)])
            evaluations += size
            keep = select(all_f, size)
            x, f = all_x[keep], all_f[keep]
        front = f[nondominated(f)]

    with open(result_file, "w", encoding="utf-8") as out:
        json.dump({"front": np.unique(front, axis=0).tolist(), "evaluations": int(evaluations),
                   "wall_time_s": round(time.perf_counter() - started, 4)}, out)


if __name__ == "__main__":
    main(sys.argv[1:])
