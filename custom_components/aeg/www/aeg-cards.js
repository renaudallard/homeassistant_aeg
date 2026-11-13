// Lovelace cards that lay an AEG appliance out the way the AEG app does, and
// drive it the same way: a washing machine, an oven, an air conditioner and
// an air purifier, each with what it is doing across the top, the controls
// that matter most to that kind of appliance under it, the rest of its
// settings after them, and its commands at the bottom.
//
// The integration builds its entities from what the appliance says about
// itself, and these read them the same way: each control is found by what it
// is rather than by a list held per model, so a model nobody has seen still
// gets a card with its own settings on it. A setting the appliance will not
// take right now goes unavailable, and its control greys out with it.
//
// The cards share one file so they share one copy of everything they have in
// common. Bundled with the aeg integration, which serves this file and adds it
// as a dashboard resource, so there is no resource to add by hand.

const UNAVAILABLE = "unavailable";

// Readings and controls whose names the integration translates, found by
// their translation key, which stays the same in every language. Home
// Assistant builds a new entity's id from the translated name, so the id is
// no use for these: select.lave_linge_programme in French.
const KEYED = {
  programme: ["select", ["program_uid", "program"]],
  state: ["sensor", ["appliance_state"]],
  phase: ["sensor", ["cycle_phase"]],
  door: ["sensor", ["door_state"]],
  remote: ["sensor", ["remote_control"]],
  ends: ["sensor", ["finishes_at"]],
  alerts: ["binary_sensor", ["alerts"]],
  lock: ["switch", ["ui_lock_mode", "ui_lock", "ui_locked", "child_lock"]],
  target: ["number", ["target_temperature_c", "target_temperature"]],
  probe_target: ["number", ["target_food_probe_temperature_c"]],
  probe: ["sensor", ["food_probe_insertion_state"]],
  tank: ["sensor", ["water_tank_empty"]],
  room: ["sensor", ["ambient_temperature_c", "temperature"]],
  fan: ["select", ["fan_speed_setting", "fan_mode"]],
  pm25: ["sensor", ["pm25_approximate"]],
  filter_life: ["sensor", ["life_remaining"]],
  filter: ["sensor", ["filter_state"]],
};

// A length of time is a reading in seconds with a clock beside it, and the
// two share a translation key. Only the one in seconds is a duration.
const DURATIONS = {
  remaining: "time_to_end",
  running: "running_time",
};

// An air conditioner's mode and a purifier's have no name the integration
// translates, so their id is made from the field's own name and ends the
// same way in every language. A louvre's mode is numbered and is not it.
const MODE = /^select\..*_mode$/;
const NUMBERED_MODE = /_\d+_mode$/;

// The command buttons are named after the field and the command, neither of
// which is translated, so their ids end the same way in every language.
const COMMAND = /^button\..*_execute_command_(on|off|start|pause|resume|stopreset)$/;

const COMMANDS = ["on", "off", "start", "pause", "resume", "stopreset"];

// Which of the roles above an entity plays, if any.
function role(id, entity, states) {
  const key = entity.translation_key;
  for (const [name, [domain, keys]] of Object.entries(KEYED)) {
    if (id.startsWith(`${domain}.`) && keys.includes(key)) return name;
  }
  for (const [name, wanted] of Object.entries(DURATIONS)) {
    if (!id.startsWith("sensor.") || key !== wanted) continue;
    const state = states && states[id];
    if (state && state.attributes.device_class === "duration") return name;
  }
  if (!key && MODE.test(id) && !NUMBERED_MODE.test(id)) return "mode";
  const command = COMMAND.exec(id);
  return command ? command[1] : null;
}

// Words some appliances run together, which nothing can split for them.
const JOINED = new Map([
  ["FANONLY", "Fan only"],
  ["AUTOCLEAN", "Auto clean"],
]);

// What an appliance says, in a form worth reading. Older appliances shout
// and run their words together with underscores, newer ones write in camel
// case or in lower case, and a washer's programme carries its family in front of its name:
// COTTON_PR_ECO40-60 is the eco 40-60 cottons programme. Anything else is
// left as it came.
function words(value) {
  const raw = String(value);
  if (JOINED.has(raw)) return JOINED.get(raw);
  if (/^[a-z]+(?:[A-Z0-9][a-z0-9]*)*$/.test(raw)) {
    const text = raw.replace(/([A-Z0-9])/g, " $1").toLowerCase();
    return text[0].toUpperCase() + text.slice(1);
  }
  if (!/^[A-Z0-9][A-Z0-9_+\-.]*$/.test(raw)) return raw;
  let text = raw;
  const cut = text.indexOf("_PR_");
  if (cut >= 0) text = text.slice(cut + 4);
  const unit = /^(\d+)_(RPM|CELSIUS|FAHRENHEIT)$/.exec(text);
  if (unit) return `${unit[1]} ${{ RPM: "rpm", CELSIUS: "°C", FAHRENHEIT: "°F" }[unit[2]]}`;
  text = text.replace(/_+/g, " ").trim().toLowerCase();
  return text ? text[0].toUpperCase() + text.slice(1) : raw;
}

// An icon for a setting, chosen by what its name is about.
const ICONS = [
  [/temperature/, "mdi:thermometer"],
  [/spin/, "mdi:rotate-right"],
  [/steam/, "mdi:weather-fog"],
  [/prewash|soak/, "mdi:water-outline"],
  [/rinse/, "mdi:water"],
  [/stain/, "mdi:spray-bottle"],
  [/night|silent|quiet|sleep/, "mdi:weather-night"],
  [/crease|iron/, "mdi:iron"],
  [/load|weight/, "mdi:scale"],
  [/time|quick|finish|start/, "mdi:timer-outline"],
  [/eco|energy/, "mdi:leaf"],
  [/dry/, "mdi:tumble-dryer"],
  [/swing|louvre|flap/, "mdi:arrow-oscillating"],
  [/clean|air/, "mdi:air-filter"],
  [/fan/, "mdi:fan"],
];

// An icon for one of the modes an appliance runs in.
const MODE_ICONS = [
  [/cool/, "mdi:snowflake"],
  [/heat/, "mdi:fire"],
  [/dry/, "mdi:water-percent"],
  [/fan/, "mdi:fan"],
  [/auto/, "mdi:autorenew"],
  [/smart/, "mdi:creation"],
  [/quiet|sleep/, "mdi:weather-night"],
  [/manual/, "mdi:hand-back-right"],
];

function iconFrom(table, label, fallback) {
  const text = String(label).toLowerCase();
  for (const [pattern, icon] of table) if (pattern.test(text)) return icon;
  return fallback;
}

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );

// A selector-safe entity id, so an id with a dot reads as one string.
const cssEscape = (id) =>
  window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/[^a-zA-Z0-9_-]/g, "\\$&");

// Seconds, shown the way a timer reads, a part minute counted as a whole one
// so the last seconds of a wash do not read as nothing left.
function clock(seconds) {
  const m = Math.ceil(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
  return `${m} min`;
}

// Where a fan speed sits, slowest first, with automatic ahead of them all.
const FAN_ORDER = ["auto", "quiet", "low", "middle", "medium", "high", "turbo"];

// The cloud hands values over in alphabetical order, which puts 1000 rpm
// before 400 and a high fan before a low one. Where every value starts with
// its number they are put in the order of those numbers, and fan speeds in
// the order they run at; the appliance still hears its own words.
function ordered(options) {
  const list = [...options];
  if (list.length > 1 && list.every((o) => /^\d/.test(o)))
    return list.sort((a, b) => parseFloat(a) - parseFloat(b));
  const rank = (o) => FAN_ORDER.indexOf(String(o).toLowerCase());
  if (list.length > 1 && list.every((o) => rank(o) >= 0)) return list.sort((a, b) => rank(a) - rank(b));
  return list;
}

// A choice of on and off is a flag, and is drawn as one.
function flag(options) {
  if (!options || options.length !== 2) return null;
  const on = options.find((o) => String(o).toLowerCase() === "on");
  const off = options.find((o) => String(o).toLowerCase() === "off");
  return on !== undefined && off !== undefined ? { on, off } : null;
}

const unknown = (value) => value === undefined || value === UNAVAILABLE || value === "unknown";

// Every AEG device on the system and the roles its entities play.
function rolesByDevice(hass) {
  const entities = (hass && hass.entities) || {};
  const found = {};
  for (const id of Object.keys(entities)) {
    const entity = entities[id];
    if (entity.platform !== "aeg" || !entity.device_id) continue;
    const name = role(id, entity, hass.states);
    if (name) (found[entity.device_id] = found[entity.device_id] || new Set()).add(name);
  }
  return found;
}

function devicesOf(hass, kind) {
  const found = rolesByDevice(hass);
  return Object.keys(found).filter((device) => kind.finds(found[device]));
}

// What a warning across the top says, by the reading that raises it and what
// that reading says.
const REMOTE = new Map([
  ["DISABLED", "Remote control is off at the machine."],
  ["NOT_SAFETY_RELEVANT_ENABLED", "Remote start is not armed at the machine."],
  ["TEMPORARY_LOCKED", "Remote control is locked at the machine for now."],
]);

const FILTER = new Map([
  ["CLEAN", "The filter wants cleaning."],
  ["CHANGE", "The filter wants changing."],
  ["BUY", "The filter is due for a new one."],
]);

// Phases that say nothing about where the appliance has got to.
const QUIET_PHASES = new Set(["UNAVAILABLE", "CYCLE_PHASE_HIDDEN", "unavailable", "unknown"]);

// The appliance states in which a pause or a resume is the thing to offer.
const PAUSABLE = new Set(["RUNNING", "DELAYED_START", "DELAYEDSTART"]);

// What the start button reads as, by the command it sends.
const GO = {
  start: ["mdi:play", "Start"],
  pause: ["mdi:pause", "Pause"],
  resume: ["mdi:play", "Resume"],
};

// How long a value set on a stepper is shown before the appliance confirms
// it, after which what it reports wins again.
const PENDING_MS = 10000;
// How long a stepper waits for the next press before it sends.
const SETTLE_MS = 600;

// Every card draws these when the appliance has them.
const COMMON = ["state", "door", "remote", "alerts", "lock", "filter", "tank", ...COMMANDS];

// What each kind of appliance is told apart by, and what its card puts where:
// the readings across the top, then the controls drawn large under them.
const KINDS = [
  {
    tag: "aeg-washer-card",
    name: "AEG Washing Machine",
    noun: "washing machine",
    description: "A washing machine laid out and driven the way the AEG app does it.",
    // A programme to pick and a time left to count down. An oven has the
    // first and not the second, an air conditioner neither.
    finds: (r) => r.has("programme") && r.has("remaining"),
    stats: ["status", "remaining", "ends"],
    hero: ["programme"],
  },
  {
    tag: "aeg-oven-card",
    name: "AEG Oven",
    noun: "oven",
    description: "An oven laid out and driven the way the AEG app does it.",
    finds: (r) => r.has("programme") && r.has("target") && !r.has("remaining"),
    stats: ["status", "running", "probe"],
    hero: ["programme", "target", "probe_target"],
  },
  {
    tag: "aeg-air-conditioner-card",
    name: "AEG Air Conditioner",
    noun: "air conditioner",
    description: "An air conditioner laid out and driven the way the AEG app does it.",
    finds: (r) => r.has("target") && r.has("mode") && !r.has("programme"),
    stats: ["status", "room", "ends"],
    hero: ["target", "mode", "fan"],
  },
  {
    tag: "aeg-air-purifier-card",
    name: "AEG Air Purifier",
    noun: "air purifier",
    description: "An air purifier laid out and driven the way the AEG app does it.",
    finds: (r) => (r.has("pm25") || r.has("filter_life")) && !r.has("target"),
    stats: ["status", "pm25", "filter_life"],
    hero: ["mode", "fan"],
  },
];

// The readings across the top: what each is headed and which role it shows.
// The status is always there; the rest only where the appliance has them.
const STATS = {
  status: ["Status", "state"],
  remaining: ["Time left", "remaining"],
  ends: ["Ends at", "ends"],
  running: ["Running for", "running"],
  probe: ["Food probe", "probe"],
  room: ["Room", "room"],
  pm25: ["PM2.5", "pm25"],
  filter_life: ["Filter life", "filter_life"],
};

// What every card does. Each kind of appliance gets a subclass of its own
// that says which kind it is, made at the bottom of this file.
class AegCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._signature = null;
    this._pending = {};
    this._settle = {};
    // A role this card has no place for is drawn among the settings instead,
    // so nothing the appliance offers falls off the card.
    const kind = this.constructor.kind;
    this._draws = new Set([...COMMON, "phase", ...kind.stats.map((s) => STATS[s][1]), ...kind.hero]);
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 9;
  }

  static getConfigElement() {
    return document.createElement(`${this.kind.tag}-editor`);
  }

  static getStubConfig(hass) {
    const devices = devicesOf(hass, this.kind);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  _device() {
    if (this._config.device) return this._config.device;
    const devices = devicesOf(this._hass, this.constructor.kind);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // The appliance's entities sorted into what each is for: the ones this card
  // draws in a place of their own, and then the rest of the settings by their
  // kind. What configures the appliance rather than works it carries a
  // category, so it is stepped over.
  _controls(device) {
    const found = { switches: [], flags: [], selects: [], numbers: [] };
    const entities = (this._hass && this._hass.entities) || {};
    if (!device) return found;
    for (const id of Object.keys(entities)) {
      const entity = entities[id];
      if (entity.device_id !== device || entity.platform !== "aeg") continue;
      const state = this._hass.states[id];
      if (!state) continue;
      const name = role(id, entity, this._hass.states);
      if (name && this._draws.has(name)) {
        found[name] = id;
        continue;
      }
      if (entity.entity_category || entity.hidden) continue;
      if (id.startsWith("switch.")) found.switches.push(id);
      else if (id.startsWith("select.")) (flag(state.attributes.options) ? found.flags : found.selects).push(id);
      else if (id.startsWith("number.")) found.numbers.push(id);
    }
    for (const key of ["switches", "flags", "selects", "numbers"]) found[key].sort();
    return found;
  }

  _value(id) {
    const state = id && this._hass.states[id];
    return state ? state.state : undefined;
  }

  _usable(id) {
    const value = this._value(id);
    return value !== undefined && value !== UNAVAILABLE;
  }

  _call(id, domain, service, extra) {
    if (!id) return undefined;
    return this._hass.callService(domain, service, { entity_id: id, ...(extra || {}) });
  }

  // What an appliance's word is shown as: Home Assistant's own text for it
  // where it has one, and failing that the word made readable.
  _shown(id, value) {
    const state = this._hass.states[id];
    if (state && typeof this._hass.formatEntityState === "function") {
      const text = this._hass.formatEntityState(state, value);
      if (text && text !== value) return text;
    }
    return words(value);
  }

  _machine() {
    const device = this._hass.devices && this._hass.devices[this._device()];
    return device ? device.name_by_user || device.name : undefined;
  }

  // What to call a setting: its own name, with the appliance's name taken off
  // the front where Home Assistant put it there.
  _label(id) {
    const state = this._hass.states[id];
    const name = state && state.attributes.friendly_name;
    if (!name) return id;
    const machine = this._machine();
    return machine && name.startsWith(`${machine} `) ? name.slice(machine.length + 1) : name;
  }

  _render() {
    if (!this._hass || !this.shadowRoot) return;
    const device = this._device();
    const found = this._controls(device);
    this._found = found;
    const named = Object.keys(found)
      .filter((k) => !Array.isArray(found[k]))
      .sort()
      .map((k) => `${k}=${found[k]}`)
      .join(",");
    const options = [...found.switches, ...found.flags, ...found.selects, ...found.numbers].join(",");
    const signature = `${device || ""}|${named}|${options}|${this._machine() || ""}`;
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, found);
    }
    this._paint(found);
  }

  _build(device, found) {
    const kind = this.constructor.kind;
    const noun = kind.noun[0].toUpperCase() + kind.noun.slice(1);
    const title = this._config.name || this._machine() || noun;
    const note = !device
      ? devicesOf(this._hass, kind).length
        ? `More than one ${kind.noun} here. Set 'device' to the one you mean.`
        : `No ${kind.noun} found on this system.`
      : "";
    if (note) {
      this.shadowRoot.innerHTML = `${STYLE}
        <ha-card><div class="title">${escape(title)}</div>
        <div class="note">${escape(note)}</div></ha-card>`;
      return;
    }

    const stats = kind.stats
      .filter((s) => s === "status" || found[STATS[s][1]])
      .map((s) => {
        const sub = s === "status" ? `<span class="sub" data-k="phase"></span>` : "";
        return `<div class="stat"><span class="cap">${STATS[s][0]}</span><span class="num" data-k="${STATS[s][1]}">—</span>${sub}</div>`;
      })
      .join("");

    const hero = kind.hero.map((part) => this._hero(part, found)).join("");

    const flags = found.flags
      .map((id) => this._pill(`data-flag="${escape(id)}"`, iconFrom(ICONS, this._label(id), "mdi:tune-variant"), this._label(id)))
      .join("");
    const switches = found.switches
      .map((id) => this._pill(`data-switch="${escape(id)}"`, iconFrom(ICONS, this._label(id), "mdi:tune-variant"), this._label(id)))
      .join("");
    const choosers = found.selects
      .map(
        (id) => `<label class="field"><span class="cap">${escape(this._label(id))}</span>
          <select class="picker" data-select="${escape(id)}"></select></label>`
      )
      .join("");
    const sliders = found.numbers
      .map(
        (id) => `<label class="field slider"><span class="cap">${escape(this._label(id))}
          <b data-out="${escape(id)}"></b></span>
          <input type="range" data-number="${escape(id)}"></label>`
      )
      .join("");
    const chips = switches + flags;
    const settings =
      choosers || chips || sliders
        ? `<div class="opts-head">Settings</div>
           ${choosers ? `<div class="fields">${choosers}</div>` : ""}
           ${chips ? `<div class="opts">${chips}</div>` : ""}
           ${sliders ? `<div class="fields">${sliders}</div>` : ""}`
        : "";

    // An appliance with a programme to run is started and stopped, and its
    // power is a pill beside the lock. One that only goes on and off has
    // that as its main button instead.
    const runs = Boolean(found.start || found.pause || found.resume || found.stopreset);
    const power = Boolean(found.on || found.off);
    const quick = [];
    if (power && runs) quick.push(this._pill('data-role="power"', "mdi:power", "Power"));
    if (found.lock) quick.push(this._pill('data-role="lock"', "mdi:lock", this._label(found.lock)));

    let actions = "";
    if (runs)
      actions = `<div class="actions">
             <button class="go" type="button"><ha-icon icon="mdi:play"></ha-icon><span>Start</span></button>
             <button class="stop" type="button"><ha-icon icon="mdi:stop"></ha-icon><span>Stop</span></button>
           </div>`;
    else if (power)
      actions = `<div class="actions">
             <button class="go" data-role="power" type="button"><ha-icon icon="mdi:power"></ha-icon><span>Turn on</span></button>
           </div>`;

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="title">${escape(title)}</div>
        ${["door", "remote", "alerts", "filter", "tank"].map((w) => this._warning(w)).join("")}
        <div class="stats">${stats}</div>
        ${hero}
        ${settings}
        ${quick.length ? `<div class="quick">${quick.join("")}</div>` : ""}
        ${actions}
      </ha-card>`;
    this._wire();
  }

  _pill(data, icon, label) {
    return `<button class="pill" ${data} type="button"><ha-icon icon="${icon}"></ha-icon><span>${escape(label)}</span></button>`;
  }

  _warning(name) {
    const icon = { door: "mdi:exclamation", remote: "mdi:remote-off", alerts: "mdi:alert", filter: "mdi:air-filter", tank: "mdi:water-off" }[name];
    return `<div class="warn" data-warn="${name}" hidden>
          <span class="dot"><ha-icon icon="${icon}"></ha-icon></span>
          <span data-text="${name}"></span>
        </div>`;
  }

  // One of the controls drawn large: the programme on a card of its own, a
  // temperature on a stepper, or the modes an appliance runs in as a row of
  // chips. Each is left out where the appliance does not have it.
  _hero(part, found) {
    const id = found[part];
    if (!id) return "";
    if (part === "programme")
      return `<label class="programme"><span class="cap">Programme</span><select class="picker prog" data-role="programme"></select></label>`;
    if (id.startsWith("number."))
      return `<div class="stepper"><span class="cap">${escape(this._label(id))}</span>
          <div class="dial">
            <button class="step" type="button" data-step="${escape(id)}" data-delta="-1"><ha-icon icon="mdi:minus"></ha-icon></button>
            <span class="big" data-big="${escape(id)}">—</span>
            <button class="step" type="button" data-step="${escape(id)}" data-delta="1"><ha-icon icon="mdi:plus"></ha-icon></button>
          </div></div>`;
    return `<div class="row"><span class="cap">${escape(this._label(id))}</span>
        <div class="opts" data-chips="${escape(id)}" data-part="${part}"></div></div>`;
  }

  _wire() {
    const root = this.shadowRoot;
    const prog = root.querySelector('[data-role="programme"]');
    if (prog)
      prog.addEventListener("change", () =>
        this._call(this._found.programme, "select", "select_option", { option: prog.value })
      );
    const power = root.querySelector('[data-role="power"]');
    if (power) power.addEventListener("click", () => this._press(this._powerCommand()));
    const lock = root.querySelector('[data-role="lock"]');
    if (lock) lock.addEventListener("click", () => this._call(this._found.lock, "switch", "toggle"));
    for (const pill of root.querySelectorAll("[data-switch]"))
      pill.addEventListener("click", () => this._call(pill.dataset.switch, "switch", "toggle"));
    for (const pill of root.querySelectorAll("[data-flag]"))
      pill.addEventListener("click", () => this._flip(pill.dataset.flag));
    for (const el of root.querySelectorAll("[data-select]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.select, "select", "select_option", { option: el.value })
      );
    for (const el of root.querySelectorAll("[data-number]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.number, "number", "set_value", { value: Number(el.value) })
      );
    for (const el of root.querySelectorAll("[data-step]"))
      el.addEventListener("click", () => this._step(el.dataset.step, Number(el.dataset.delta)));
    // The chips are drawn again whenever the choices change, so one listener
    // on the row takes every chip that is ever in it.
    for (const row of root.querySelectorAll("[data-chips]"))
      row.addEventListener("click", (event) => {
        const chip = event.target.closest("[data-option]");
        if (chip && !chip.disabled)
          this._call(row.dataset.chips, "select", "select_option", { option: chip.dataset.option });
      });
    const go = root.querySelector(".go:not([data-role])");
    if (go) go.addEventListener("click", () => this._press(this._goCommand()));
    const stop = root.querySelector(".stop");
    if (stop) stop.addEventListener("click", () => this._press("stopreset"));
  }

  _press(command) {
    const id = command && this._found[command];
    if (id && this._usable(id)) this._call(id, "button", "press");
  }

  // A flag kept as a choice of on and off is set to whichever it is not.
  _flip(id) {
    const state = this._hass.states[id];
    const both = state && flag(state.attributes.options);
    if (!both || !this._usable(id)) return;
    const option = String(state.state).toLowerCase() === "on" ? both.off : both.on;
    this._call(id, "select", "select_option", { option });
  }

  // A stepper moves from what it last showed, so pressing it three times goes
  // three steps however slowly the appliance confirms each one, and it sends
  // only once the presses stop, so those three are one command.
  _step(id, delta) {
    const state = this._hass.states[id];
    if (!state || !this._usable(id)) return;
    const { min, max, step } = this._range(state);
    const from = this._stepperValue(id);
    if (from === undefined) return;
    // Steps are counted from where the range starts, as the appliance counts
    // them, so an oven going up in fives from 30 lands on 35 and not 40.
    const base = Number.isFinite(min) ? min : 0;
    const next = Math.min(max, Math.max(min, base + Math.round((from + delta * step - base) / step) * step));
    const pending = { value: Number(next.toFixed(this._decimals(step))), at: Date.now() };
    this._pending[id] = pending;
    clearTimeout(this._settle[id]);
    this._settle[id] = setTimeout(() => this._call(id, "number", "set_value", { value: pending.value }), SETTLE_MS);
    this._paint(this._found);
  }

  _range(state) {
    const a = state.attributes;
    const step = Number(a.step) > 0 ? Number(a.step) : 1;
    return { min: Number(a.min ?? -Infinity), max: Number(a.max ?? Infinity), step };
  }

  _decimals(step) {
    const text = String(step);
    return text.includes(".") ? text.split(".")[1].length : 0;
  }

  // What a stepper shows: the value just set on it until the appliance says
  // the same or long enough has passed, and what the appliance says after.
  _stepperValue(id) {
    if (!this._usable(id)) {
      delete this._pending[id];
      return undefined;
    }
    const pending = this._pending[id];
    const reported = Number(this._value(id));
    const known = !unknown(this._value(id)) && !Number.isNaN(reported);
    if (pending && Date.now() - pending.at < PENDING_MS && (!known || reported !== pending.value))
      return pending.value;
    delete this._pending[id];
    return known ? reported : undefined;
  }

  // The appliance is on unless it says it is off. Pressing the power button
  // sends whichever of the two it does not say it is.
  _isOn() {
    const state = this._value(this._found.state);
    return !unknown(state) && String(state).toUpperCase() !== "OFF";
  }

  _powerCommand() {
    return this._isOn() ? "off" : "on";
  }

  // One button for start, pause and resume, as on the appliance's own panel.
  // The one its state calls for comes first. The appliance also says which of
  // the three it will take right now, which is what the buttons being
  // available or not reflects, so another it will take stands in where that
  // one is refused, and where it takes none the first is shown greyed out.
  _goCommand() {
    const state = String(this._value(this._found.state)).toUpperCase();
    let wanted = "start";
    if (state === "PAUSED" && this._found.resume) wanted = "resume";
    else if (PAUSABLE.has(state) && this._found.pause) wanted = "pause";
    if (this._usable(this._found[wanted])) return wanted;
    return ["resume", "pause", "start"].find((c) => this._usable(this._found[c])) || wanted;
  }

  _paint(found) {
    const root = this.shadowRoot;
    if (!root || root.querySelector(".note")) return;

    const warn = (name, text) => {
      const el = root.querySelector(`[data-warn="${name}"]`);
      if (!el) return;
      el.hidden = !text;
      if (text) el.querySelector(`[data-text="${name}"]`).textContent = text;
    };
    warn("door", this._value(found.door) === "OPEN" ? "The door is open." : "");
    warn("remote", REMOTE.get(this._value(found.remote)) || "");
    warn("filter", FILTER.get(this._value(found.filter)) || "");
    warn("tank", this._value(found.tank) === "STEAM_TANK_EMPTY" ? "The steam tank is empty." : "");
    let alert = "";
    if (this._value(found.alerts) === "on") {
      const codes = this._hass.states[found.alerts].attributes.alerts;
      const list = Array.isArray(codes) && codes.length ? codes.map(words).join(", ") : "";
      alert = list ? `The appliance reports: ${list}.` : "The appliance reports an alert.";
    }
    warn("alerts", alert);

    const put = (key, text) => {
      const el = root.querySelector(`[data-k="${key}"]`);
      if (el) el.textContent = text;
    };
    const state = this._value(found.state);
    put("state", unknown(state) ? "—" : this._shown(found.state, state));
    const phase = this._value(found.phase);
    put("phase", phase && !QUIET_PHASES.has(phase) ? this._shown(found.phase, phase) : "");
    const left = Number(this._value(found.remaining));
    put("remaining", left > 0 ? clock(left) : "—");
    const running = Number(this._value(found.running));
    put("running", running > 0 ? clock(running) : "—");
    put("ends", this._when(this._value(found.ends)));
    const probe = this._value(found.probe);
    put("probe", unknown(probe) ? "—" : this._shown(found.probe, probe));
    for (const key of ["room", "pm25", "filter_life"]) put(key, this._reading(found[key]));

    this._fill(root.querySelector('[data-role="programme"]'), found.programme);
    for (const id of found.selects) this._fill(root.querySelector(`[data-select="${cssEscape(id)}"]`), id);
    for (const row of root.querySelectorAll("[data-chips]")) this._chips(row);
    for (const el of root.querySelectorAll("[data-big]")) this._dial(el.dataset.big);

    // A setting the appliance will not take right now goes unavailable. Home
    // Assistant drops a call to an unavailable entity, so its control is
    // greyed out rather than left to do nothing when used.
    for (const id of found.switches) {
      const pill = root.querySelector(`[data-switch="${cssEscape(id)}"]`);
      pill.disabled = !this._usable(id);
      pill.classList.toggle("on", this._value(id) === "on");
    }
    for (const id of found.flags) {
      const pill = root.querySelector(`[data-flag="${cssEscape(id)}"]`);
      pill.disabled = !this._usable(id);
      pill.classList.toggle("on", String(this._value(id)).toLowerCase() === "on");
    }
    for (const id of found.numbers) this._slide(id);

    for (const power of root.querySelectorAll('[data-role="power"]')) {
      const on = this._isOn();
      power.classList.toggle("on", on);
      power.disabled = !this._usable(found[this._powerCommand()]);
      if (power.classList.contains("go")) power.querySelector("span").textContent = on ? "Turn off" : "Turn on";
    }
    const lock = root.querySelector('[data-role="lock"]');
    if (lock) {
      lock.classList.toggle("on", this._value(found.lock) === "on");
      lock.disabled = !this._usable(found.lock);
    }

    const go = root.querySelector(".go:not([data-role])");
    if (go) {
      const command = this._goCommand();
      const [icon, text] = GO[command];
      go.querySelector("ha-icon").setAttribute("icon", icon);
      go.querySelector("span").textContent = text;
      go.disabled = !this._usable(found[command]);
    }
    const stop = root.querySelector(".stop");
    if (stop) stop.disabled = !this._usable(found.stopreset);
  }

  // A reading with its unit, where it is a figure.
  _reading(id) {
    const state = id && this._hass.states[id];
    if (!state || unknown(state.state) || Number.isNaN(Number(state.state))) return "—";
    const unit = state.attributes.unit_of_measurement;
    return unit ? `${state.state} ${unit}` : state.state;
  }

  // A finishing time as a clock time, with the day in front when it is not
  // today, as a delayed start can be.
  _when(value) {
    if (unknown(value) || !value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const language = (this._hass.locale && this._hass.locale.language) || this._hass.language;
    const time = date.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === new Date().toDateString()) return time;
    return `${date.toLocaleDateString(language, { weekday: "short" })} ${time}`;
  }

  _options(state) {
    const options = ordered(state.attributes.options || []);
    // The current value is shown even when the appliance has left it off the
    // list, so a control never claims a setting the appliance is not on.
    if (!options.includes(state.state) && !unknown(state.state)) options.unshift(state.state);
    return options;
  }

  _fill(el, id) {
    if (!el) return;
    const state = id && this._hass.states[id];
    if (!state || state.state === UNAVAILABLE) {
      el.disabled = true;
      return;
    }
    el.disabled = false;
    const options = this._options(state);
    const signature = options.join("\n");
    if (el._signature !== signature) {
      el._signature = signature;
      el.innerHTML = options
        .map((o) => `<option value="${escape(o)}">${escape(this._shown(id, o))}</option>`)
        .join("");
    }
    if (!el.matches(":focus")) el.value = state.state;
  }

  _chips(row) {
    const id = row.dataset.chips;
    const state = this._hass.states[id];
    const usable = this._usable(id);
    const options = state ? this._options(state) : [];
    const signature = options.join("\n");
    if (row._signature !== signature) {
      row._signature = signature;
      const table = row.dataset.part === "fan" ? [[/auto/, "mdi:fan-auto"]] : MODE_ICONS;
      const fallback = row.dataset.part === "fan" ? "mdi:fan" : "mdi:tune-variant";
      row.innerHTML = options
        .map((o) => this._pill(`data-option="${escape(o)}"`, iconFrom(table, o, fallback), this._shown(id, o)))
        .join("");
    }
    for (const chip of row.children) {
      chip.disabled = !usable;
      chip.classList.toggle("on", Boolean(state) && chip.dataset.option === state.state);
    }
  }

  _dial(id) {
    const root = this.shadowRoot;
    const state = this._hass.states[id];
    const value = this._stepperValue(id);
    const big = root.querySelector(`[data-big="${cssEscape(id)}"]`);
    const usable = this._usable(id) && value !== undefined;
    if (big) {
      const unit = state && state.attributes.unit_of_measurement;
      big.textContent =
        value === undefined ? "—" : `${value.toFixed(this._decimals(this._range(state).step))}${unit ? ` ${unit}` : ""}`;
    }
    for (const button of root.querySelectorAll(`[data-step="${cssEscape(id)}"]`)) {
      const { min, max } = this._range(state || { attributes: {} });
      const delta = Number(button.dataset.delta);
      button.disabled = !usable || (delta < 0 ? value <= min : value >= max);
    }
  }

  _slide(id) {
    const root = this.shadowRoot;
    const el = root.querySelector(`[data-number="${cssEscape(id)}"]`);
    const out = root.querySelector(`[data-out="${cssEscape(id)}"]`);
    const state = this._hass.states[id];
    // A figure only when it is one: unavailable and unknown are words, and a
    // slider handed a word sits at its middle as if that were the value.
    const known = state !== undefined && state.state !== "" && !Number.isNaN(Number(state.state));
    if (el) {
      el.disabled = !this._usable(id);
      if (state) {
        el.min = state.attributes.min ?? 0;
        el.max = state.attributes.max ?? 100;
        el.step = state.attributes.step ?? 1;
      }
      if (known && !el.matches(":focus")) el.value = state.state;
    }
    if (out) {
      const unit = known ? state.attributes.unit_of_measurement || "" : "";
      out.textContent = !known
        ? "—"
        : unit === "s"
          ? clock(Number(state.state))
          : `${state.state}${unit ? ` ${unit}` : ""}`;
    }
  }
}

const STYLE = `
  <style>
    ha-card { padding: 16px; }
    [hidden] { display: none !important; }
    .title { font-size: 1.4em; font-weight: 700; letter-spacing: -.01em;
             margin: 0 0 14px; color: var(--primary-text-color); }
    .cap { font-size: .72em; letter-spacing: .05em; text-transform: uppercase;
           color: var(--secondary-text-color); }
    .note { color: var(--secondary-text-color); text-align: center; padding: 24px 8px; }
    .warn { display: flex; gap: 10px; align-items: center; padding: 12px 14px;
            border-radius: 16px; margin-bottom: 14px; font-weight: 600;
            color: #7a3d00; background: #ffedd5; border: 1px solid rgba(234,120,20,.4); }
    .warn .dot { width: 26px; height: 26px; border-radius: 50%; flex: 0 0 26px;
                 background: #ea7814; color: #fff; display: flex; align-items: center;
                 justify-content: center; --mdc-icon-size: 18px; }
    .stats { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
             margin-bottom: 18px; }
    .stat { display: flex; flex-direction: column; gap: 4px; padding: 0 14px;
            border-left: 1px solid var(--divider-color); min-width: 0; }
    .stat:first-child { border-left: none; padding-left: 0; }
    .stat .num { font-size: 1.25em; font-weight: 700; color: var(--primary-text-color); }
    .stat .sub { font-size: .85em; color: var(--secondary-text-color); }
    .programme, .stepper { display: flex; align-items: center; justify-content: space-between;
                 gap: 12px; padding: 14px 16px; border-radius: 16px; margin-bottom: 16px;
                 background: var(--card-background-color, #fff);
                 box-shadow: 0 1px 3px rgba(0,0,0,.10); }
    .dial { display: flex; align-items: center; gap: 14px; }
    .dial .big { font-size: 1.8em; font-weight: 700; min-width: 3.5em; text-align: center;
                 color: var(--primary-text-color); }
    .step { width: 40px; height: 40px; border-radius: 50%; cursor: pointer; display: flex;
            align-items: center; justify-content: center; --mdc-icon-size: 20px;
            border: 1px solid var(--divider-color); background: var(--secondary-background-color);
            color: var(--primary-text-color); }
    .step:disabled { opacity: .4; cursor: default; }
    .row { margin-bottom: 14px; }
    .row .cap { display: block; margin-bottom: 8px; }
    .picker { font: inherit; padding: 9px 12px; border-radius: 12px;
              color: var(--primary-text-color); background: var(--secondary-background-color);
              border: 1px solid var(--divider-color); }
    .picker.prog { font-weight: 700; color: var(--primary-color); text-align: right;
                   border: none; background: transparent; max-width: 60%; }
    .opts-head { font-weight: 700; margin: 4px 0 10px; color: var(--primary-text-color); }
    .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .row .opts { margin-bottom: 0; }
    .fields { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
    .field { display: flex; flex-direction: column; gap: 5px; flex: 1 1 140px; min-width: 120px; }
    .field.slider b { font-weight: 700; color: var(--primary-text-color); }
    .field .picker, .field input[type=range] { width: 100%; }
    .quick { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
    .pill { display: inline-flex; align-items: center; gap: 8px; font: inherit;
            cursor: pointer; padding: 9px 15px 9px 12px; border-radius: 999px;
            border: 1px solid var(--divider-color); background: transparent;
            color: var(--primary-text-color); transition: all .2s ease; --mdc-icon-size: 20px; }
    .pill ha-icon { color: var(--secondary-text-color); pointer-events: none; }
    .pill span { pointer-events: none; }
    .pill.on { border-color: var(--primary-color); color: var(--primary-color);
               background: color-mix(in srgb, var(--primary-color) 12%, transparent);
               font-weight: 600; }
    .pill.on ha-icon { color: var(--primary-color); }
    .actions { display: flex; gap: 10px; }
    .actions button { flex: 1; display: inline-flex; align-items: center; justify-content: center;
                      gap: 8px; font: inherit; font-weight: 700; cursor: pointer; padding: 14px;
                      border-radius: 14px; border: none; --mdc-icon-size: 20px; }
    .go { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    .stop { background: var(--secondary-background-color); color: var(--primary-text-color); }
    .actions button:disabled { opacity: .5; cursor: default; }
    .pill:disabled, .picker:disabled, input[type=range]:disabled { opacity: .5; cursor: default; }
  </style>`;

class AegCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    const kind = this.constructor.kind;
    if (!this._form) {
      const noun = kind.noun[0].toUpperCase() + kind.noun.slice(1);
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({ device: noun, name: "Name (optional)" })[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { type: `custom:${kind.tag}`, ...event.detail.value } },
          })
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "device", required: true, selector: { device: { integration: "aeg" } } },
      { name: "name", selector: { text: {} } },
    ];
  }
}

window.customCards = window.customCards || [];
for (const kind of KINDS) {
  if (!customElements.get(kind.tag)) {
    customElements.define(
      kind.tag,
      class extends AegCard {
        static get kind() {
          return kind;
        }
      }
    );
    customElements.define(
      `${kind.tag}-editor`,
      class extends AegCardEditor {
        static get kind() {
          return kind;
        }
      }
    );
  }
  if (!window.customCards.some((c) => c.type === kind.tag)) {
    window.customCards.push({
      type: kind.tag,
      name: kind.name,
      description: kind.description,
      preview: true,
    });
  }
}
