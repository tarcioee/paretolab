"use strict";
// paretolab web interface. Every field, label and choice comes from the project manifest (GET /api/project);
// the setup is edited as a plain object (`draft`) and validated by the server with the same code as the CLI.

const $ = (sel, el = document) => el.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false)
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

async function api(path, body) {
  const options = body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { data = { error: `HTTP ${response.status}` }; }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

let toastTimer;
function toast(text, bad = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, bad ? 7000 : 3000);
}

const fmt = (x, digits = 4) => (x === null || x === undefined || Number.isNaN(x)) ? "-" :
  (typeof x === "number" ? (Number.isInteger(x) ? String(x) : x.toPrecision(digits).replace(/\.?0+$/, "")) : String(x));
const fmtP = p => p === null || p === undefined ? "-" : (p < 1e-4 ? p.toExponential(1) : p.toFixed(4));

function duration(s) {
  if (s === null || s === undefined) return "-";
  s = Math.round(s);
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}h${String(mm).padStart(2, "0")}m` : mm ? `${mm}m${String(ss).padStart(2, "0")}s` : `${ss}s`;
}
const when = iso => iso ? new Date(iso).toLocaleString() : "-";

// ------------------------------------------------------------------ nested values of the draft

function getp(obj, path) {
  return path.split(".").reduce((o, k) => (o === undefined || o === null ? undefined : o[k]), obj);
}
function setp(obj, path, value) {
  const keys = path.split(".");
  const parents = [obj];
  let o = obj;
  for (const k of keys.slice(0, -1)) {
    if (typeof o[k] !== "object" || o[k] === null || Array.isArray(o[k])) o[k] = {};
    o = o[k];
    parents.push(o);
  }
  const last = keys[keys.length - 1];
  if (value === undefined) delete o[last]; else o[last] = value;
  for (let i = keys.length - 1; i > 0; i--) {            // drop objects left empty
    if (Object.keys(parents[i]).length === 0) delete parents[i - 1][keys[i - 1]]; else break;
  }
}
const clone = x => JSON.parse(JSON.stringify(x));
const stable = x => Array.isArray(x) ? x.map(stable) : (x && typeof x === "object")
  ? Object.fromEntries(Object.keys(x).sort().map(k => [k, stable(x[k])])) : x;
const same = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

// ------------------------------------------------------------------ state

const S = { project: null, manifest: null, saved: null, draft: null, setupInfo: null, check: null,
  status: null, analysis: null, analysisStamp: null, indicator: null, tab: null, boundsDraft: {}, log: null };

// ------------------------------------------------------------------ tabs

function showTab(name) {
  S.tab = name;
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== `tab-${name}`;
  try { localStorage.setItem("paretolab.tab", name); } catch { /* private window */ }
  if (name === "results") loadAnalysis();
}

// ------------------------------------------------------------------ setup form

function field(label, input, hint) {
  return h("div", { class: "field" }, h("label", {}, label), input, hint ? h("div", { class: "hint" }, hint) : null);
}

function numberInput(path, { min, max, step = "any", placeholder, integer = false, rerender = false } = {}) {
  const value = getp(S.draft, path);
  return h("input", {
    type: "number", min, max, step: integer ? 1 : step, placeholder, value: value ?? "",
    oninput: e => {
      const t = e.target.value.trim();
      setp(S.draft, path, t === "" ? undefined : (integer ? parseInt(t, 10) : Number(t)));
      changed(rerender);
    },
  });
}

function textInput(path, placeholder) {
  return h("input", { type: "text", value: getp(S.draft, path) ?? "", placeholder,
    oninput: e => { setp(S.draft, path, e.target.value === "" ? undefined : e.target.value); changed(); } });
}

function checkbox(label, checked, onchange) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked, onchange: e => onchange(e.target.checked) }),
    label);
}

// A list of names stored as `undefined` when every name is chosen (the setup's default: "everything").
function choiceList(path, names, { describe, allIsDefault = true, defaultList = null, after } = {}) {
  const current = getp(S.draft, path);
  const chosen = new Set(current === undefined || current === null ? (defaultList ?? names) : current);
  const update = () => {
    const list = names.filter(n => chosen.has(n));
    const isDefault = allIsDefault ? list.length === names.length : same(list, defaultList);
    setp(S.draft, path, isDefault ? undefined : list);
    changed(true);
    if (after) after();
  };
  return h("div", {},
    names.map(n => checkbox(describe ? describe(n) : n, chosen.has(n), on => { on ? chosen.add(n) : chosen.delete(n); update(); })),
    h("button", { type: "button", class: "link small", onclick: () => { names.forEach(n => chosen.add(n)); update(); } }, "all"),
    h("button", { type: "button", class: "link small", onclick: () => { chosen.clear(); update(); } }, "none"));
}

function units() {
  return S.manifest.algorithms.flatMap(a => a.variants.map(v => `${a.name}/${v}`));
}

function chosenUnits() {
  const list = S.draft.algorithms;
  if (!list) return units();
  return list.flatMap(e => e.includes("/") ? [e] : S.manifest.algorithms.find(a => a.name === e)?.variants.map(v => `${e}/${v}`) ?? []);
}

function algorithmsSection() {
  const chosen = new Set(chosenUnits());
  const update = () => {
    const entries = [];
    for (const a of S.manifest.algorithms) {
      const picked = a.variants.filter(v => chosen.has(`${a.name}/${v}`));
      if (picked.length === a.variants.length) entries.push(a.name);
      else entries.push(...picked.map(v => `${a.name}/${v}`));
    }
    const all = S.manifest.algorithms.map(a => a.name);
    setp(S.draft, "algorithms", same(entries, all) ? undefined : entries);
    changed(true);
  };
  return S.manifest.algorithms.map(a => field(a.name, h("div", {},
    a.variants.map(v => checkbox(v, chosen.has(`${a.name}/${v}`), on => {
      on ? chosen.add(`${a.name}/${v}`) : chosen.delete(`${a.name}/${v}`); update();
    })))));
}

function seedsSection() {
  const seeds = S.draft.seeds;
  const isList = Array.isArray(seeds);
  const mode = h("select", { onchange: e => {
    S.draft.seeds = e.target.value === "list" ? (isList ? seeds : rangeOf(seeds)) : { count: isList ? seeds.length || 1 : 10 };
    changed(true);
  } }, h("option", { value: "range", selected: !isList }, "a range"), h("option", { value: "list", selected: isList }, "a list"));
  if (isList) {
    const input = h("input", { type: "text", value: seeds.join(", "), placeholder: "1, 2, 3",
      oninput: e => {
        const parts = e.target.value.split(/[\s,;]+/).filter(Boolean);
        const numbers = parts.map(Number);
        e.target.setCustomValidity(numbers.every(Number.isInteger) ? "" : "whole numbers only");
        if (numbers.every(Number.isInteger)) { S.draft.seeds = numbers; changed(); }
      } });
    return [field("Seeds", h("div", { class: "row" }, mode, input), "seeds separated by commas")];
  }
  return [field("Seeds", h("div", { class: "row" }, mode, "count", numberInput("seeds.count", { min: 1, integer: true }),
    "starting at", numberInput("seeds.start", { integer: true, placeholder: "1" })), "one run per seed, instance and algorithm variant")];
}

function rangeOf(seeds) {
  const start = seeds?.start ?? 1;
  return Array.from({ length: seeds?.count ?? 10 }, (_, i) => start + i);
}

function budgetFields(prefix) {
  return [
    field("Evaluations", numberInput(`${prefix}.max_evaluations`, { min: 1, integer: true, placeholder: "no limit" }),
      "passed to the program as {max_evaluations}"),
    field("Time limit of one run (s)", numberInput(`${prefix}.time_limit_s`, { min: 0, placeholder: "no limit" }),
      "passed as {time_limit_s}; the program should stop by itself"),
    field("Kill after extra (s)", numberInput(`${prefix}.kill_grace_s`, { min: 0, placeholder: "max(10 s, 10%)" }),
      "a run still alive after the limit plus this is killed"),
  ];
}

function paramInput(param, key, tuning) {
  const values = S.draft.parameters?.[key] ?? {};
  const has = Object.prototype.hasOwnProperty.call(values, param.name);
  const set = value => {
    const p = clone(S.draft.parameters ?? {});
    p[key] = { ...(p[key] ?? {}) };
    if (value === undefined) delete p[key][param.name]; else p[key][param.name] = value;
    if (Object.keys(p[key]).length === 0) delete p[key];
    S.draft.parameters = Object.keys(p).length ? p : undefined;
    if (S.draft.parameters === undefined) delete S.draft.parameters;
    changed();
  };
  const empty = key.includes("/") ? "(as all variants)" : tuning ? "(tuned)" :
    param.default !== null && param.default !== undefined ? `(default ${param.default})` : "(not passed)";
  if (param.type === "categorical" || param.type === "ordinal") {
    const index = has ? param.values.findIndex(v => v === values[param.name]) : -1;
    return h("select", { onchange: e => set(e.target.value === "" ? undefined : param.values[Number(e.target.value)]) },
      h("option", { value: "", selected: index < 0 }, empty),
      param.values.map((v, i) => h("option", { value: String(i), selected: i === index }, String(v))));
  }
  const integer = param.type === "integer";
  return h("input", { type: "number", min: param.range[0], max: param.range[1], step: integer ? 1 : "any",
    placeholder: empty, value: has ? values[param.name] : "",
    oninput: e => { const t = e.target.value.trim(); set(t === "" ? undefined : (integer ? parseInt(t, 10) : Number(t))); } });
}

function domain(p) {
  if (p.type === "real" || p.type === "integer") return `[${p.range[0]}, ${p.range[1]}]${p.log ? " log" : ""}`;
  return p.values.join(", ");
}

function parametersSection() {
  const tuning = !!S.draft.tuning?.enabled;
  const withParams = S.manifest.algorithms.filter(a => a.parameters.length);
  if (!withParams.length) return [h("p", { class: "muted" }, "The algorithms of this project have no parameters.")];
  return [h("p", { class: "hint" }, tuning
    ? "Empty cells are tuned. A value fixes the parameter: it is not tuned. A variant column wins over \"all variants\"."
    : "Empty cells use the manifest default. A variant column wins over \"all variants\"."),
  ...withParams.map(a => {
    const keys = [a.name, ...(a.variants.length > 1 ? a.variants.map(v => `${a.name}/${v}`) : [])];
    return h("div", { class: "scroll-x" }, h("h3", {}, a.name), h("table", { class: "param-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "parameter"), h("th", {}, "type"), h("th", {}, "domain"), h("th", {}, "default"),
        keys.map(k => h("th", {}, k === a.name ? "all variants" : k.split("/")[1])))),
      h("tbody", {}, a.parameters.map(p => h("tr", {},
        h("td", {}, h("strong", {}, p.name), p.condition ? h("div", { class: "hint" }, `if ${p.condition}`) : null),
        h("td", {}, p.type), h("td", {}, domain(p)), h("td", {}, p.default ?? "-"),
        keys.map(k => h("td", {}, paramInput(p, k, tuning))))))));
  })];
}

function experimentInstances() {
  return S.draft.instances ?? S.manifest.instances.map(i => i.name);
}

function boundsSection() {
  const objectives = S.manifest.objectives;
  const training = S.draft.tuning?.instances ?? experimentInstances();
  const bounds = S.draft.tuning?.bounds ?? {};
  for (const [inst, pairs] of Object.entries(bounds)) if (!S.boundsDraft[inst]) S.boundsDraft[inst] = clone(pairs);
  const store = inst => {
    const pairs = S.boundsDraft[inst];
    const complete = pairs && pairs.length === objectives.length && pairs.every(p => p.every(x => typeof x === "number" && !Number.isNaN(x)));
    const all = { ...(S.draft.tuning?.bounds ?? {}) };
    if (complete) all[inst] = pairs; else delete all[inst];
    setp(S.draft, "tuning.bounds", Object.keys(all).length ? all : undefined);
    changed();
  };
  const cell = (inst, o, side) => h("input", { type: "number", step: "any", class: "num", placeholder: side ? "max" : "min",
    value: S.boundsDraft[inst]?.[o]?.[side] ?? "",
    oninput: e => {
      const row = S.boundsDraft[inst] ??= objectives.map(() => [NaN, NaN]);
      row[o][side] = e.target.value === "" ? NaN : Number(e.target.value);
      store(inst);
    } });
  return field("Normalization bounds", h("div", { class: "scroll-x" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "instance"), objectives.map(o => h("th", {}, `${o.name} (${o.sense})`)))),
    h("tbody", {}, training.map(inst => h("tr", {}, h("td", {}, inst),
      objectives.map((o, k) => h("td", {}, cell(inst, k, 0), " ", cell(inst, k, 1)))))))),
    "fixed [min, max] per objective for the tuning cost (hypervolume); a row left incomplete is calibrated");
}

function tuningSection() {
  const t = S.draft.tuning ?? {};
  const out = [field("Tune before the runs", checkbox("enabled", !!t.enabled, on => {
    setp(S.draft, "tuning.enabled", on || undefined); changed(true);
  }), "with irace (needs R and the irace package; see paretolab doctor)")];
  if (!t.enabled) return out;
  const names = experimentInstances();
  out.push(
    field("Experiments per variant", numberInput("tuning.max_experiments", { min: 1, integer: true, placeholder: "1000" }),
      "irace's maxExperiments: runs it may spend on each algorithm variant"),
    field("Training instances", choiceList("tuning.instances", S.manifest.instances.map(i => i.name),
      { allIsDefault: false, defaultList: names }), "default: the experiment's instances"),
    field("Tuner seed", numberInput("tuning.seed", { integer: true, placeholder: "1" })),
    field("Own budget for tuning runs", checkbox("yes", !!t.budget, on => {
      setp(S.draft, "tuning.budget", on ? clone(S.draft.budget ?? { max_evaluations: 1000 }) : undefined); changed(true);
    }), "default: the experiment's budget"));
  if (t.budget) out.push(...budgetFields("tuning.budget"));
  if (S.project.multiobjective) {
    out.push(field("Calibration runs", numberInput("tuning.calibration_runs", { min: 1, integer: true, placeholder: "3" }),
      "runs of the default configuration per variant, to find the bounds not given below"));
    out.push(boundsSection());
  }
  return out;
}

function analysisSection() {
  const all = S.project.indicators;
  const custom = Array.isArray(S.draft.indicators);
  const labels = { hv: "hypervolume", igd_plus: "IGD+", igd: "IGD", epsilon_additive: "additive epsilon",
    best: "best value", gap: "gap to the optimum" };
  const out = [field("Indicators", h("div", {},
    checkbox("the defaults", !custom, on => {
      setp(S.draft, "indicators", on ? undefined : (S.check?.summary?.indicators ?? [all[0]])); changed(true);
    }),
    custom ? choiceList("indicators", all, { allIsDefault: false, defaultList: null, describe: n => labels[n] ?? n }) : null),
  S.project.multiobjective ? "default: hypervolume and IGD+" : "default: best value, and the gap when every instance has a known optimum")];
  if (S.project.multiobjective) {
    out.push(field("Reference point offset", numberInput("normalization.reference_offset", { min: 0, placeholder: "0.1" }),
      "after min-max normalization, the hypervolume reference point is 1 + offset in every objective"));
  }
  const tests = S.draft.statistics?.tests ?? S.project.statistical_tests;
  out.push(field("Statistical tests", h("div", {}, S.project.statistical_tests.map(name => checkbox(name.replace("_", "-"),
    tests.includes(name), on => {
      const list = S.project.statistical_tests.filter(n => n === name ? on : tests.includes(n));
      setp(S.draft, "statistics.tests", same(list, S.project.statistical_tests) ? undefined : list); changed(true);
    })))),
  field("Significance level", numberInput("statistics.alpha", { min: 0, max: 1, placeholder: "0.05" })),
  field("Blocks", selectInput("statistics.blocks", [["instances", "instances (runs aggregated)"], ["runs", "(instance, seed) pairs"]], "instances")),
  field("Aggregation", selectInput("statistics.aggregation", [["median", "median"], ["mean", "mean"]], "median"),
    "how the runs of an instance are aggregated when blocks are instances"));
  return out;
}

function selectInput(path, options, fallback) {
  const value = getp(S.draft, path) ?? fallback;
  return h("select", { onchange: e => { setp(S.draft, path, e.target.value === fallback ? undefined : e.target.value); changed(); } },
    options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
}

function renderSetupForm() {
  const m = S.manifest;
  const describeInstance = name => {
    const i = m.instances.find(x => x.name === name);
    return i.optimum !== null && i.optimum !== undefined ? `${name} (optimum ${i.optimum})` : name;
  };
  const sections = [
    ["Experiment", [
      field("Project", h("span", {}, S.draft.project ?? "project.yaml"), "the manifest; edit it in its own file"),
      field("Output folder", textInput("output_dir", "results"), "relative to the setup file"),
      field("Runs at the same time", numberInput("parallel_jobs", { min: 0, integer: true, placeholder: "0 = one per CPU core" })),
      field("Minimum free disk (GB)", numberInput("min_free_disk_gb", { min: 0, placeholder: "1" }),
        "the experiment pauses when the disk has less free space"),
    ]],
    ["Instances", [field("Instances", choiceList("instances", m.instances.map(i => i.name), { describe: describeInstance }))]],
    ["Algorithm variants", algorithmsSection()],
    ["Seeds and budget", [...seedsSection(), ...budgetFields("budget")]],
    ["Parameters", parametersSection()],
    ["Tuning", tuningSection()],
    ["Analysis", analysisSection()],
  ];
  const form = $("#setup-form");
  const scroll = window.scrollY;
  form.replaceChildren(...sections.map(([title, content]) => h("div", { class: "card" }, h("h2", {}, title), content)));
  window.scrollTo(0, scroll);
}

let checkTimer;
function changed(rerender = false) {
  if (rerender) renderSetupForm();
  updateDirty();
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 250);
}

function updateDirty() {
  const dirty = !same(S.draft, S.saved);
  $("#save-note").replaceChildren(dirty ? h("span", { class: "dirty" }, "Unsaved changes. ") : "",
    S.setupInfo?.exists ? `File: ${S.setupInfo.path}` : `New file: ${S.setupInfo?.path ?? ""}`);
  $("#btn-discard").disabled = !dirty;
}

async function runCheck() {
  try {
    S.check = await api("/api/check", { setup: S.draft });
  } catch (e) { S.check = { ok: false, errors: [e.message], yaml: "" }; }
  renderCheck();
}

function renderCheck() {
  const c = S.check;
  const busy = !!S.status?.alive;
  $("#check-status").replaceChildren(c.ok ? h("span", { class: "badge ok" }, "valid") : h("span", { class: "badge bad" }, "not valid"));
  const problem = S.setupInfo?.problem ? [`${S.setupInfo.path} could not be read; the form starts from defaults:
${S.setupInfo.problem}`] : [];
  $("#check-errors").replaceChildren(...[...problem, ...(c.errors || [])].map(e => h("li", {}, e)));
  const s = c.summary;
  $("#check-summary").replaceChildren(s ? h("div", {},
    h("p", {}, h("strong", {}, `${s.runs} runs`), ` = ${s.instances.length} instances × ${s.units.length} variants × ${s.seeds} seeds`),
    s.runs === 0 ? h("p", { class: "errors" }, "nothing to run: choose instances and variants") : null,
    h("p", { class: "small muted" }, `indicators: ${s.indicators.join(", ")}`),
    h("p", { class: "small muted" }, `output: ${s.output_dir}`),
    s.tuning ? h("div", { class: "small" }, h("strong", {}, "Tuning"), ` on ${s.tuning_instances.join(", ")}`,
      h("ul", {}, s.tuning.map(u => h("li", {}, `${u.unit}: `, u.tuned.length ? u.tuned.join(", ") : h("em", {}, "nothing to tune (skipped)"))))) : null)
    : "");
  $("#check-yaml").textContent = c.yaml || "";
  $("#btn-save").disabled = !c.ok || busy;
  $("#btn-save-run").disabled = !c.ok || busy || !s?.runs;
  $("#btn-save").title = busy ? "pause the experiment to change its setup" : "";
}

async function save(andRun) {
  try {
    const info = await api("/api/save", { setup: S.draft });
    loadSetupInfo(info);
    toast("setup saved");
    if (andRun) { await startRun(); showTab("run"); }
  } catch (e) { toast(e.message, true); }
}

function loadSetupInfo(info) {
  S.setupInfo = info;
  S.saved = clone(info.data);
  S.draft = clone(info.data);
  S.boundsDraft = {};
  $("#setup-name").textContent = info.path;
  renderSetupForm();
  updateDirty();
  if (info.check) { S.check = info.check; renderCheck(); } else runCheck();
}

// ------------------------------------------------------------------ run tab

function phaseOf(st) {
  const state = st?.state;
  if (!state) return { label: "not started", cls: "", text: "Not started" };
  const p = state.phase;
  if ((p === "running" || p === "tuning") && !st.alive)
    return { label: "interrupted", cls: "bad", text: "Interrupted: the process is gone. Resume to continue." };
  return { running: { label: "running", cls: "info", text: "Running" }, tuning: { label: "tuning", cls: "info", text: "Tuning" },
    paused: { label: "paused", cls: "warn", text: "Paused" }, failed: { label: "failed", cls: "bad", text: "Failed" },
    done: { label: "done", cls: "ok", text: "All runs finished" } }[p] ?? { label: p, cls: "", text: p };
}

function renderStatus() {
  const st = S.status;
  const state = st.state;
  const phase = phaseOf(st);
  const analyzing = !!st.children?.analyze?.running;
  const badge = $("#phase-badge");
  badge.textContent = analyzing && !st.alive ? "analysing" : phase.label;
  badge.className = "badge " + (analyzing && !st.alive ? "info" : phase.cls);

  $("#run-title").textContent = phase.text + (st.pause_requested && st.alive ? " (pause requested…)" : "");
  const message = state?.message && state.message.toLowerCase() !== phase.text.toLowerCase() ? state.message : "";
  $("#run-message").textContent = state ? message : "Save a setup and start it. Finished runs are never repeated.";
  const total = state?.total ?? 0, finished = state?.finished ?? 0;
  $("#run-bar").style.width = total ? `${(100 * finished) / total}%` : "0";
  const facts = state ? [
    ["finished", `${finished} of ${total}`], ["failed", state.failed ?? 0], ["running now", (state.running ?? []).length],
    ["left (estimate)", st.alive && state.phase === "running" ? duration(state.eta_s) : "-"],
    ["mean run", state.mean_run_s ? duration(state.mean_run_s) : "-"], ["at the same time", state.jobs ?? "-"],
    ["started", when(state.started_at)], ["updated", when(state.updated_at)],
  ] : [];
  $("#run-facts").replaceChildren(...facts.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, String(v)))));

  const run = $("#btn-run");
  run.textContent = st.alive ? "Running…" : !state ? "Start" : state.phase === "done" ? "Run again" : "Resume";
  run.title = state?.phase === "done" ? "runs only what is missing (or failed, if chosen), then analyses" : "";
  run.disabled = st.alive || analyzing || !S.setupInfo?.exists;
  $("#btn-pause").disabled = !st.alive || st.pause_requested;
  $("#btn-analyze").disabled = st.alive || analyzing;
  $("#btn-analyze").textContent = analyzing ? "Analysing…" : "Analyse now";
  if (S.check) renderCheck();

  const tuning = state?.tuning;
  $("#tuning-card").hidden = !tuning || !Object.keys(tuning).length;
  if (tuning) {
    $("#tuning-table").replaceChildren(h("table", {}, h("thead", {}, h("tr", {}, ["variant", "status", "tuned values", "time"].map(t => h("th", {}, t)))),
      h("tbody", {}, Object.entries(tuning).map(([key, u]) => h("tr", {}, h("td", {}, key),
        h("td", {}, h("span", { class: "badge " + ({ done: "ok", running: "info", failed: "bad", paused: "warn" }[u.status] ?? "") }, u.status)),
        h("td", { class: "small" }, u.parameters ? Object.entries(u.parameters).map(([k, v]) => `${k}=${fmt(v)}`).join("  ") : (u.message ?? "")),
        h("td", {}, u.elapsed_s ? duration(u.elapsed_s) : "-"))))));
  }

  const g = st.grid;
  if (g) {
    $("#grid").replaceChildren(h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", {}, "instance"), g.units.map(u => h("th", { class: "cell" }, u)))),
      h("tbody", {}, g.instances.map((inst, i) => h("tr", {}, h("td", {}, inst), g.cells[i].map(c => h("td", {
        class: "cell " + (c.done === c.total ? "full" : c.done ? "part" : "") + (c.failed ? " failed" : ""),
        title: c.failed ? `${c.failed} failed` : "" }, `${c.done}/${c.total}`)))))));
  } else $("#grid").replaceChildren(h("p", { class: "muted" }, "no valid saved setup"));
  const running = state?.running ?? [];
  $("#running-list").replaceChildren(running.length ? h("p", {}, h("strong", {}, "Running now: "), running.join(", ")) : "");

  const choice = $("#log-choice");
  const names = Object.keys(st.logs).filter(n => st.logs[n]);
  if (!S.log || !names.includes(S.log)) S.log = names.includes("paretolab.log") ? "paretolab.log" : names[0];
  if (choice.options.length !== names.length || [...choice.options].some((o, i) => o.value !== names[i]))
    choice.replaceChildren(...names.map(n => h("option", { value: n, selected: n === S.log }, n)));
  const pre = $("#log");
  const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = S.log ? st.logs[S.log] : "(no log yet)";
  if (atEnd) pre.scrollTop = pre.scrollHeight;
}

let lastAnalyzeRunning = false;
let pollTimer;
async function pollStatus() {
  clearTimeout(pollTimer);
  try {
    S.status = await api("/api/status");
    renderStatus();
    const analyzing = !!S.status.children?.analyze?.running;
    if (lastAnalyzeRunning && !analyzing) {
      const code = S.status.children.analyze.exit_code;
      toast(code === 0 ? "analysis finished" : `analysis failed (exit code ${code}); see ui_analyze.log`, code !== 0);
      loadAnalysis(true);
    }
    lastAnalyzeRunning = analyzing;
    if (S.tab === "results" && S.status.state?.phase === "done") loadAnalysis();
  } catch (e) {
    $("#phase-badge").textContent = "interface stopped?";
    $("#phase-badge").className = "badge bad";
  }
  pollTimer = setTimeout(pollStatus, S.status?.alive || S.status?.children?.analyze?.running ? 1500 : 4000);
}

async function startRun() {
  try {
    await api("/api/run", { retry_failed: $("#opt-retry").checked });
    toast("experiment started");
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollStatus, 300);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ results tab

async function loadAnalysis(force = false) {
  try {
    const a = await api("/api/analysis");
    if (!force && a.updated_at === S.analysisStamp && S.analysis) return;
    S.analysis = a;
    S.analysisStamp = a.updated_at;
    renderAnalysis();
  } catch (e) {
    $("#an-body").replaceChildren(h("div", { class: "card error" }, e.message));
  }
}

function figure(base, name) {
  const url = `${base}/${encodeURIComponent(name)}?t=${S.analysisStamp}`;
  return h("figure", {}, h("a", { href: url, target: "_blank" }, h("img", { src: url, alt: name, loading: "lazy" })),
    h("figcaption", {}, name));
}

function renderAnalysis() {
  const a = S.analysis;
  if (!a.available) {
    $("#an-info").textContent = "No analysis yet. It runs by itself when every run is finished, or press \"Analyse now\" for the runs finished so far.";
    $("#an-warnings-box").hidden = true;
    $("#an-body").replaceChildren();
    return;
  }
  const s = a.summary;
  $("#an-info").textContent = `${s.runs_analysed} of ${s.runs_planned} planned runs, analysed ${new Date(a.updated_at * 1000).toLocaleString()}`;
  const warnings = s.warnings ?? [];
  $("#an-warnings-box").hidden = !warnings.length;
  $("#an-warnings-title").textContent = `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
  $("#an-warnings").replaceChildren(...warnings.map(w => h("li", {}, w)));
  if (!a.indicators.find(i => i.name === S.indicator)) S.indicator = a.indicators[0]?.name;
  const ind = a.indicators.find(i => i.name === S.indicator);
  const pills = h("div", { class: "pills" }, a.indicators.map(i => h("button", { type: "button", "aria-pressed": String(i.name === S.indicator),
    onclick: () => { S.indicator = i.name; renderAnalysis(); } }, i.label)));
  const body = [h("div", { class: "card" }, pills, ind ? indicatorView(ind, a.figure_base) : null)];
  if (a.figures.length) body.push(h("div", { class: "card" }, h("h2", {}, "Fronts and convergence"),
    h("div", { class: "figures" }, a.figures.map(f => figure(a.figure_base, f)))));
  if (a.per_run) body.push(h("p", { class: "small" }, h("a", { href: a.per_run }, "indicators of every run (CSV)")));
  $("#an-body").replaceChildren(...body);
}

function indicatorView(ind, base) {
  const out = [h("h2", {}, ind.label, h("span", { class: "muted small" }, ind.higher_is_better ? "  higher is better" : "  lower is better"))];
  if (ind.table) {
    out.push(h("p", { class: "small muted" }, "mean (standard deviation) per instance; best in bold"),
      h("div", { class: "scroll-x" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "instance"), ind.table.units.map(u => h("th", { class: "num" }, u)))),
        h("tbody", {}, ind.table.rows.map(r => h("tr", {}, h("td", {}, r.instance),
          r.cells.map(c => h("td", { class: "num" + (c.best ? " best" : "") }, c.text))))))));
  }
  const files = Object.entries(ind.files);
  if (files.length) out.push(h("p", { class: "small" }, "files: ", files.map(([k, url]) => [h("a", { href: url, target: "_blank" }, k), " "])));
  const st = ind.statistics;
  if (st) out.push(statisticsView(st));
  if (ind.figures.length) out.push(h("h3", {}, "Figures"), h("div", { class: "figures" }, ind.figures.map(f => figure(base, f))));
  return h("div", {}, out);
}

function statisticsView(st) {
  const out = [h("h3", {}, "Statistical comparison"),
    h("p", { class: "small muted" }, `${st.n_blocks} blocks (${st.blocks}${st.aggregation ? `, ${st.aggregation} of the runs` : ""}), α = ${st.alpha}`)];
  if (st.mean_ranks) {
    const ranks = Object.entries(st.mean_ranks);
    const max = Math.max(...ranks.map(([, r]) => r));
    out.push(h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "variant"), h("th", { class: "num" }, "mean rank"), h("th", {}, ""))),
      h("tbody", {}, ranks.map(([u, r]) => h("tr", {}, h("td", {}, u), h("td", { class: "num" }, r.toFixed(2)),
        h("td", {}, h("span", { class: "bar", style: `width:${Math.max(4, (120 * r) / max)}px` })))))));
  }
  if (st.friedman) {
    const f = st.friedman;
    out.push(h("p", {}, "Friedman: χ² = ", fmt(f.chi2), `, df = ${f.df}, p = ${fmtP(f.p_value)} `,
      h("span", { class: "badge " + (f.reject_h0 ? "ok" : "") }, f.reject_h0 ? "the variants differ" : "no significant difference")));
  }
  if (st.nemenyi) {
    const units = Object.keys(st.nemenyi.p_values);
    out.push(h("details", {}, h("summary", {}, `Nemenyi: critical difference ${fmt(st.nemenyi.critical_difference)} (p-values)`),
      h("div", { class: "scroll-x" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), units.map(u => h("th", { class: "num" }, u)))),
        h("tbody", {}, units.map(a => h("tr", {}, h("td", {}, a), units.map(b => {
          const p = st.nemenyi.p_values[a][b];
          return h("td", { class: "num" + (a !== b && p < st.alpha ? " best" : "") }, a === b ? "" : fmtP(p));
        }))))))));
  }
  if (st.wilcoxon_holm) {
    out.push(h("details", { open: st.wilcoxon_holm.length <= 15 }, h("summary", {}, "Wilcoxon signed-rank, Holm correction (significant pairs highlighted)"),
      h("div", { class: "scroll-x" }, h("table", {}, h("thead", {}, h("tr", {}, ["a", "b", "median a − b", "p", "p (Holm)", "better"].map(t => h("th", {}, t)))),
        h("tbody", {}, st.wilcoxon_holm.map(p => h("tr", { class: p.significant ? "sig" : "" }, h("td", {}, p.a), h("td", {}, p.b),
          h("td", { class: "num" }, fmt(p.median_difference)), h("td", { class: "num" }, fmtP(p.p_value)),
          h("td", { class: "num" }, fmtP(p.p_holm)), h("td", {}, p.significant ? p.better ?? "-" : "-"))))))));
  }
  if (st.warnings?.length) out.push(h("ul", { class: "small muted" }, st.warnings.map(w => h("li", {}, w))));
  return h("div", {}, out);
}

// ------------------------------------------------------------------ project tab

function renderProject() {
  const m = S.manifest;
  const command = Array.isArray(m.command) ? m.command.join(" ") : m.command;
  $("#project-body").replaceChildren(
    h("div", { class: "card" }, h("h2", {}, m.name), m.description ? h("p", {}, m.description) : null,
      h("p", { class: "small muted" }, S.project.path),
      h("p", {}, S.project.multiobjective ? `multi-objective (${m.objectives.length} objectives)` : "single-objective"),
      h("h3", {}, "Command of one run"), h("pre", { class: "code" }, command),
      h("p", { class: "small muted" }, `parameters passed as ${m.param_format}` + (m.executable ? `; executable: ${m.executable}` : ""))),
    h("div", { class: "card" }, h("h2", {}, "Objectives"), h("table", {}, h("thead", {}, h("tr", {}, ["name", "sense", "unit"].map(t => h("th", {}, t)))),
      h("tbody", {}, m.objectives.map(o => h("tr", {}, h("td", {}, o.name), h("td", {}, o.sense === "min" ? "minimize" : "maximize"), h("td", {}, o.unit ?? "-")))))),
    h("div", { class: "card" }, h("h2", {}, `Instances (${m.instances.length})`), h("div", { class: "scroll-x" }, h("table", {},
      h("thead", {}, h("tr", {}, ["name", "path", "known optimum"].map(t => h("th", {}, t)))),
      h("tbody", {}, m.instances.map(i => h("tr", {}, h("td", {}, i.name), h("td", { class: "small" }, i.path ?? "-"), h("td", {}, i.optimum ?? "-"))))))),
    h("div", { class: "card" }, h("h2", {}, "Algorithms"), m.algorithms.map(a => h("div", {}, h("h3", {}, a.name, h("span", { class: "muted small" }, `  variants: ${a.variants.join(", ")}`)),
      a.parameters.length ? h("div", { class: "scroll-x" }, h("table", {}, h("thead", {}, h("tr", {}, ["parameter", "type", "domain", "default", "condition"].map(t => h("th", {}, t)))),
        h("tbody", {}, a.parameters.map(p => h("tr", {}, h("td", {}, p.name), h("td", {}, p.type), h("td", {}, domain(p)), h("td", {}, p.default ?? "-"), h("td", {}, p.condition ?? "-"))))))
        : h("p", { class: "muted small" }, "no parameters")))));
}

// ------------------------------------------------------------------ start

async function openFolder(which) {
  try { await api("/api/open", { folder: which }); } catch (e) { toast(e.message, true); }
}

async function main() {
  for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));
  for (const b of document.querySelectorAll("[data-open]")) b.addEventListener("click", () => openFolder(b.dataset.open));
  $("#btn-save").addEventListener("click", () => save(false));
  $("#btn-save-run").addEventListener("click", () => save(true));
  $("#btn-discard").addEventListener("click", () => { S.draft = clone(S.saved); S.boundsDraft = {}; changed(true); });
  $("#btn-run").addEventListener("click", startRun);
  $("#btn-pause").addEventListener("click", async () => {
    try { await api("/api/pause", {}); toast("pause requested: the runs in progress stop and are redone on resume"); pollStatus(); }
    catch (e) { toast(e.message, true); }
  });
  $("#btn-analyze").addEventListener("click", async () => {
    try { await api("/api/analyze", { no_figures: $("#opt-nofig").checked }); toast("analysis started"); lastAnalyzeRunning = true; pollStatus(); }
    catch (e) { toast(e.message, true); }
  });
  $("#log-choice").addEventListener("change", e => { S.log = e.target.value; renderStatus(); });
  window.addEventListener("beforeunload", e => { if (S.draft && !same(S.draft, S.saved)) e.preventDefault(); });

  try {
    S.project = await api("/api/project");
  } catch (e) {
    $("#fatal").hidden = false;
    $("#fatal").textContent = `The project manifest could not be loaded:\n${e.message}`;
    $("#project-name").textContent = "no project";
    return;
  }
  S.manifest = S.project.manifest;
  $("#project-name").textContent = S.manifest.name;
  document.title = `${S.manifest.name} · paretolab`;
  renderProject();
  loadSetupInfo(await api("/api/setup"));
  let tab = null;
  try { tab = localStorage.getItem("paretolab.tab"); } catch { /* private window */ }
  await pollStatus();
  showTab(tab ?? (S.status?.state ? "run" : "setup"));
}

main();
