"""Reads the TSPLIB instances of this example (EUC_2D, GEO, EXPLICIT LOWER_DIAG_ROW / FULL_MATRIX) into a
distance matrix, with TSPLIB's own rounding rules, so tour lengths match the published optima."""
import math


def read(path) -> list[list[int]]:
    spec, coords, weights, section = {}, [], [], None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line == "EOF":
                continue
            if line in ("NODE_COORD_SECTION", "EDGE_WEIGHT_SECTION", "DISPLAY_DATA_SECTION"):
                section = line
                continue
            if ":" in line and section is None:
                key, value = line.split(":", 1)
                spec[key.strip()] = value.strip()
                continue
            if section == "NODE_COORD_SECTION":
                _, x, y = line.split()[:3]
                coords.append((float(x), float(y)))
            elif section == "EDGE_WEIGHT_SECTION":
                weights += [int(float(v)) for v in line.split()]
    n = int(spec["DIMENSION"])
    kind = spec["EDGE_WEIGHT_TYPE"]
    if kind == "EUC_2D":
        return [[round(math.dist(a, b)) for b in coords] for a in coords]
    if kind == "GEO":
        return _geo(coords)
    if kind == "EXPLICIT":
        layout = spec.get("EDGE_WEIGHT_FORMAT")
        d = [[0] * n for _ in range(n)]
        if layout == "FULL_MATRIX":
            return [weights[i * n:(i + 1) * n] for i in range(n)]
        if layout == "LOWER_DIAG_ROW":
            k = 0
            for i in range(n):
                for j in range(i + 1):
                    d[i][j] = d[j][i] = weights[k]
                    k += 1
            return d
        raise ValueError(f"unsupported EDGE_WEIGHT_FORMAT {layout}")
    raise ValueError(f"unsupported EDGE_WEIGHT_TYPE {kind}")


def _geo(coords) -> list[list[int]]:
    def radians(x):
        degrees = int(x)
        return math.pi * (degrees + 5.0 * (x - degrees) / 3.0) / 180.0

    lat = [radians(x) for x, _ in coords]
    lon = [radians(y) for _, y in coords]
    n = len(coords)
    d = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                q1 = math.cos(lon[i] - lon[j])
                q2 = math.cos(lat[i] - lat[j])
                q3 = math.cos(lat[i] + lat[j])
                d[i][j] = int(6378.388 * math.acos(0.5 * ((1.0 + q1) * q2 - (1.0 - q1) * q3)) + 1.0)
    return d


def length(tour, d) -> int:
    return sum(d[tour[i - 1]][tour[i]] for i in range(len(tour)))


def held_karp(d) -> int:
    """Exact optimum by dynamic programming over subsets (fine up to ~18 cities); used to check the data."""
    n = len(d)
    full = 1 << (n - 1)
    inf = float("inf")
    best = [[inf] * (n - 1) for _ in range(full)]
    for j in range(n - 1):
        best[1 << j][j] = d[0][j + 1]
    for subset in range(1, full):
        row = best[subset]
        for j in range(n - 1):
            value = row[j]
            if value == inf or not subset >> j & 1:
                continue
            for k in range(n - 1):
                if not subset >> k & 1:
                    nxt = subset | 1 << k
                    candidate = value + d[j + 1][k + 1]
                    if candidate < best[nxt][k]:
                        best[nxt][k] = candidate
    return min(best[full - 1][j] + d[j + 1][0] for j in range(n - 1))
