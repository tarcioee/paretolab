import copy

import pytest

BIOBJECTIVE = {
    "name": "toy",
    "objectives": [{"name": "power", "sense": "max"}, {"name": "cost", "sense": "min"}],
    "instances": ["A", {"name": "B", "path": "data/B.txt"}],
    "algorithms": [
        {"name": "mosa", "variants": ["seq", "ext"],
         "parameters": [{"name": "t0", "type": "real", "range": [0.1, 10], "default": 1, "log": True},
                        {"name": "op", "type": "categorical", "values": ["swap", "insert"], "default": "swap"}]},
        {"name": "mots"},
    ],
    "executable": "./solver",
    "command": ["{executable}", "--inst", "{instance_path}", "--alg", "{algorithm}", "--var", "{variant}",
                "--seed", "{seed}", "--out", "{result_file}", "{params}"],
}

TSP = {
    "name": "tsp",
    "objectives": [{"name": "length", "sense": "min"}],
    "instances": [{"name": "burma14", "optimum": 3323}, {"name": "gr17", "optimum": 2085}],
    "algorithms": [{"name": "ils"}],
    "command": "python ils.py {instance} {seed} {result_file}",
}


@pytest.fixture
def biobjective():
    return copy.deepcopy(BIOBJECTIVE)


@pytest.fixture
def tsp():
    return copy.deepcopy(TSP)
