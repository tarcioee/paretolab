// Step 2: the experiment running. Progress, time left, tuning, every instance, details and logs.
import { $, api, fill, h, store, toast } from "./dom.js";
import { cap, duration, errorText, msg, num, t, term, text, when } from "./i18n.js";
import { analyzing, emit, on, phase, S, unitLabel } from "./state.js";
import { alertBox, badge, card, counter, help, kv, miniBar, pathLine, progressBar, table, tabs } from "./ui.js";

let view = store("paretolab.run.view") || "progress";
let logChoice = null;
let retryFailed = false;

// ------------------------------------------------------------------ the scene: a Pareto front taking shape

const DOTS = 46;
let scene = null;

function seeded(seed) {
  let x = seed;
  return () => { x = (x * 1664525 + 1013904223) % 4294967296; return x / 4294967296; };
}

function buildScene() {
  const random = seeded(7);
  const W = 600, H = 120;
  // objective 1 to the right, objective 2 up: a convex front from the top left to the bottom right, and the
  // dominated points above and to its right, moving onto it as the runs finish
  const front = u => [40 + u * 520, 106 - 88 * (1 - Math.sqrt(u))];
  const dots = Array.from({ length: DOTS }, (_, i) => {
    const u = (i + 0.5) / DOTS;
    const [fx, fy] = front(u);
    return { fx, fy, sx: Math.min(588, fx + 20 + random() * 140), sy: Math.max(8, fy - 18 - random() * 70), delay: random() * 4 };
  });
  const path = Array.from({ length: 41 }, (_, i) => front(i / 40)).map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet", class: "scene-svg", "aria-hidden": "true" },
    h("path", { d: path, class: "scene-front" }),
    dots.map(d => h("circle", { r: "3.2", class: "scene-dot", style: { animationDelay: `-${d.delay}s` } })));
  scene = { svg, dots, circles: [...svg.querySelectorAll("circle")], last: -1 };
  return h("div", { class: "scene", id: "scene" }, svg);
}

function moveScene(fraction) {
  if (!scene) return;
  const f = Math.max(0, Math.min(1, fraction));
  if (Math.abs(f - scene.last) < 0.002) return;
  scene.last = f;
  const ease = 1 - (1 - f) ** 2;
  scene.dots.forEach((d, i) => {
    const x = d.sx + (d.fx - d.sx) * ease, y = d.sy + (d.fy - d.sy) * ease;
    const c = scene.circles[i];
    c.setAttribute("cx", x.toFixed(1));
    c.setAttribute("cy", y.toFixed(1));
    c.style.cx = `${x.toFixed(1)}px`;        // as CSS too, so the move is animated
    c.style.cy = `${y.toFixed(1)}px`;
    c.classList.toggle("on-front", ease > 0.97);
  });
}

// ------------------------------------------------------------------ actions

export async function startRun() {
  try {
    await api("/api/run", { retry_failed: retryFailed });
    toast(t("run.started_toast"));
    emit("goto", "run");
    emit("poll-soon");
  } catch (e) { toast(errorText(e), true); }
}

async function pause() {
  try {
    await api("/api/pause", {});
    toast(t("run.pause_toast"));
    emit("poll-soon");
  } catch (e) { toast(errorText(e), true); }
}

on("start-run", startRun);

// ------------------------------------------------------------------ progress tab

const PHASE_TONE = { running: "info", tuning: "info", paused: "warn", interrupted: "bad", failed: "bad", done: "ok", none: "" };

export function phaseLabel(p = phase()) {
  if (analyzing() && !S.status?.alive) return { text: t("phase.analysing"), tone: "info" };
  return { text: t(`phase.${p}`), tone: PHASE_TONE[p] ?? "" };
}

function statusCard() {
  const st = S.status;
  const state = st?.state;
  const p = phase();
  const total = state?.total ?? 0, finished = state?.finished ?? 0;
  const fraction = p === "done" ? 1 : total ? finished / total : 0;
  const tuning = p === "tuning" && st.alive;
  const title = !state ? t("run.title_none") : st.pause_requested && st.alive ? t("run.title_pausing") : t(`run.title_${p}`);
  const message = state?.message_info ? msg(state.message_info) : state?.message || "";
  const canStart = !st?.alive && !analyzing() && S.setupInfo?.exists && S.check?.ok !== false;
  const startLabel = !state ? t("action.start") : p === "done" ? t("action.run_again") : t("action.resume");
  const elapsed = state?.elapsed_s ?? (state?.started_at && state?.updated_at
    ? (Date.parse(state.updated_at) - Date.parse(state.started_at)) / 1000 : null);
  let left = "–";
  if (p === "done") left = duration(0);
  else if (st?.alive && p === "running") left = state?.eta_s !== undefined && state?.eta_s !== null ? duration(state.eta_s) : t("run.estimating");
  else if (tuning) left = t("run.after_tuning");
  const running = (state?.running ?? []).length;

  return h("div", { class: "card status-card" },
    h("div", { class: "status-line" },
      h("div", {}, h("h2", {}, title), message && message.toLowerCase() !== title.toLowerCase() ? help(message) : null,
        !state ? help(t("run.none_help")) : null),
      h("div", { class: "buttons" },
        st?.alive ? h("button", { type: "button", class: "btn btn-prim", disabled: st.pause_requested, onclick: pause },
          st.pause_requested ? t("run.pausing") : t("action.pause")) : null,
        !st?.alive ? h("label", { class: "check", title: t("run.retry_help") }, h("input", { type: "checkbox", checked: retryFailed,
          onchange: e => { retryFailed = e.target.checked; } }), t("run.retry")) : null,
        !st?.alive ? h("button", { type: "button", class: "btn btn-prim", disabled: !canStart, onclick: startRun,
          title: p === "done" ? t("run.again_help") : "" }, startLabel) : null)),
    buildSceneOnce(st?.alive && !st.pause_requested),
    progressBar(fraction, `${Math.floor(100 * fraction)}%` + (total ? `  (${num(finished)}/${num(total)})` : "")),
    p === "done" && analyzing() ? alertBox(t("run.analysing_note"), "info") : null,
    h("div", { class: "counters" },
      counter(state ? `${num(finished)} / ${num(total)}` : "–", t("run.finished")),
      counter(state ? num(state.failed ?? 0) : "–", t("run.failed"), { tone: state?.failed ? "bad" : "" }),
      counter(state ? `${running} / ${state.jobs ?? "–"}` : "–", t("run.processes")),
      counter(elapsed !== null ? duration(elapsed) : "–", t("run.elapsed")),
      counter(left, t("run.left"), { highlight: true })),
    help(t("run.estimate_note") + (state?.mean_run_s ? " " + t("run.mean_run", { time: duration(state.mean_run_s) }) : "")),
    ["paused", "interrupted", "failed"].includes(p) ? help(t("run.resume_note")) : null);
}

function buildSceneOnce(moving) {
  const el = scene ? scene.svg.parentNode : buildScene();
  el.classList.toggle("still", !moving);
  return el;
}

function tuningCard() {
  const units = S.status?.state?.tuning;
  if (!units || !Object.keys(units).length) return null;
  const done = Object.values(units).filter(u => ["done", "skipped"].includes(u.status)).length;
  const TONE = { done: "ok", running: "info", failed: "bad", paused: "warn", skipped: "" };
  return card(t("run.tuning_title"), help(t("run.tuning_summary", { done, total: Object.keys(units).length })),
    table([t("run.col_variant"), t("run.col_status"), t("run.col_time"), t("run.col_values")],
      Object.entries(units).map(([key, u]) => [unitLabel(key), badge(t(`tstatus.${u.status}`), TONE[u.status] ?? ""),
        u.elapsed_s ? duration(u.elapsed_s) : "–",
        u.parameters ? h("span", { class: "mono small" }, Object.entries(u.parameters).map(([k, v]) => `${k} = ${num(v)}`).join("  ·  "))
          : h("span", { class: "help" }, msg(u.message_info) || u.message || "")])));
}

function progressView() {
  const st = S.status;
  const p = phase();
  const notes = [];
  if (p === "interrupted") notes.push(alertBox(t("run.interrupted_alert", { pid: st.state.pid }), "error"));
  if (p === "failed") notes.push(alertBox(t("run.failed_alert"), "error"));
  if (st?.children?.run && !st.children.run.running && st.children.run.exit_code && p !== "failed")
    notes.push(alertBox(t("run.exit_code", { code: st.children.run.exit_code }), "error"));
  return [...notes, statusCard(), tuningCard()];
}

// ------------------------------------------------------------------ instances tab

function instancesView() {
  const g = S.status?.grid;
  if (!g) return [card(cap(term("instances")), help(t("run.no_grid")))];
  const running = new Set((S.status.state?.running ?? []).map(id => id.split("/")[0]));
  const rows = g.instances.map((inst, i) => {
    const cells = g.cells[i];
    const done = cells.reduce((a, c) => a + c.done, 0), total = cells.reduce((a, c) => a + c.total, 0);
    const failed = cells.reduce((a, c) => a + c.failed, 0);
    const state = done >= total ? "done" : running.has(inst) ? "running" : done ? "partial" : "pending";
    const tone = { done: "ok", running: "info", partial: "warn", pending: "" }[state];
    return h("div", { class: `inst ${state}` }, h("div", { class: "inst-name" }, inst),
      h("div", {}, badge(t(`istate.${state}`), tone), miniBar(total ? done / total : 0, failed > 0)),
      h("div", { class: "help" }, t("run.inst_runs", { done: num(done), total: num(total) }),
        failed ? h("span", { class: "bad-text" }, ` · ${t("run.inst_failed", { n: failed })}`) : null));
  });
  const matrix = h("div", { class: "scroll-x" }, h("table", { class: "tab grid" },
    h("thead", {}, h("tr", {}, h("th", {}, t("run.col_variant")), g.instances.map(i => h("th", { class: "num" }, i)))),
    h("tbody", {}, g.units.map((u, j) => h("tr", {}, h("td", { class: "nowrap" }, unitLabel(u)),
      g.instances.map((_, i) => {
        const c = g.cells[i][j];
        return h("td", { class: "cell" + (c.failed ? " failed" : ""), title: c.failed ? t("run.inst_failed", { n: c.failed }) : "" },
          h("span", { class: "cell-count" }, `${c.done}/${c.total}`), miniBar(c.total ? c.done / c.total : 0, c.failed > 0));
      }))))));
  const runningNow = S.status.state?.running ?? [];
  return [card(cap(term("instances")), h("div", { class: "inst-list" }, rows)),
    card(t("run.matrix_title"), help(t("run.matrix_help")), matrix,
      runningNow.length ? h("p", { class: "small" }, h("strong", {}, t("run.running_now")), " ", runningNow.join(", ")) : null)];
}

// ------------------------------------------------------------------ details tab

function setupSummary() {
  const s = S.check?.summary;
  const d = S.saved ?? {};
  if (!s) return help(t("run.no_setup"));
  const b = d.budget ?? {};
  return kv([
    [t("setup.output_dir"), s.output_dir],
    [cap(term("instances")), s.instances.join(", ")],
    [t("setup.variants_title"), s.units.map(unitLabel).join(", ")],
    [cap(term("seeds")), Array.isArray(d.seeds) ? d.seeds.join(", ") : t("run.seed_range", { n: d.seeds?.count, start: d.seeds?.start ?? 1 })],
    [t("setup.evaluations"), b.max_evaluations ? num(b.max_evaluations) : t("setup.no_limit")],
    [t("setup.time_limit"), b.time_limit_s ? duration(b.time_limit_s) : t("setup.no_limit")],
    [t("tuning.title"), d.tuning?.enabled ? t("confirm.yes") : t("confirm.no")],
    [t("setup.jobs"), d.parallel_jobs === 1 ? t("confirm.sequential") : d.parallel_jobs ? String(d.parallel_jobs) : t("setup.jobs_auto")],
  ]);
}

export function projectCards() {
  const m = S.manifest;
  const command = Array.isArray(m.command) ? m.command.join(" ") : m.command;
  return [
    card(t("project.title"), h("p", {}, h("strong", {}, m.name), m.description ? ` — ${text(m.description)}` : ""),
      help(S.project.multiobjective ? t("project.mo", { n: m.objectives.length }) : t("project.so")),
      pathLine(t("setup.project_file"), S.project.path, null),
      h("h3", {}, t("project.command")), h("pre", { class: "code" }, command),
      help(t("project.param_format", { format: m.param_format }) + (m.executable ? ` · ${t("project.executable", { exe: m.executable })}` : ""))),
    card(cap(term("objectives")), table([t("project.name"), t("project.sense"), t("project.unit"), t("project.description")],
      m.objectives.map(o => [o.name, t(`sense.${o.sense}`), o.unit ?? "–", text(o.description) || "–"]))),
    card(`${cap(term("instances"))} (${m.instances.length})`, table([t("project.name"), t("project.path"), t("project.optimum"), t("project.description")],
      m.instances.map(i => [i.name, h("span", { class: "small mono" }, i.path ?? "–"), i.optimum ?? "–", text(i.description) || "–"]))),
    card(cap(term("algorithms")), m.algorithms.map(a => h("div", { class: "alg-block" },
      h("h3", {}, a.name, h("span", { class: "help inline" }, ` ${cap(term("variants"))}: ${a.variants.join(", ")}`)),
      a.description ? help(text(a.description)) : null,
      a.parameters.length ? table([t("param.name"), t("param.type_col"), t("param.domain"), t("param.default_col"), t("param.condition_col")],
        a.parameters.map(p => [p.name, t(`param.type.${p.type}`), p.range ? `[${p.range.join(", ")}]` : (p.values ?? []).join(", "),
          p.default ?? "–", p.condition ?? "–"])) : help(t("project.no_params"))))),
  ];
}

function logsCard() {
  const logs = S.status?.logs ?? {};
  const names = Object.keys(logs).filter(n => logs[n]);
  if (!logChoice || !names.includes(logChoice)) logChoice = names.includes("paretolab.log") ? "paretolab.log" : names[0];
  const pre = h("pre", { class: "log", id: "log" }, logChoice ? logs[logChoice] : t("run.no_log"));
  const box = card(null, h("div", { class: "row spread" }, h("h2", {}, t("run.log_title")),
    names.length ? h("select", { "aria-label": t("run.log_file"), onchange: e => { logChoice = e.target.value; e.target.blur(); renderRun(true); } },
      names.map(n => h("option", { value: n, selected: n === logChoice }, n))) : null), help(t("run.log_help")), pre);
  return box;
}

function detailsView() {
  const out = S.status?.output_dir;
  return [card(t("run.setup_in_use"), setupSummary()),
    card(t("run.folders"), pathLine(t("run.folder_setup"), S.setupInfo?.path, "setup"),
      pathLine(t("run.folder_output"), out, out ? "output" : null),
      pathLine(t("run.folder_analysis"), out ? `${out}${out.includes("\\") ? "\\" : "/"}analysis` : null, out ? "analysis" : null)),
    logsCard(), ...projectCards()];
}

// ------------------------------------------------------------------ the step

let runKey = "";
export function renderRun(force = false) {
  const root = $("#step-run");
  if (!root || !S.status) return;
  // redraw only when something shown changed (the logs count only on the details tab)
  const { now, logs, ...shown } = S.status;
  const key = JSON.stringify([view, shown, view === "details" ? logs : null, logChoice, retryFailed,
    document.documentElement.lang, S.check?.ok, S.setupInfo?.exists]);
  if (!force && key === runKey) return;
  runKey = key;
  const old = $("#log");
  const atEnd = !old || old.scrollTop + old.clientHeight >= old.scrollHeight - 20;
  const scroll = window.scrollY;
  const content = view === "instances" ? instancesView() : view === "details" ? detailsView() : progressView();
  fill(root, tabs([["progress", t("run.tab_progress")], ["instances", cap(term("instances"))], ["details", t("run.tab_details")]],
    view, v => { view = v; store("paretolab.run.view", v); renderRun(true); }), h("div", { class: "panel" }, content));
  const st = S.status.state;
  moveScene(phase() === "done" ? 1 : st?.total ? st.finished / st.total : 0);
  const log = $("#log");
  if (log && atEnd) log.scrollTop = log.scrollHeight;
  window.scrollTo(0, scroll);
}
