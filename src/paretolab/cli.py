"""Command-line interface."""
import json
import platform
from pathlib import Path

import typer

from paretolab import __version__

app = typer.Typer(help="paretolab: experiment manager for optimization algorithms.",
                  no_args_is_help=True, add_completion=False)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"paretolab {__version__}")
        raise typer.Exit()


@app.callback()
def main(version: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True,
                                      help="Show the version and exit.")) -> None:
    """paretolab: experiment manager for optimization algorithms."""


SCHEMAS = {"project": "Manifest", "setup": "Setup", "output": "RunOutput", "result": "RunResult"}


@app.command()
def validate(
    path: Path = typer.Argument(..., help="project.yaml, experiment.yaml or a result JSON file"),
    project: Path | None = typer.Option(None, "--project", help="manifest to check a result's objectives against"),
) -> None:
    """Validate a contract file. The kind is detected from its keys."""
    from paretolab import contract

    try:
        data = contract.io.read_data(path)
        keys = set(data) if isinstance(data, dict) else set()
        if "objectives" in keys and "command" in keys:
            manifest = contract.load_manifest(path)
            n_units = sum(len(a.variants) for a in manifest.algorithms)
            kind = "multi-objective" if manifest.is_multiobjective else "single-objective"
            typer.echo(f"OK: project '{manifest.name}' ({kind}: {', '.join(o.name for o in manifest.objectives)}), "
                       f"{len(manifest.instances)} instances, {len(manifest.algorithms)} algorithms, "
                       f"{n_units} algorithm variants")
        elif "output_dir" in keys:
            setup, manifest, plan = contract.load_experiment(path)
            typer.echo(f"OK: experiment on project '{manifest.name}': {len(plan.instances)} instances x "
                       f"{len(plan.units)} algorithm variants x {len(plan.seeds)} seeds = {plan.total_runs} runs; "
                       f"indicators: {', '.join(plan.indicators)}"
                       + ("; tuning with " + setup.tuning.tuner if setup.tuning.enabled else ""))
        elif "front" in keys:
            model = contract.RunResult if "instance" in keys else contract.RunOutput
            result = contract.load_model(path, model)
            if project is not None:
                contract.load_output(path, contract.load_manifest(project))
            typer.echo(f"OK: {model.__name__} with {len(result.front)} points, status '{result.status}'")
        else:
            raise contract.ContractError(f"{path}: cannot tell the kind of file (a project has 'objectives' and "
                                         f"'command', a setup has 'output_dir', a result has 'front')")
    except contract.ContractError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def schema(kind: str = typer.Argument(..., help="one of: " + ", ".join(SCHEMAS))) -> None:
    """Print the JSON Schema of a contract file (for editors, validators and other languages)."""
    from paretolab import contract

    if kind not in SCHEMAS:
        typer.echo(f"ERROR: unknown kind '{kind}'; choose from {', '.join(SCHEMAS)}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(getattr(contract, SCHEMAS[kind]).model_json_schema(), indent=2))


@app.command()
def run(
    setup: Path = typer.Argument(..., help="experiment.yaml"),
    jobs: int | None = typer.Option(None, "--jobs", "-j", min=1, help="runs at the same time (default: setup)"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="run again the runs stored as errors"),
    no_analysis: bool = typer.Option(False, "--no-analysis", help="do not analyse when all runs are finished"),
) -> None:
    """Run (or resume) every planned run, then analyse. Finished runs are never repeated."""
    from paretolab.contract import ContractError
    from paretolab.execution import EXIT_OK, EXIT_SETUP, Runner

    try:
        runner = Runner(setup, jobs=jobs, retry_failed=retry_failed, log=typer.echo)
    except ContractError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(EXIT_SETUP) from None
    code = runner.run()
    if code != EXIT_OK or runner.state.get("phase") != "done":
        raise typer.Exit(code)
    if not no_analysis:
        analyze(setup, runs_dir=None, no_figures=False)


@app.command()
def pause(setup: Path = typer.Argument(..., help="experiment.yaml")) -> None:
    """Ask a running experiment to pause (the runs in progress are stopped and redone on the next run)."""
    from paretolab.contract import ContractError, Setup, load_model
    from paretolab.execution.state import PAUSE_FILE

    try:
        output_dir = Path(setup).parent / load_model(setup, Setup).output_dir
    except ContractError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(2) from None
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / PAUSE_FILE).write_text("pause requested\n", encoding="utf-8")
    typer.echo(f"pause requested ({output_dir / PAUSE_FILE}); the experiment stops within a second")


@app.command()
def status(setup: Path = typer.Argument(..., help="experiment.yaml")) -> None:
    """Show the progress of an experiment."""
    from paretolab.contract import ContractError, Setup, load_model
    from paretolab.execution.state import format_duration, read_state

    try:
        output_dir = Path(setup).parent / load_model(setup, Setup).output_dir
    except ContractError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(2) from None
    state = read_state(output_dir)
    if state is None:
        typer.echo("not started")
        return
    typer.echo(f"{state['phase']}: {state['finished']} of {state['total']} runs finished, {state['failed']} failed, "
               f"{len(state.get('running', []))} running" + (f", ~{format_duration(state['eta_s'])} left"
                                                              if state.get("eta_s") and state["phase"] == "running"
                                                              else ""))
    for key, unit in (state.get("tuning") or {}).items():
        values = f" {unit['parameters']}" if unit.get("parameters") else ""
        typer.echo(f"  tuning {key}: {unit.get('status')}{values}")
    if state.get("message"):
        typer.echo(state["message"])


@app.command()
def analyze(
    setup: Path = typer.Argument(..., help="experiment.yaml"),
    runs_dir: Path | None = typer.Option(None, "--runs-dir",
                                         help="read results from here instead of <output_dir>/runs"),
    no_figures: bool = typer.Option(False, "--no-figures", help="skip the figures (faster)"),
) -> None:
    """Compute indicators, statistical tests, tables and figures into <output_dir>/analysis."""
    from paretolab.analysis import analyze as run_analysis
    from paretolab.contract import ContractError

    try:
        summary = run_analysis(setup, runs_dir=runs_dir, figures=not no_figures, log=typer.echo)
    except ContractError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from None
    for name, info in summary["indicators"].items():
        ranks = info["mean_ranks"] or {}
        best = ", ".join(f"{u} ({r:.2f})" for u, r in list(ranks.items())[:3])
        p = info["friedman_p"]
        typer.echo(f"{name}: best mean ranks {best or '-'}" + (f"; Friedman p = {p:.3g}" if p is not None else ""))
    for warning in summary["warnings"]:
        typer.echo(f"warning: {warning}")


@app.command()
def doctor() -> None:
    """Check the environment needed by paretolab."""
    typer.echo(f"paretolab {__version__}")
    typer.echo(f"Python    {platform.python_version()} ({platform.system()})")
    from paretolab.tuning import rscript as r

    found = r.find_rscript()
    typer.echo(f"Rscript   {found or 'not found (only needed for tuning). ' + r.INSTALL_R}")
    if found:
        version = r.package_version(found, "irace")
        typer.echo(f"irace     {version or 'not installed. ' + r.INSTALL_IRACE}")
