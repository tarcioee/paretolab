from typer.testing import CliRunner

from paretolab import __version__
from paretolab.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_validate_detects_kinds(tmp_path, tsp):
    import json

    import yaml

    (tmp_path / "project.yaml").write_text(yaml.safe_dump(tsp), encoding="utf-8")
    (tmp_path / "experiment.yaml").write_text(yaml.safe_dump(
        {"output_dir": "o", "seeds": {"count": 2}, "budget": {"time_limit_s": 5}}), encoding="utf-8")
    (tmp_path / "out.json").write_text(json.dumps({"front": [[3400.0]]}), encoding="utf-8")
    r = runner.invoke(app, ["validate", str(tmp_path / "project.yaml")])
    assert r.exit_code == 0 and "single-objective" in r.output
    r = runner.invoke(app, ["validate", str(tmp_path / "experiment.yaml")])
    assert r.exit_code == 0 and "= 4 runs" in r.output and "best, gap" in r.output
    r = runner.invoke(app, ["validate", str(tmp_path / "out.json"), "--project", str(tmp_path / "project.yaml")])
    assert r.exit_code == 0 and "RunOutput with 1 points" in r.output


def test_validate_reports_errors(tmp_path):
    (tmp_path / "x.yaml").write_text("foo: 1\n", encoding="utf-8")
    r = runner.invoke(app, ["validate", str(tmp_path / "x.yaml")])
    assert r.exit_code == 1 and "cannot tell the kind" in r.output


def test_schema():
    import json

    r = runner.invoke(app, ["schema", "output"])
    assert r.exit_code == 0 and "front" in json.loads(r.output)["properties"]
    assert runner.invoke(app, ["schema", "nope"]).exit_code == 1
