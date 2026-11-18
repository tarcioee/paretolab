"""Pipeline runner: state, pause/resume, parallel runs, per-run time limit."""
from paretolab.execution.runner import EXIT_DISK, EXIT_ERROR, EXIT_OK, EXIT_SETUP, Runner, RunSpec

__all__ = ["EXIT_DISK", "EXIT_ERROR", "EXIT_OK", "EXIT_SETUP", "RunSpec", "Runner"]
