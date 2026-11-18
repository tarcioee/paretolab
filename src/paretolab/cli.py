"""Command-line interface. Subcommands (run, resume, analyze, serve) are added as each phase lands."""
import platform
import shutil

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


@app.command()
def doctor() -> None:
    """Check the environment needed by paretolab."""
    typer.echo(f"paretolab {__version__}")
    typer.echo(f"Python    {platform.python_version()} ({platform.system()})")
    rscript = shutil.which("Rscript")
    typer.echo(f"Rscript   {rscript or 'not found (only needed for tuning with irace)'}")
