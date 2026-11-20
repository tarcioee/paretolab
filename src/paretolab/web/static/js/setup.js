// Step 1: the experiment setup, as a form built from the project manifest. The draft is validated by the server
// with the same code as `paretolab validate`; nothing runs until "Run" is confirmed.
import { $, api, clone, confirmDialog, fill, getp, h, same, setp, toast } from "./dom.js";
import { cap, count, duration, errorText, msg, num, t, term, text } from "./i18n.js";
import { allUnits, algorithmOf, analyzing, emit, instanceOf, S, unitLabel } from "./state.js";
import { alertBox, badge, chip, field, help, kv, switchInput } from "./ui.js";

let checkTimer;
let boundsDraft = {};
const timeUnits = {};        // path -> "s" | "min" | "h", the unit chosen for a time field
const UNIT = { s: 1, min: 60, h: 3600 };

export function loadSetupInfo(info) {
  S.setupInfo = info;
  S.saved = clone(info.data);
  S.draft = clone(info.data);
  boundsDraft = {};
  renderSetup();
  if (info.check) { S.check = info.check; renderBar(); } else runCheck();
}

const busy = () => !!S.status?.alive || analyzing();
const dirty = () => !same(S.draft, S.saved);

function changed(rerender = false) {
  if (rerender) renderSetup(); else renderBar();
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 250);
}

async function runCheck() {
  try {
    S.check = await api("/api/check", { setup: S.draft });
  } catch (e) { S.check = { ok: false, errors: [errorText(e)], issues: [], yaml: "" }; }
  renderBar();
  const yaml = $("#setup-yaml");
  if (yaml) yaml.textContent = S.check.yaml || "";
}

// ------------------------------------------------------------------ inputs bound to the draft

function numberInput(path, { min, max, integer = false, placeholder, rerender = false, scale = 1, cls = "" } = {}) {
  const value = getp(S.draft, path);
  return h("input", {
    type: "number", min, max, step: integer && scale === 1 ? 1 : "any", placeholder, class: cls,
    value: value === undefined || value === null ? "" : +(value / scale).toPrecision(12),
    oninput: e => {
      const raw = e.target.value.trim();
      const v = raw === "" ? undefined : Number(raw) * scale;
      setp(S.draft, path, v === undefined || Number.isNaN(v) ? undefined : (integer ? Math.round(v) : v));
      changed(rerender);
    },
  });
}

function textInput(path, placeholder, cls = "") {
  return h("input", { type: "text", class: cls, spellcheck: false, value: getp(S.draft, path) ?? "", placeholder,
    oninput: e => { setp(S.draft, path, e.target.value === "" ? undefined : e.target.value); changed(); } });
}

/** A duration in seconds, typed in seconds, minutes or hours. */
function timeInput(path, placeholder) {
  const value = getp(S.draft, path);
  timeUnits[path] ??= value >= 3600 ? "h" : value >= 120 ? "min" : "s";
  const unit = timeUnits[path];
  return h("div", { class: "with-unit" }, numberInput(path, { min: 0, placeholder, scale: UNIT[unit] }),
    h("select", { "aria-label": t("setup.time_unit"), onchange: e => { timeUnits[path] = e.target.value; renderSetup(); } },
      Object.keys(UNIT).map(u => h("option", { value: u, selected: u === unit }, t(`unit.${u}`)))));
}

function selectInput(path, options, fallback) {
  const value = getp(S.draft, path) ?? fallback;
  return h("select", { onchange: e => { setp(S.draft, path, e.target.value === fallback ? undefined : e.target.value); changed(); } },
    options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
}

/** Chips for a list of names stored as undefined when the default (by default: all of them) is chosen. */
function chipList(path, names, { label = n => n, title, defaultList = null, after } = {}) {
  const current = getp(S.draft, path);
  const chosen = new Set(current === undefined || current === null ? (defaultList ?? names) : current);
  const update = () => {
    const list = names.filter(n => chosen.has(n));
    setp(S.draft, path, same(list, defaultList ?? names) ? undefined : list);
    after?.();
    changed(true);
  };
  return h("div", {},
    h("div", { class: "group-tools" },
      h("button", { type: "button", class: "link", onclick: () => { names.forEach(n => chosen.add(n)); update(); } }, t("action.all")),
      h("button", { type: "button", class: "link", onclick: () => { chosen.clear(); update(); } }, t("action.none"))),
    h("div", { class: "chips" }, names.map(n => chip(label(n), chosen.has(n),
      on => { on ? chosen.add(n) : chosen.delete(n); update(); }, { title: title?.(n) }))));
}

// ------------------------------------------------------------------ sections

const experimentInstances = () => S.draft.instances ?? S.manifest.instances.map(i => i.name);

function chosenUnits() {
  const list = S.draft.algorithms;
  if (!list) return allUnits();
  return list.flatMap(e => (e.includes("/") ? [e] : algorithmOf(e)?.variants.map(v => `${e}/${v}`) ?? []));
}

function storeUnits(chosen) {
  const entries = [];
  for (const a of S.manifest.algorithms) {
    const picked = a.variants.filter(v => chosen.has(`${a.name}/${v}`));
    if (picked.length === a.variants.length) entries.push(a.name);
    else entries.push(...picked.map(v => `${a.name}/${v}`));
  }
  setp(S.draft, "algorithms", same(entries, S.manifest.algorithms.map(a => a.name)) ? undefined : entries);
  changed(true);
}

const algorithmTitle = a => text(a.description) || undefined;
const variantTitle = (a, v) => text(a.variant_descriptions?.[v]) || undefined;

/** Algorithms × variants: a matrix when every algorithm has the same variants, otherwise one row each. */
function variantsBlock() {
  const algorithms = S.manifest.algorithms;
  const chosen = new Set(chosenUnits());
  const toggle = (units, on) => { units.forEach(u => (on ? chosen.add(u) : chosen.delete(u))); storeUnits(chosen); };
  const shared = algorithms.length > 1 && algorithms[0].variants.length > 1 &&
    algorithms.every(a => same(a.variants, algorithms[0].variants));
  const tools = h("div", { class: "group-tools" },
    h("button", { type: "button", class: "link", onclick: () => toggle(allUnits(), true) }, t("action.all")),
    h("button", { type: "button", class: "link", onclick: () => toggle(allUnits(), false) }, t("action.none")));
  if (shared) {
    const variants = algorithms[0].variants;
    const all = units => units.every(u => chosen.has(u));
    return h("div", {}, tools, h("div", { class: "scroll-x" }, h("table", { class: "matrix" },
      h("thead", {}, h("tr", {}, h("th", {}, `${cap(term("algorithm"))} \\ ${term("variant")}`),
        variants.map(v => {
          const units = algorithms.map(a => `${a.name}/${v}`);
          return h("th", {}, chip(v, all(units), on => toggle(units, on), { title: variantTitle(algorithms[0], v) }));
        }))),
      h("tbody", {}, algorithms.map(a => {
        const units = a.variants.map(v => `${a.name}/${v}`);
        return h("tr", {}, h("th", {}, chip(a.name, all(units), on => toggle(units, on), { title: algorithmTitle(a) })),
          units.map(u => h("td", {}, h("label", { class: "cell-check" }, h("input", { type: "checkbox",
            checked: chosen.has(u), "aria-label": unitLabel(u), onchange: e => toggle([u], e.target.checked) })))));
      })))), help(t("setup.matrix_help")));
  }
  if (algorithms.every(a => a.variants.length === 1)) {
    return h("div", {}, tools, h("div", { class: "chips" }, algorithms.map(a => {
      const u = `${a.name}/${a.variants[0]}`;
      return chip(unitLabel(u), chosen.has(u), on => toggle([u], on), { title: algorithmTitle(a) });
    })));
  }
  return h("div", {}, tools, algorithms.map(a => {
    if (a.variants.length === 1) {
      const u = `${a.name}/${a.variants[0]}`;
      return h("div", { class: "alg-row" }, chip(unitLabel(u), chosen.has(u), on => toggle([u], on),
        { title: algorithmTitle(a) }), a.description ? h("span", { class: "help inline" }, text(a.description)) : null);
    }
    return h("div", { class: "alg-row" }, h("strong", { title: algorithmTitle(a) }, a.name),
      h("div", { class: "chips" }, a.variants.map(v => chip(v, chosen.has(`${a.name}/${v}`),
        on => toggle([`${a.name}/${v}`], on), { title: variantTitle(a, v) }))));
  }));
}

function tunerNote() {
  const tuner = S.meta?.tuner;
  if (!tuner || tuner.checking) return h("p", { class: "help" }, t("setup.tuner_checking"));
  if (tuner.ok) return h("p", { class: "help" }, t("setup.tuner_ok", { version: tuner.irace }));
  return alertBox(`${t("setup.tuner_missing")} ${tuner.help ?? ""}`, "warn");
}

function whatToRun() {
  const tuning = !!S.draft.tuning?.enabled;
  const describeInstance = name => {
    const i = instanceOf(name);
    return i?.optimum !== null && i?.optimum !== undefined ? `${name} (${t("setup.optimum", { value: num(i.optimum) })})` : name;
  };
  return h("div", { class: "card" }, h("h2", {}, t("setup.what_to_run")),
    h("div", { class: "switch-row" },
      switchInput(t("setup.tuning_switch"), tuning, on => { setp(S.draft, "tuning.enabled", on || undefined); changed(true); }),
      help(tuning ? t("setup.tuning_on_help") : t("setup.tuning_off_help")), tuning ? tunerNote() : null),
    h("div", { class: "group" }, h("h3", {}, t("setup.variants_title")), variantsBlock()),
    h("div", { class: "group" }, h("h3", {}, cap(term("instances"))),
      chipList("instances", S.manifest.instances.map(i => i.name), { label: describeInstance,
        title: n => text(instanceOf(n)?.description) || undefined })));
}

function seedsInput() {
  const seeds = S.draft.seeds;
  const isList = Array.isArray(seeds);
  const mode = h("select", { "aria-label": t("setup.seeds_mode"), onchange: e => {
    S.draft.seeds = e.target.value === "list"
      ? Array.from({ length: seeds?.count ?? 10 }, (_, i) => (seeds?.start ?? 1) + i)
      : { count: isList ? seeds.length || 1 : 10 };
    changed(true);
  } }, h("option", { value: "range", selected: !isList }, t("setup.seeds_range")),
  h("option", { value: "list", selected: isList }, t("setup.seeds_list")));
  if (isList) {
    return h("div", { class: "row" }, mode, h("input", { type: "text", value: seeds.join(", "), placeholder: "1, 2, 3",
      oninput: e => {
        const numbers = e.target.value.split(/[\s,;]+/).filter(Boolean).map(Number);
        e.target.setCustomValidity(numbers.every(Number.isInteger) ? "" : t("setup.whole_numbers"));
        if (numbers.every(Number.isInteger)) { S.draft.seeds = numbers; changed(); }
      } }));
  }
  return h("div", { class: "row" }, mode, h("span", {}, t("setup.seeds_count")),
    numberInput("seeds.count", { min: 1, integer: true, cls: "short" }), h("span", {}, t("setup.seeds_start")),
    numberInput("seeds.start", { integer: true, placeholder: "1", cls: "short" }));
}

function sizeCard() {
  return h("div", { class: "card" }, h("h2", {}, t("setup.size")), h("div", { class: "grid-fields" },
    field(t("setup.evaluations"), numberInput("budget.max_evaluations", { min: 1, integer: true, placeholder: t("setup.no_limit") }),
      t("setup.evaluations_help")),
    field(t("setup.time_limit"), timeInput("budget.time_limit_s", t("setup.no_limit")), t("setup.time_limit_help")),
    field(cap(term("seeds")), seedsInput(), t("setup.seeds_help"), { wide: true })));
}

function resourcesCard() {
  const jobs = S.draft.parallel_jobs;
  const parallel = jobs !== 1;
  const cpus = S.meta?.cpu_count ?? 1;
  return h("div", { class: "card" }, h("h2", {}, t("setup.resources")),
    h("div", { class: "switch-row" }, switchInput(t("setup.parallel"), parallel, on => {
      setp(S.draft, "parallel_jobs", on ? undefined : 1); changed(true);
    }), help(t("setup.parallel_help", { n: cpus }))),
    h("div", { class: "grid-fields" },
      parallel ? field(t("setup.jobs"), numberInput("parallel_jobs", { min: 0, integer: true, placeholder: t("setup.jobs_auto") }),
        t("setup.jobs_help", { n: cpus })) : null,
      field(t("setup.kill_grace"), timeInput("budget.kill_grace_s", t("setup.kill_grace_default")), t("setup.kill_grace_help")),
      field(t("setup.min_disk"), numberInput("min_free_disk_gb", { min: 0, placeholder: "1" }), t("setup.min_disk_help"))));
}

function domain(p) {
  if (p.type === "real" || p.type === "integer") return `[${num(p.range[0])}, ${num(p.range[1])}]${p.log ? " log" : ""}`;
  return p.values.join(", ");
}

function paramInput(param, key, tuning) {
  const values = S.draft.parameters?.[key] ?? {};
  const has = Object.prototype.hasOwnProperty.call(values, param.name);
  const set = value => {
    const p = clone(S.draft.parameters ?? {});
    p[key] = { ...(p[key] ?? {}) };
    if (value === undefined) delete p[key][param.name]; else p[key][param.name] = value;
    if (Object.keys(p[key]).length === 0) delete p[key];
    if (Object.keys(p).length) S.draft.parameters = p; else delete S.draft.parameters;
    changed();
  };
  const empty = key.includes("/") ? t("param.as_all") : tuning ? t("param.tuned") :
    param.default !== null && param.default !== undefined ? t("param.default", { value: param.default }) : t("param.not_passed");
  if (param.type === "categorical" || param.type === "ordinal") {
    const index = has ? param.values.findIndex(v => v === values[param.name]) : -1;
    return h("select", { "aria-label": `${key} ${param.name}`,
      onchange: e => set(e.target.value === "" ? undefined : param.values[Number(e.target.value)]) },
    h("option", { value: "", selected: index < 0 }, empty),
    param.values.map((v, i) => h("option", { value: String(i), selected: i === index }, String(v))));
  }
  const integer = param.type === "integer";
  return h("input", { type: "number", min: param.range[0], max: param.range[1], step: integer ? 1 : "any",
    placeholder: empty, value: has ? values[param.name] : "", "aria-label": `${key} ${param.name}`,
    oninput: e => { const v = e.target.value.trim(); set(v === "" ? undefined : (integer ? parseInt(v, 10) : Number(v))); } });
}

function parametersCard() {
  const tuning = !!S.draft.tuning?.enabled;
  const withParams = S.manifest.algorithms.filter(a => a.parameters.length);
  if (!withParams.length) return null;
  const units = new Set(chosenUnits());
  return h("div", { class: "card" }, h("h2", {}, cap(term("parameters"))),
    help(tuning ? t("param.help_tuning") : t("param.help")),
    tuning ? alertBox(t("param.tuning_note"), "info") : null,
    withParams.map(a => {
      const used = a.variants.some(v => units.has(`${a.name}/${v}`));
      const keys = [a.name, ...(a.variants.length > 1 ? a.variants.map(v => `${a.name}/${v}`) : [])];
      const custom = keys.some(k => Object.keys(S.draft.parameters?.[k] ?? {}).length);
      return h("details", { class: "hp" + (used ? "" : " off"), open: custom || withParams.length === 1 },
        h("summary", {}, a.name, a.description ? h("span", { class: "summary-note" }, text(a.description)) : null,
          used ? null : h("span", { class: "summary-note" }, t("param.not_selected"))),
        h("div", { class: "hp-body scroll-x" }, h("table", { class: "tab params" },
          h("thead", {}, h("tr", {}, h("th", {}, t("param.name")), h("th", {}, t("param.domain")), h("th", {}, t("param.default_col")),
            keys.map(k => h("th", {}, k === a.name ? (keys.length > 1 ? t("param.all_variants", {}) : t("param.value")) :
              h("span", { title: variantTitle(a, k.split("/")[1]) }, k.split("/")[1]))))),
          h("tbody", {}, a.parameters.map(p => h("tr", {},
            h("td", {}, h("strong", {}, p.name), h("span", { class: "type-tag" }, t(`param.type.${p.type}`)),
              p.description ? h("div", { class: "help" }, text(p.description)) : null,
              p.condition ? h("div", { class: "help mono" }, t("param.condition", { condition: p.condition })) : null),
            h("td", { class: "mono" }, domain(p)), h("td", { class: "mono" }, p.default ?? "–"),
            keys.map(k => h("td", {}, paramInput(p, k, tuning)))))))));
    }));
}

function boundsTable() {
  const objectives = S.manifest.objectives;
  const training = S.draft.tuning?.instances ?? experimentInstances();
  const bounds = S.draft.tuning?.bounds ?? {};
  for (const [inst, pairs] of Object.entries(bounds)) if (!boundsDraft[inst]) boundsDraft[inst] = clone(pairs);
  const storeBounds = inst => {
    const pairs = boundsDraft[inst];
    const complete = pairs && pairs.length === objectives.length &&
      pairs.every(p => p.every(x => typeof x === "number" && !Number.isNaN(x)));
    const all = { ...(S.draft.tuning?.bounds ?? {}) };
    if (complete) all[inst] = pairs; else delete all[inst];
    setp(S.draft, "tuning.bounds", Object.keys(all).length ? all : undefined);
    changed();
  };
  const cell = (inst, o, side) => h("input", { type: "number", step: "any", class: "short",
    placeholder: side ? "max" : "min", value: boundsDraft[inst]?.[o]?.[side] ?? "",
    oninput: e => {
      const row = boundsDraft[inst] ??= objectives.map(() => [NaN, NaN]);
      row[o][side] = e.target.value === "" ? NaN : Number(e.target.value);
      storeBounds(inst);
    } });
  return field(t("tuning.bounds"), h("div", { class: "scroll-x" }, h("table", { class: "tab" },
    h("thead", {}, h("tr", {}, h("th", {}, cap(term("instance"))),
      objectives.map(o => h("th", {}, `${o.name} (${t(`sense.${o.sense}`)})`)))),
    h("tbody", {}, training.map(inst => h("tr", {}, h("td", {}, inst),
      objectives.map((o, k) => h("td", { class: "nowrap" }, cell(inst, k, 0), " ", cell(inst, k, 1)))))))),
  t("tuning.bounds_help"), { wide: true });
}

function tuningCard() {
  const tuning = S.draft.tuning ?? {};
  if (!tuning.enabled) return null;
  const names = experimentInstances();
  return h("div", { class: "card" }, h("h2", {}, t("tuning.title")), h("div", { class: "grid-fields" },
    field(t("tuning.experiments"), numberInput("tuning.max_experiments", { min: 1, integer: true, placeholder: "1000" }),
      t("tuning.experiments_help")),
    field(t("tuning.seed"), numberInput("tuning.seed", { integer: true, placeholder: "1" })),
    S.project.multiobjective ? field(t("tuning.calibration"), numberInput("tuning.calibration_runs",
      { min: 1, integer: true, placeholder: "3" }), t("tuning.calibration_help")) : null),
  h("div", { class: "group" }, h("h3", {}, t("tuning.instances")),
    chipList("tuning.instances", S.manifest.instances.map(i => i.name), { defaultList: names }),
    help(t("tuning.instances_help"))),
  h("div", { class: "switch-row" }, switchInput(t("tuning.own_budget"), !!tuning.budget, on => {
    setp(S.draft, "tuning.budget", on ? clone(S.draft.budget ?? { max_evaluations: 1000 }) : undefined); changed(true);
  }), help(t("tuning.own_budget_help"))),
  tuning.budget ? h("div", { class: "grid-fields" },
    field(t("setup.evaluations"), numberInput("tuning.budget.max_evaluations", { min: 1, integer: true, placeholder: t("setup.no_limit") })),
    field(t("setup.time_limit"), timeInput("tuning.budget.time_limit_s", t("setup.no_limit")))) : null,
  S.project.multiobjective ? boundsTable() : null);
}

const INDICATOR_KEYS = ["hv", "igd_plus", "igd", "epsilon_additive", "best", "gap"];

function analysisCard() {
  const all = S.project.indicators;
  const custom = Array.isArray(S.draft.indicators);
  const tests = S.draft.statistics?.tests ?? S.project.statistical_tests;
  const changedHere = custom || S.draft.statistics || S.draft.normalization;
  return h("details", { class: "card advanced", open: !!changedHere },
    h("summary", {}, h("h2", {}, t("an_setup.title")), h("span", { class: "help" }, t("an_setup.summary"))),
    h("div", { class: "grid-fields" },
      field(t("an_setup.indicators"), h("div", {},
        switchInput(t("an_setup.default_indicators"), !custom, on => {
          setp(S.draft, "indicators", on ? undefined : (S.check?.summary?.indicators ?? [all[0]])); changed(true);
        }),
        custom ? chipList("indicators", all, { label: n => (INDICATOR_KEYS.includes(n) ? t(`ind.${n}`) : n), defaultList: [] }) : null),
      S.project.multiobjective ? t("an_setup.default_mo") : t("an_setup.default_so"), { wide: true }),
      S.project.multiobjective ? field(t("an_setup.offset"), numberInput("normalization.reference_offset",
        { min: 0, placeholder: "0.1" }), t("an_setup.offset_help")) : null,
      field(t("an_setup.tests"), h("div", { class: "chips" }, S.project.statistical_tests.map(name => chip(t(`test.${name}`),
        tests.includes(name), on => {
          const list = S.project.statistical_tests.filter(n => (n === name ? on : tests.includes(n)));
          setp(S.draft, "statistics.tests", same(list, S.project.statistical_tests) ? undefined : list); changed(true);
        })))),
      field(t("an_setup.alpha"), numberInput("statistics.alpha", { min: 0, max: 1, placeholder: "0.05" })),
      field(t("an_setup.blocks"), selectInput("statistics.blocks",
        [["instances", t("an_setup.blocks_instances")], ["runs", t("an_setup.blocks_runs")]], "instances"), t("an_setup.blocks_help")),
      field(t("an_setup.aggregation"), selectInput("statistics.aggregation",
        [["median", t("an_setup.median")], ["mean", t("an_setup.mean")]], "median"), t("an_setup.aggregation_help"))));
}

function outputCard() {
  return h("div", { class: "card" }, h("h2", {}, t("setup.output")),
    field(t("setup.output_dir"), textInput("output_dir", "results", "wide-input"), t("setup.output_dir_help"), { wide: true }),
    h("div", { class: "files-note" },
      h("div", {}, h("span", { class: "path-label" }, t("setup.setup_file")), h("code", { class: "path" }, S.setupInfo.path)),
      h("div", {}, h("span", { class: "path-label" }, t("setup.project_file")), h("code", { class: "path" }, S.project.path))));
}

// ------------------------------------------------------------------ presets

function preset(kind) {
  const d = S.draft;
  if (kind === "complete") {
    delete d.instances;
    delete d.algorithms;
  } else if (kind === "quick") {
    d.instances = [experimentInstances()[0] ?? S.manifest.instances[0].name];
    delete d.algorithms;
    d.seeds = { count: 1 };
    const b = d.budget ?? {};
    if (b.max_evaluations) b.max_evaluations = Math.max(1, Math.round(b.max_evaluations / 10));
    if (b.time_limit_s) b.time_limit_s = Math.max(1, Math.round(b.time_limit_s / 10));
    d.budget = b;
    setp(d, "tuning.enabled", undefined);
  } else {
    S.draft = clone(S.saved);
    boundsDraft = {};
  }
  changed(true);
  toast(t("setup.preset_applied"));
}

function presetsCard() {
  const button = (kind, title, note) => h("button", { type: "button", class: "preset", onclick: () => preset(kind) },
    h("strong", {}, title), h("span", {}, note));
  return h("div", { class: "card band" },
    h("div", {}, h("h2", {}, t("setup.shortcuts")), help(t("setup.shortcuts_help"))),
    h("div", { class: "presets" },
      button("complete", t("setup.preset_complete"), t("setup.preset_complete_help")),
      button("quick", t("setup.preset_quick"), t("setup.preset_quick_help")),
      S.setupInfo.exists ? button("saved", t("setup.preset_saved"), t("setup.preset_saved_help")) : null));
}

// ------------------------------------------------------------------ the page and the bar

export function renderSetup() {
  const root = $("#step-setup");
  if (!root || !S.draft) return;
  const scroll = window.scrollY;
  const info = S.setupInfo;
  fill(root, 
    presetsCard(),
    info.exists ? null : alertBox(t("setup.new_file", { path: info.path }), "info"),
    info.problem ? alertBox(t("setup.unreadable", { path: info.path, problem: info.problem }), "error") : null,
    h("form", { autocomplete: "off", onsubmit: e => e.preventDefault() },
      outputCard(), whatToRun(), sizeCard(), resourcesCard(), parametersCard(), tuningCard(), analysisCard(),
      h("details", { class: "card yaml" }, h("summary", {}, h("h2", {}, t("setup.yaml"))),
        h("pre", { class: "code", id: "setup-yaml" }, S.check?.yaml ?? ""))),
    h("div", { class: "card run-bar", id: "run-bar" }));
  renderBar();
  window.scrollTo(0, scroll);
}

export function renderBar() {
  const bar = $("#run-bar");
  if (!bar || !S.check) return;
  const c = S.check;
  const s = c.summary;
  const issues = (c.issues?.length ? c.issues.map(msg) : c.errors) ?? [];
  const isBusy = busy();
  const summary = s ? t("setup.summary_runs", { runs: count(s.runs, "run"), parts: [count(s.instances.length, "instance"),
    count(s.units.length, "variant"), count(s.seeds, "seed")].join(" × ") }) : t("setup.invalid");
  fill(bar, 
    issues.length ? h("ul", { class: "alert alert-error issues" }, issues.map(e => h("li", {}, e))) : null,
    isBusy ? alertBox(t("setup.locked_running"), "warn") : null,
    h("div", { class: "bar-line" },
      h("div", { class: "bar-summary" },
        h("div", { class: "live-summary" + (!c.ok || !s?.runs ? " empty" : "") }, c.ok && !s?.runs ? t("setup.nothing") : summary),
        h("div", { class: "help ellipsis" }, dirty() ? h("span", { class: "dirty" }, t("setup.unsaved")) : t("setup.saved_in"),
          " ", S.setupInfo.path)),
      dirty() ? h("button", { type: "button", class: "link", onclick: () => { S.draft = clone(S.saved); boundsDraft = {}; changed(true); } },
        t("setup.discard")) : null,
      h("button", { type: "button", class: "btn btn-sec", disabled: !c.ok || isBusy || !dirty() && S.setupInfo.exists,
        onclick: () => save() }, t("action.save")),
      h("button", { type: "button", class: "btn btn-prim btn-big", disabled: !c.ok || isBusy || !s?.runs,
        onclick: confirmRun }, t("action.run"))));
}

async function save() {
  try {
    const info = await api("/api/save", { setup: S.draft });
    loadSetupInfo(info);
    toast(t("setup.saved_toast"));
    emit("saved");
    return true;
  } catch (e) { toast(errorText(e), true); return false; }
}

function confirmBody() {
  const s = S.check.summary;
  const d = S.draft;
  const b = d.budget ?? {};
  const jobs = d.parallel_jobs === 1 ? t("confirm.sequential") :
    !d.parallel_jobs ? t("confirm.jobs_auto", { n: S.meta?.cpu_count ?? 1 }) : t("confirm.jobs", { n: d.parallel_jobs });
  return h("div", {},
    h("div", { class: "total" }, t("confirm.total", { runs: count(s.runs, "run") })),
    kv([
      [cap(term("instances")), s.instances.join(", ")],
      [t("setup.variants_title"), s.units.map(unitLabel).join(", ")],
      [cap(term("seeds")), String(s.seeds)],
      [t("setup.evaluations"), b.max_evaluations ? num(b.max_evaluations) : t("setup.no_limit")],
      [t("setup.time_limit"), b.time_limit_s ? duration(b.time_limit_s) : t("setup.no_limit")],
      [t("setup.resources"), jobs],
      [t("tuning.title"), s.tuning ? t("confirm.tuning_on", { n: s.tuning.filter(u => u.tuned.length).length }) : t("confirm.no")],
      [t("setup.output_dir"), s.output_dir],
    ]),
    dirty() ? alertBox(t("confirm.will_save"), "info") : null,
    S.status?.state ? alertBox(t("confirm.resume_note"), "info") : null);
}

async function confirmRun() {
  const ok = await confirmDialog({ title: t("confirm.title"), body: confirmBody(), ok: t("confirm.start"),
    cancel: t("action.back") });
  if (!ok) return;
  if ((dirty() || !S.setupInfo.exists) && !(await save())) return;
  emit("start-run", {});
}

