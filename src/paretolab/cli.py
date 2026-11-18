"""Command-line interface. Subcommands (run, resume, analyze, serve) are added as each phase lands."""
import json
import platform
import shutil
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
def doctor() -> None:
    """Check the environment needed by paretolab."""
    typer.echo(f"paretolab {__version__}")
    typer.echo(f"Python    {platform.python_version()} ({platform.system()})")
    rscript = shutil.which("Rscript")
    typer.echo(f"Rscript   {rscript or 'not found (only needed for tuning with irace)'}")
