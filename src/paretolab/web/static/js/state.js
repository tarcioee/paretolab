// The page's state, shared by the screens, and a tiny event bus between them.

export const S = {
  meta: null,          // GET /api/meta: version, languages, cpu_count, tuner
  project: null,       // GET /api/project
  manifest: null,      // project.manifest
  setupInfo: null,     // GET /api/setup (path, exists, data, check)
  saved: null,         // the saved setup
  draft: null,         // the setup being edited
  check: null,         // POST /api/check of the draft
  status: null,        // GET /api/status
  analysis: null,      // GET /api/analysis
  step: "setup",       // setup | run | analysis
};

const hooks = {};
export const on = (name, fn) => (hooks[name] ??= []).push(fn);
export const emit = (name, ...args) => (hooks[name] ?? []).forEach(fn => fn(...args));

/** Every algorithm variant of the project as "algorithm/variant". */
export const allUnits = () => S.manifest.algorithms.flatMap(a => a.variants.map(v => `${a.name}/${v}`));

/** How a unit is shown: "alg" when the algorithm has only the "default" variant. */
export const unitLabel = unit => (unit.endsWith("/default") ? unit.slice(0, -"/default".length) : unit);

export const algorithmOf = name => S.manifest.algorithms.find(a => a.name === name);
export const instanceOf = name => S.manifest.instances.find(i => i.name === name);

/** Phase of the experiment for the page: none, running, tuning, paused, interrupted, failed, done. */
export function phase(st = S.status) {
  const state = st?.state;
  if (!state) return "none";
  const p = state.phase;
  if ((p === "running" || p === "tuning") && !st.alive) return "interrupted";
  return p;
}

export const analyzing = (st = S.status) => !!st?.children?.analyze?.running;
