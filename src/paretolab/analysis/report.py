"""Runs the whole analysis of an experiment and writes it to <output_dir>/analysis/."""
import json
from collections import defaultdict
from pathlib import Path

from paretolab.analysis import indicators as ind
from paretolab.analysis import plots, tables
from paretolab.analysis.statistics import compare
from paretolab.contract import ContractError, RunResult, load_experiment, load_model
from paretolab.contract.layout import ANALYSIS, RUNS, result_files

MAX_FIGURE_INSTANCES = 12


def load_runs(runs_root: Path) -> list[RunResult]:
    runs, problems = [], []
    for path in result_files(runs_root):
        try:
            runs.append(load_model(path, RunResult))
        except ContractError as exc:
            problems.append(str(exc))
    if problems:
        raise ContractError(f"{len(problems)} invalid result files:\n" + "\n".join(problems[:10]))
    return runs


def analyze(setup_path, runs_dir=None, figures: bool = True, log=print) -> dict:
    """Analyse the runs of an experiment; returns the summary that is also written to summary.json."""
    setup, manifest, plan = load_experiment(setup_path)
    output_dir = Path(setup_path).parent / setup.output_dir
    runs_root = Path(runs_dir) if runs_dir else output_dir / RUNS
    out = output_dir / ANALYSIS
    out.mkdir(parents=True, exist_ok=True)
    warnings = []

    wanted_instances = {i.name for i in plan.instances}
    wanted = {(i, a, v, s) for i in wanted_instances for a, v in plan.units for s in plan.seeds}
    found = [r for r in load_runs(runs_root) if (r.instance, r.algorithm, r.variant, r.seed) in wanted]
    for run in found:
        run.check_against(manifest)
    missing = len(wanted) - len(found)
    if missing:
        warnings.append(f"{missing} of {len(wanted)} planned runs have no result in {runs_root}")
    if not found:
        raise ContractError(f"no results of this experiment in {runs_root}")
    errors = sum(r.status == "error" for r in found)
    if errors:
        warnings.append(f"{errors} runs ended with status 'error' and are left out")
    log(f"analysing {len(found)} runs ({len(plan.instances)} instances, {len(plan.units)} variants)")

    df, references = ind.compute(found, manifest, plan.indicators, setup.normalization.reference_offset)
    df.to_csv(out / "indicators_per_run.csv", index=False)
    summary = {"project": manifest.name, "runs_analysed": len(found), "runs_planned": len(wanted),
               "indicators": {}, "references": {}, "figures": [], "warnings": warnings}
    for name, ref in references.items():
        summary["references"][name] = {"runs_used": ref.runs_used, "reference_set_size":
                                       0 if ref.reference_set is None else len(ref.reference_set),
                                       "hv_reference": ref.hv_reference, "notes": ref.notes}
        warnings += [f"instance {name}: {n}" for n in ref.notes]

    instances = sorted(df["instance"].unique())
    for name in plan.indicators:
        hib = ind.higher_is_better(name, manifest)
        files = tables.write(tables.summary(df, name), name, hib, out / "tables" / name)
        result = compare(df, name, hib, setup.statistics.tests, setup.statistics.alpha,
                         setup.statistics.blocks, setup.statistics.aggregation)
        (out / "statistics").mkdir(exist_ok=True)
        stats_file = out / "statistics" / f"{name}.json"
        stats_file.write_text(json.dumps(result, indent=1), encoding="utf-8")
        summary["indicators"][name] = {"higher_is_better": hib, "tables": {k: str(v) for k, v in files.items()},
                                       "statistics": str(stats_file), "mean_ranks": result.get("mean_ranks"),
                                       "friedman_p": result.get("friedman", {}).get("p_value")}
        warnings += [f"{name}: {w}" for w in result["warnings"]]
        if figures and "nemenyi" in result:
            summary["figures"].append(str(plots.cd_diagram(
                result["mean_ranks"], result["nemenyi"]["critical_difference"],
                f"{ind.LABELS[name]}: mean ranks, {result['n_blocks']} blocks ({result['blocks']})",
                out / "figures" / f"cd_{name}.png")))
        if figures:
            for instance in instances[:MAX_FIGURE_INSTANCES]:
                summary["figures"].append(str(plots.boxplot(df, name, instance,
                                                            out / "figures" / f"box_{name}_{instance}.png")))
                if not manifest.is_multiobjective:
                    summary["figures"].append(str(plots.quality_ecdf(
                        df, name, instance, out / "figures" / f"ecdf_{name}_{instance}.png")))

    if figures:
        summary["figures"] += _instance_figures(found, manifest, instances[:MAX_FIGURE_INSTANCES], out / "figures")
        if len(instances) > MAX_FIGURE_INSTANCES:
            warnings.append(f"per-instance figures only for the first {MAX_FIGURE_INSTANCES} instances")
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"analysis written to {out}")
    return summary


def _instance_figures(runs, manifest, instances, folder) -> list:
    made = []
    for instance in instances:
        by_unit, traces = defaultdict(list), defaultdict(list)
        for r in runs:
            if r.instance == instance and r.status != "error":
                by_unit[ind.unit_label(r.algorithm, r.variant)].append(r.front)
                if r.convergence_trace:
                    traces[ind.unit_label(r.algorithm, r.variant)].append(r.convergence_trace)
        if len(manifest.objectives) == 2:
            made.append(str(plots.attainment(by_unit, manifest.objectives, instance,
                                             folder / f"attainment_{instance}.png")))
        if not manifest.is_multiobjective and traces:
            made.append(str(plots.convergence(traces, manifest.objectives[0], instance,
                                              folder / f"convergence_{instance}.png")))
    return made
