"""Where things live inside an experiment's output_dir."""
from pathlib import Path

RUNS = "runs"
ANALYSIS = "analysis"
RESULT_FILE = "result.json"


def run_dir(runs_root, instance: str, algorithm: str, variant: str, seed: int) -> Path:
    return Path(runs_root) / instance / algorithm / variant / f"seed_{seed}"


def result_files(runs_root) -> list[Path]:
    """Every stored run result under ``runs_root``, in a stable order."""
    return sorted(Path(runs_root).glob(f"*/*/*/seed_*/{RESULT_FILE}"))
