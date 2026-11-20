// Step 3: the analysis. Charts chosen by kind, indicator and instance, with the matching statistical test;
// the tables of every indicator; and what was run (parameters, times, files, warnings).
import { $, api, fill, h, store, toast } from "./dom.js";
import { cap, duration, errorText, has, msg, num, pvalue, t, term, when } from "./i18n.js";
import { analyzing, emit, phase, S, unitLabel } from "./state.js";
import { alertBox, badge, card, counter, help, kv, openFolder, table, tabs } from "./ui.js";

let view = store("paretolab.an.view") || "charts";
const sel = { kind: null, indicator: null, instance: null };
let tableIndicator = null;
let noFigures = false;
const KINDS = ["cd", "box", "ecdf", "attainment", "convergence"];
const WITH_INDICATOR = new Set(["cd", "box", "ecdf"]);

export async function loadAnalysis(force = false) {
  try {
    const a = await api("/api/analysis");
    if (!force && S.analysis?.available && a.available && a.updated_at === S.analysis.updated_at) return;
    S.analysis = a;
  } catch (e) {
    S.analysis = { available: false, error: errorText(e) };
  }
  renderAnalysis();
}

export async function analyzeNow() {
  try {
    await api("/api/analyze", { no_figures: noFigures });
    toast(t("an.started_toast"));
    emit("analysis-started");
  } catch (e) { toast(errorText(e), true); }
}

const indicatorLabel = name => (has(`ind.${name}`) ? t(`ind.${name}`) : S.analysis.indicators.find(i => i.name === name)?.label ?? name);
const instanceLabel = name => (name ? name : t("an.all_instances"));

// ------------------------------------------------------------------ statistics of one indicator

function statisticsView(ind) {
  const st = ind?.statistics;
  if (!st) return null;
  const f = st.friedman;
  const out = [h("div", { class: "counters" },
    counter(f ? pvalue(f.p_value) : "–", t("an.friedman_p")),
    counter(f ? (f.reject_h0 ? t("confirm.yes") : t("confirm.no")) : "–", t("an.h0_rejected"), { tone: f?.reject_h0 ? "ok" : "" }),
    counter(st.nemenyi ? num(st.nemenyi.critical_difference, 3) : "–", t("an.cd")),
    counter(num(st.n_blocks), t("an.blocks", { kind: t(`an.blocks_${st.blocks}`) })))];
  if (st.mean_ranks) {
    const ranks = Object.entries(st.mean_ranks);
    const max = Math.max(...ranks.map(([, r]) => r));
    out.push(table([t("an.position"), t("run.col_variant"), t("an.mean_rank"), ""],
      ranks.map(([u, r], i) => [String(i + 1), unitLabel(u), num(r, 3), h("span", { class: "rank-bar", style: { width: `${Math.max(4, (140 * r) / max)}px` } })]),
      { numeric: [0, 2] }));
  }
  out.push(help(t(st.aggregation ? "an.test_note" : "an.test_note_pairs", { alpha: num(st.alpha),
    better: ind.higher_is_better ? t("an.higher") : t("an.lower"),
    aggregation: st.aggregation ? t(`an_setup.${st.aggregation}`) : "" })));
  if (st.nemenyi) {
    const units = Object.keys(st.nemenyi.p_values);
    out.push(h("details", { class: "fold" }, h("summary", {}, t("an.nemenyi")),
      table(["", ...units.map(unitLabel)], units.map(a => h("tr", {}, h("td", {}, unitLabel(a)), units.map(b => {
        const p = st.nemenyi.p_values[a][b];
        return h("td", { class: "num" + (a !== b && p < st.alpha ? " sig" : "") }, a === b ? "" : pvalue(p));
      }))))));
  }
  if (st.wilcoxon_holm) {
    out.push(h("details", { class: "fold", open: st.wilcoxon_holm.length <= 12 }, h("summary", {}, t("an.wilcoxon")),
      table([t("an.col_a"), t("an.col_b"), t("an.col_median_diff"), "p", t("an.col_p_holm"), t("an.col_better")],
        st.wilcoxon_holm.map(p => h("tr", { class: p.significant ? "sig" : "" }, h("td", {}, unitLabel(p.a)), h("td", {}, unitLabel(p.b)),
          h("td", { class: "num" }, num(p.median_difference)), h("td", { class: "num" }, pvalue(p.p_value)),
          h("td", { class: "num" }, pvalue(p.p_holm)), h("td", {}, p.significant ? unitLabel(p.better ?? "–") : "–"))),
        { numeric: [2, 3, 4] })));
  }
  const warnings = st.warnings_info?.length ? st.warnings_info.map(msg) : st.warnings ?? [];
  if (warnings.length) out.push(h("ul", { class: "help" }, warnings.map(w => h("li", {}, w))));
  if (ind.files?.statistics) out.push(h("p", { class: "small" }, h("a", { href: ind.files.statistics, target: "_blank" }, t("an.stats_file"))));
  return h("div", {}, out);
}

// ------------------------------------------------------------------ charts

function options(key) {
  const figs = S.analysis.figures;
  if (key === "kind") return KINDS.filter(k => figs.some(f => f.kind === k));
  const pool = figs.filter(f => f.kind === sel.kind && (key === "indicator" || !WITH_INDICATOR.has(sel.kind) || f.indicator === sel.indicator));
  const values = [...new Set(pool.map(f => f[key] ?? null))];
  return key === "instance" ? values.sort((a, b) => (a === null ? -1 : b === null ? 1 : String(a).localeCompare(String(b)))) : values;
}

function settle() {
  const kinds = options("kind");
  if (!kinds.includes(sel.kind)) sel.kind = kinds[0] ?? null;
  if (WITH_INDICATOR.has(sel.kind)) {
    const inds = options("indicator");
    if (!inds.includes(sel.indicator)) sel.indicator = inds[0] ?? null;
  }
  const insts = options("instance");
  if (!insts.includes(sel.instance)) sel.instance = insts[0] ?? null;
}

function selectBox(label, key, values, show) {
  return h("div", { class: "filter" }, h("label", {}, label), h("select", { disabled: values.length <= 1,
    onchange: e => { sel[key] = e.target.value === "" ? null : e.target.value; settle(); renderAnalysis(); } },
  values.map(v => h("option", { value: v ?? "", selected: v === sel[key] }, show(v)))));
}

function chartsView() {
  const a = S.analysis;
  if (!a.figures.length) {
    const names = a.indicators.map(i => i.name);
    if (!names.includes(sel.indicator)) sel.indicator = names[0];
    const ind = a.indicators.find(i => i.name === sel.indicator);
    return [alertBox(t("an.no_figures"), "info"),
      card(null, h("div", { class: "filters" }, h("div", { class: "filter" }, h("label", {}, t("an.indicator")),
        h("select", { onchange: e => { sel.indicator = e.target.value; renderAnalysis(); } },
          names.map(n => h("option", { value: n, selected: n === sel.indicator }, indicatorLabel(n)))))),
      h("h2", {}, t("an.test_title")), statisticsView(ind))];
  }
  settle();
  const fig = a.figures.find(f => f.kind === sel.kind && (f.indicator ?? null) === (WITH_INDICATOR.has(sel.kind) ? sel.indicator : null)
    && (f.instance ?? null) === sel.instance) ?? a.figures.find(f => f.kind === sel.kind);
  const ind = WITH_INDICATOR.has(sel.kind) ? a.indicators.find(i => i.name === sel.indicator) : null;
  const caption = [t(`chart.${fig.kind}`), fig.indicator ? indicatorLabel(fig.indicator) : null,
    fig.instance ? `${cap(term("instance"))} ${fig.instance}` : null].filter(Boolean).join(" · ");
  const stamp = Math.round(a.updated_at);
  return [
    card(null, h("div", { class: "filters" },
      selectBox(t("an.chart"), "kind", options("kind"), k => t(`chart.${k}`)),
      WITH_INDICATOR.has(sel.kind) ? selectBox(t("an.indicator"), "indicator", options("indicator"), indicatorLabel) : null,
      selectBox(cap(term("instance")), "instance", options("instance"), instanceLabel)),
    help(t(`chart_help.${fig.kind}`)),
    h("figure", { class: "figure" }, h("figcaption", {}, caption),
      h("a", { href: fig.url, target: "_blank", title: t("an.open_full") }, h("img", { src: `${fig.url}?t=${stamp}`, alt: caption }))),
    h("div", { class: "buttons" }, h("a", { class: "btn btn-sec", href: fig.url, download: fig.name }, t("an.download")),
      h("span", { class: "help mono" }, fig.name))),
    ind ? card(t("an.test_title_for", { indicator: indicatorLabel(ind.name) }), statisticsView(ind)) : null,
  ];
}

// ------------------------------------------------------------------ tables

function tablesView() {
  const a = S.analysis;
  if (!a.indicators.find(i => i.name === tableIndicator)) tableIndicator = a.indicators[0]?.name;
  const ind = a.indicators.find(i => i.name === tableIndicator);
  const pills = h("div", { class: "pills" }, a.indicators.map(i => h("button", { type: "button", "aria-pressed": String(i.name === tableIndicator),
    onclick: () => { tableIndicator = i.name; renderAnalysis(); } }, indicatorLabel(i.name))));
  if (!ind) return [card(null, help(t("an.no_tables")))];
  const files = Object.entries(ind.files).filter(([k]) => k !== "statistics");
  return [card(null, pills,
    h("h2", {}, indicatorLabel(ind.name), h("span", { class: "help inline" }, ` ${ind.higher_is_better ? t("an.higher_better") : t("an.lower_better")}`)),
    help(t("an.table_help")),
    ind.table ? h("div", { class: "scroll-x" }, h("table", { class: "tab" },
      h("thead", {}, h("tr", {}, h("th", {}, cap(term("instance"))), ind.table.units.map(u => h("th", { class: "num" }, unitLabel(u))))),
      h("tbody", {}, ind.table.rows.map(r => h("tr", {}, h("td", {}, r.instance),
        r.cells.map(c => h("td", { class: "num" + (c.best ? " best" : "") }, c.text))))))) : help(t("an.no_tables")),
    files.length ? h("div", { class: "buttons downloads" }, h("span", { class: "help" }, t("an.files")),
      files.map(([k, url]) => h("a", { class: "btn btn-sec btn-small", href: url, target: "_blank" }, k.toUpperCase()))) : null,
    a.per_run ? h("p", { class: "small" }, h("a", { href: a.per_run, target: "_blank" }, t("an.per_run"))) : null)];
}

// ------------------------------------------------------------------ information

function infoView() {
  const a = S.analysis;
  const s = a.summary;
  const out = [];
  if (a.parameters) {
    out.push(card(t("an.parameters_used"), table([t("run.col_variant"), cap(term("parameters"))],
      Object.entries(a.parameters).filter(([u]) => s.units?.includes(unitLabel(u)) ?? true).map(([u, p]) => [unitLabel(u),
        Object.keys(p.values).length ? h("span", { class: "mono small" }, Object.entries(p.values).map(([k, v]) =>
          `${k} = ${num(v)}${p.tuned.includes(k) ? " *" : ""}`).join("  ·  ")) : "–"])),
    Object.values(a.parameters).some(p => p.tuned.length) ? help(t("an.tuned_mark")) : null));
  }
  if (a.times) {
    out.push(card(t("an.times"), h("div", { class: "counters" },
      counter(duration(a.times.total_s), t("an.total_time")), counter(duration(a.times.mean_s), t("an.mean_time")),
      counter(num(a.times.runs), t("an.runs_timed"))),
    table([t("run.col_variant"), t("an.runs"), t("an.mean"), t("an.min"), t("an.max")],
      a.times.units.map(u => [unitLabel(u.unit), num(u.count), duration(u.mean), duration(u.min), duration(u.max)]),
      { numeric: [1, 2, 3, 4] }), help(t("an.times_help"))));
  }
  const refs = Object.entries(s.references ?? {});
  out.push(card(t("an.metadata"), kv([
    [t("project.title"), s.project],
    [t("an.generated"), when(s.generated_at ?? new Date(a.updated_at * 1000).toISOString())],
    [t("an.runs_analysed"), t("an.of", { a: num(s.runs_analysed), b: num(s.runs_planned) })],
    s.instances ? [cap(term("instances")), s.instances.join(", ")] : null,
    s.units ? [t("setup.variants_title"), s.units.join(", ")] : null,
    ...refs.map(([name, r]) => [t("an.reference", { instance: name }),
      t("an.reference_text", { runs: r.runs_used, size: r.reference_set_size })]),
  ]), h("div", { class: "buttons downloads" }, a.per_run ? h("a", { class: "btn btn-sec btn-small", href: a.per_run, target: "_blank" }, t("an.per_run_short")) : null,
    Object.entries(a.files ?? {}).map(([k, url]) => h("a", { class: "btn btn-sec btn-small", href: url, target: "_blank" }, t(`an.file_${k}`))),
    h("button", { type: "button", class: "btn btn-sec btn-small", onclick: () => openFolder("analysis") }, t("action.open_folder")))));
  const warnings = s.warnings_info?.length ? s.warnings_info.map(msg) : s.warnings ?? [];
  out.push(card(t("an.warnings"), warnings.length ? h("ul", {}, warnings.map(w => h("li", {}, w))) : help(t("an.no_warnings"))));
  return out;
}

// ------------------------------------------------------------------ the step

function banner() {
  const a = S.analysis;
  const busy = !!S.status?.alive || analyzing();
  const complete = a.available && a.summary.runs_analysed >= a.summary.runs_planned;
  const title = !a.available ? t("an.none_title") : analyzing() ? t("an.running_title") : complete ? t("an.done_title") : t("an.partial_title");
  const line = a.available ? t("an.summary_line", { a: num(a.summary.runs_analysed), b: num(a.summary.runs_planned),
    when: when(a.summary.generated_at ?? new Date(a.updated_at * 1000).toISOString()) }) : a.error ?? t("an.none_help");
  return h("div", { class: "card band" }, h("div", {}, h("h2", {}, title), help(line)),
    h("div", { class: "buttons" },
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: noFigures, onchange: e => { noFigures = e.target.checked; } }), t("an.without_figures")),
      h("button", { type: "button", class: "btn btn-sec", disabled: busy || !S.setupInfo?.exists, onclick: analyzeNow },
        analyzing() ? t("an.analysing") : t("an.analyse_now")),
      h("button", { type: "button", class: "btn btn-sec", onclick: () => emit("goto", "setup") }, t("an.new_experiment"))));
}

export function renderAnalysis() {
  const root = $("#step-analysis");
  if (!root || !S.analysis) return;
  const scroll = window.scrollY;
  const a = S.analysis;
  const parts = [banner()];
  if (a.available) {
    const warnings = a.summary.warnings_info?.length ? a.summary.warnings_info : a.summary.warnings ?? [];
    if (warnings.length) parts.push(h("details", { class: "alert alert-warn fold" }, h("summary", {}, t("an.warnings_count", { n: warnings.length })),
      h("ul", {}, warnings.map(w => h("li", {}, msg(w))))));
    parts.push(tabs([["charts", t("an.tab_charts")], ["tables", t("an.tab_tables")], ["info", t("an.tab_info")]], view,
      v => { view = v; store("paretolab.an.view", v); renderAnalysis(); }),
    h("div", { class: "panel" }, view === "tables" ? tablesView() : view === "info" ? infoView() : chartsView()));
  } else if (phase() !== "done") {
    parts.push(alertBox(t("an.wait_runs"), "info"));
  }
  fill(root, ...parts);
  window.scrollTo(0, scroll);
}

