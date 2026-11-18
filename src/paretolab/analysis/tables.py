"""Summary tables: one row per instance, one column per algorithm variant, in CSV, Markdown and LaTeX."""
import pandas as pd

from paretolab.analysis.indicators import LABELS


def summary(df: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Long table: instance, unit, runs, mean, std, median, iqr (NaN values, e.g. no solution, are skipped)."""
    groups = df[df["status"] != "error"].groupby(["instance", "unit"])[indicator]
    table = groups.agg(runs="size", valid="count", mean="mean", std="std", median="median")
    table["iqr"] = groups.quantile(0.75) - groups.quantile(0.25)
    return table.reset_index()


def _fmt(x: float) -> str:
    return "-" if pd.isna(x) else f"{x:.4g}"


def wide(table: pd.DataFrame, higher_is_better: bool) -> tuple[list, list]:
    """(units, rows): rows are (instance, [(cell text, is_best)]) with "mean (std)" cells."""
    units = sorted(table["unit"].unique())
    rows = []
    for instance, block in table.groupby("instance"):
        means = block.set_index("unit")["mean"]
        best = means.max() if higher_is_better else means.min()
        cells = []
        for u in units:
            if u not in means.index or pd.isna(means[u]):
                cells.append(("-", False))
                continue
            row = block[block["unit"] == u].iloc[0]
            cells.append((f"{_fmt(row['mean'])} ({_fmt(row['std'])})", means[u] == best))
        rows.append((instance, cells))
    return units, rows


def write(table: pd.DataFrame, indicator: str, higher_is_better: bool, base_path) -> dict:
    """Writes <base>.csv (long), <base>.md and <base>.tex (wide); returns their paths."""
    paths = {"csv": base_path.with_suffix(".csv"), "md": base_path.with_suffix(".md"),
             "tex": base_path.with_suffix(".tex")}
    base_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(paths["csv"], index=False)
    units, rows = wide(table, higher_is_better)
    arrow = "higher is better" if higher_is_better else "lower is better"
    title = f"{LABELS.get(indicator, indicator)}: mean (standard deviation) per instance; {arrow}; best in bold."

    md = [f"{title}\n", "| instance | " + " | ".join(units) + " |", "|---" * (len(units) + 1) + "|"]
    md += [f"| {inst} | " + " | ".join(f"**{c}**" if b else c for c, b in cells) + " |" for inst, cells in rows]
    paths["md"].write_text("\n".join(md) + "\n", encoding="utf-8")

    def tex(s):
        return s.replace("_", r"\_").replace("%", r"\%")

    lines = [r"\begin{table}[htbp]", r"\centering", f"\\caption{{{tex(title)}}}",
             r"\begin{tabular}{l" + "r" * len(units) + "}", r"\hline",
             "Instance & " + " & ".join(tex(u) for u in units) + r" \\", r"\hline"]
    lines += [tex(str(inst)) + " & " + " & ".join(f"\\textbf{{{c}}}" if b else c for c, b in cells) + r" \\"
              for inst, cells in rows]
    lines += [r"\hline", r"\end{tabular}", r"\end{table}"]
    paths["tex"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths
