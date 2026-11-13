// A Lovelace card that lays a washing machine out the way the AEG app does,
// and drives it the same way: what it is doing and how long it has left, the
// programme on a card of its own, the wash settings and options it offers,
// and a start, a pause and a stop, with a warning across the top when the
// door is open or remote control has not been armed at the machine.
//
// The integration builds its entities from what the appliance says about
// itself, and this reads them the same way: each control is found by what it
// is rather than by a list held per model, so a washer nobody has seen still
// gets a card with its own settings on it. A setting the current programme
// does not take goes unavailable, and its control greys out with it.
//
// Bundled with the aeg integration, which serves this file and adds it as a
// dashboard resource, so there is no resource to add by hand.

const CARD = "aeg-washer-card";

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
};

// The time left is a reading in seconds with a clock beside it, and the two
// share a translation key. Only the one in seconds is a duration.
const REMAINING = "time_to_end";

// The command buttons are named after the field and the command, neither of
// which is translated, so their ids end the same way in every language.
const COMMAND = /^button\..*_execute_command_(on|off|start|pause|resume|stopreset)$/;

// Which of the roles above an entity plays, if any.
function role(id, entity, states) {
  for (const [name, [domain, keys]] of Object.entries(KEYED)) {
    if (id.startsWith(`${domain}.`) && keys.includes(entity.translation_key)) return name;
  }
  if (id.startsWith("sensor.") && entity.translation_key === REMAINING) {
    const state = states && states[id];
    if (state && state.attributes.device_class === "duration") return "remaining";
  }
  const command = COMMAND.exec(id);
  return command ? command[1] : null;
}

// What an appliance says, in a form worth reading. These appliances shout
// and run their words together with underscores, and a programme carries its
// family in front of its name: COTTON_PR_ECO40-60 is the eco 40-60 cottons
// programme. A value that is not shouted is left as it came.
function words(value) {
  const raw = String(value);
  if (!/^[A-Z0-9][A-Z0-9_+\-.]*$/.test(raw)) return raw;
  let text = raw;
  const cut = text.indexOf("_PR_");
  if (cut >= 0) text = text.slice(cut + 4);
  const unit = /^(\d+)_(RPM|CELSIUS|FAHRENHEIT)$/.exec(text);
  if (unit) return `${unit[1]} ${{ RPM: "rpm", CELSIUS: "°C", FAHRENHEIT: "°F" }[unit[2]]}`;
  text = text.replace(/_+/g, " ").trim().toLowerCase();
  return text ? text[0].toUpperCase() + text.slice(1) : raw;
}

// An icon for an option, chosen by what its name is about.
const ICONS = [
  [/temperature/, "mdi:thermometer"],
  [/spin/, "mdi:rotate-right"],
  [/steam/, "mdi:weather-fog"],
  [/prewash|soak/, "mdi:water-outline"],
  [/rinse/, "mdi:water"],
  [/stain/, "mdi:spray-bottle"],
  [/night|silent|quiet/, "mdi:weather-night"],
  [/crease|iron/, "mdi:iron"],
  [/load|weight/, "mdi:scale"],
  [/time|quick|finish|start/, "mdi:timer-outline"],
  [/eco|energy/, "mdi:leaf"],
  [/dry/, "mdi:tumble-dryer"],
];

function iconFor(label) {
  const text = String(label).toLowerCase();
  for (const [pattern, icon] of ICONS) if (pattern.test(text)) return icon;
  return "mdi:tune-variant";
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

// A washing machine is an appliance with a programme to pick and a time left
// to count down. An oven has the first and not the second, an air
// conditioner neither.
function washers(hass) {
  const entities = (hass && hass.entities) || {};
  const found = {};
  for (const id of Object.keys(entities)) {
    const entity = entities[id];
    if (entity.platform !== "aeg" || !entity.device_id) continue;
    const name = role(id, entity, hass.states);
    if (name !== "programme" && name !== "remaining") continue;
    (found[entity.device_id] = found[entity.device_id] || new Set()).add(name);
  }
  return Object.keys(found).filter((device) => found[device].size === 2);
}

// The appliance states in which a pause or a resume is the thing to offer.
const PAUSABLE = new Set(["RUNNING", "DELAYED_START"]);

class AegWasherCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._signature = null;
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
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const devices = washers(hass);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  _device() {
    if (this._config.device) return this._config.device;
    const devices = washers(this._hass);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // The machine's entities sorted into what each is for: the ones with a
  // role, and then the wash settings by their kind. What configures the
  // machine rather than the wash carries a category, so it is stepped over.
  _controls(device) {
    const found = { switches: [], selects: [], numbers: [] };
    const entities = (this._hass && this._hass.entities) || {};
    if (!device) return found;
    for (const id of Object.keys(entities)) {
      const entity = entities[id];
      if (entity.device_id !== device || entity.platform !== "aeg") continue;
      if (!this._hass.states[id]) continue;
      const name = role(id, entity, this._hass.states);
      if (name) found[name] = id;
      if (name || entity.entity_category || entity.hidden) continue;
      if (id.startsWith("switch.")) found.switches.push(id);
      else if (id.startsWith("select.")) found.selects.push(id);
      else if (id.startsWith("number.")) found.numbers.push(id);
    }
    for (const key of ["switches", "selects", "numbers"]) found[key].sort();
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
    if (!id) return;
    this._hass.callService(domain, service, { entity_id: id, ...(extra || {}) });
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
    const options = [...found.switches, ...found.selects, ...found.numbers].join(",");
    const signature = `${device || ""}|${named}|${options}|${this._machine() || ""}`;
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, found);
    }
    this._paint(found);
  }

  _build(device, found) {
    const title = this._config.name || this._machine() || "Washing machine";
    const note = !device
      ? washers(this._hass).length
        ? "More than one washing machine here. Set 'device' to the one you mean."
        : "No washing machine found on this system."
      : "";
    if (note) {
      this.shadowRoot.innerHTML = `${STYLE}
        <ha-card><div class="title">${escape(title)}</div>
        <div class="note">${escape(note)}</div></ha-card>`;
      return;
    }

    const status = `<div class="stats">
        <div class="stat"><span class="cap">Status</span><span class="num" data-k="state">—</span>
          <span class="sub" data-k="phase"></span></div>
        <div class="stat"><span class="cap">Time left</span><span class="num" data-k="remaining">—</span></div>
        <div class="stat"><span class="cap">Ends at</span><span class="num" data-k="ends">—</span></div>
      </div>`;

    const programme = found.programme
      ? `<label class="programme"><span class="cap">Programme</span><select class="picker prog" data-role="programme"></select></label>`
      : "";

    const choosers = found.selects
      .map(
        (id) => `<label class="field"><span class="cap">${escape(this._label(id))}</span>
          <select class="picker" data-select="${escape(id)}"></select></label>`
      )
      .join("");
    const chips = found.switches
      .map(
        (id) => `<button class="pill" data-switch="${escape(id)}" type="button">
          <ha-icon icon="${iconFor(this._label(id))}"></ha-icon><span>${escape(this._label(id))}</span>
        </button>`
      )
      .join("");
    const sliders = found.numbers
      .map(
        (id) => `<label class="field slider"><span class="cap">${escape(this._label(id))}
          <b data-out="${escape(id)}"></b></span>
          <input type="range" data-number="${escape(id)}"></label>`
      )
      .join("");
    const settings =
      choosers || chips || sliders
        ? `<div class="opts-head">Settings</div>
           ${choosers ? `<div class="fields">${choosers}</div>` : ""}
           ${chips ? `<div class="opts">${chips}</div>` : ""}
           ${sliders ? `<div class="fields">${sliders}</div>` : ""}`
        : "";

    const quick = [];
    if (found.on || found.off)
      quick.push(
        `<button class="pill" data-role="power" type="button"><ha-icon icon="mdi:power"></ha-icon><span>Power</span></button>`
      );
    if (found.lock)
      quick.push(
        `<button class="pill" data-role="lock" type="button"><ha-icon icon="mdi:lock"></ha-icon><span>${escape(this._label(found.lock))}</span></button>`
      );

    const actions =
      found.start || found.pause || found.resume || found.stopreset
        ? `<div class="actions">
             <button class="go" type="button"><ha-icon icon="mdi:play"></ha-icon><span>Start</span></button>
             <button class="stop" type="button"><ha-icon icon="mdi:stop"></ha-icon><span>Stop</span></button>
           </div>`
        : "";

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="title">${escape(title)}</div>
        <div class="warn" data-warn="door" hidden>
          <span class="dot"><ha-icon icon="mdi:exclamation"></ha-icon></span>
          <span>The door is open.</span>
        </div>
        <div class="warn" data-warn="remote" hidden>
          <span class="dot"><ha-icon icon="mdi:remote-off"></ha-icon></span>
          <span data-text="remote"></span>
        </div>
        <div class="warn" data-warn="alerts" hidden>
          <span class="dot"><ha-icon icon="mdi:alert"></ha-icon></span>
          <span data-text="alerts"></span>
        </div>
        ${status}
        ${programme}
        ${settings}
        ${quick.length ? `<div class="quick">${quick.join("")}</div>` : ""}
        ${actions}
      </ha-card>`;
    this._wire();
  }

  _wire() {
    const root = this.shadowRoot;
    const prog = root.querySelector('[data-role="programme"]');
    if (prog)
      prog.addEventListener("change", () =>
        this._call(this._found.programme, "select", "select_option", { option: prog.value })
      );
    const power = root.querySelector('[data-role="power"]');
    if (power)
      power.addEventListener("click", () => this._press(this._powerCommand()));
    const lock = root.querySelector('[data-role="lock"]');
    if (lock)
      lock.addEventListener("click", () => this._call(this._found.lock, "switch", "toggle"));
    for (const pill of root.querySelectorAll("[data-switch]"))
      pill.addEventListener("click", () => this._call(pill.dataset.switch, "switch", "toggle"));
    for (const el of root.querySelectorAll("[data-select]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.select, "select", "select_option", { option: el.value })
      );
    for (const el of root.querySelectorAll("[data-number]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.number, "number", "set_value", { value: Number(el.value) })
      );
    const go = root.querySelector(".go");
    if (go) go.addEventListener("click", () => this._press(this._goCommand()));
    const stop = root.querySelector(".stop");
    if (stop) stop.addEventListener("click", () => this._press("stopreset"));
  }

  _press(command) {
    const id = command && this._found[command];
    if (id && this._usable(id)) this._call(id, "button", "press");
  }

  // The machine is on unless it says it is off. Pressing the power pill sends
  // whichever of the two it does not say it is.
  _isOn() {
    const state = this._value(this._found.state);
    return state !== undefined && state !== UNAVAILABLE && state !== "unknown" && state !== "OFF";
  }

  _powerCommand() {
    return this._isOn() ? "off" : "on";
  }

  // One button for start, pause and resume, as on the machine's own panel.
  // The appliance says which of those it will take right now, which is what
  // the buttons being available or not reflects; where it will take none,
  // the one its state calls for is shown greyed out.
  _goCommand() {
    for (const command of ["resume", "pause", "start"])
      if (this._usable(this._found[command])) return command;
    const state = this._value(this._found.state);
    if (state === "PAUSED") return "resume";
    if (PAUSABLE.has(state)) return "pause";
    return "start";
  }

  _paint(found) {
    const root = this.shadowRoot;
    if (!root || root.querySelector(".note")) return;

    const show = (name, on) => {
      const el = root.querySelector(`[data-warn="${name}"]`);
      if (el) el.hidden = !on;
    };
    show("door", this._value(found.door) === "OPEN");
    const remote = REMOTE.get(this._value(found.remote));
    show("remote", Boolean(remote));
    if (remote) root.querySelector('[data-text="remote"]').textContent = remote;
    const alerts = this._value(found.alerts) === "on";
    show("alerts", alerts);
    if (alerts) {
      const codes = this._hass.states[found.alerts].attributes.alerts;
      const list = Array.isArray(codes) && codes.length ? codes.map(words).join(", ") : "";
      root.querySelector('[data-text="alerts"]').textContent = list
        ? `The machine reports: ${list}.`
        : "The machine reports an alert.";
    }

    const state = this._value(found.state);
    root.querySelector('[data-k="state"]').textContent =
      state === undefined || state === UNAVAILABLE || state === "unknown"
        ? "—"
        : this._shown(found.state, state);
    const phase = this._value(found.phase);
    root.querySelector('[data-k="phase"]').textContent =
      phase && !QUIET_PHASES.has(phase) ? this._shown(found.phase, phase) : "";
    const left = Number(this._value(found.remaining));
    root.querySelector('[data-k="remaining"]').textContent = left > 0 ? clock(left) : "—";
    root.querySelector('[data-k="ends"]').textContent = this._when(this._value(found.ends));

    this._fill(root.querySelector('[data-role="programme"]'), found.programme);
    for (const id of found.selects)
      this._fill(root.querySelector(`[data-select="${cssEscape(id)}"]`), id);

    // A setting belongs to a programme and goes unavailable with it. Home
    // Assistant drops a call to an unavailable entity, so its control is
    // greyed out rather than left to do nothing when used.
    for (const id of found.switches) {
      const pill = root.querySelector(`[data-switch="${cssEscape(id)}"]`);
      if (!pill) continue;
      pill.disabled = !this._usable(id);
      pill.classList.toggle("on", this._value(id) === "on");
    }
    for (const id of found.numbers) this._slide(id);

    const power = root.querySelector('[data-role="power"]');
    if (power) {
      power.classList.toggle("on", this._isOn());
      power.disabled = !this._usable(found[this._powerCommand()]);
    }
    const lock = root.querySelector('[data-role="lock"]');
    if (lock) {
      lock.classList.toggle("on", this._value(found.lock) === "on");
      lock.disabled = !this._usable(found.lock);
    }

    const go = root.querySelector(".go");
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

  // A finishing time as a clock time, with the day in front when it is not
  // today, as a delayed start can be.
  _when(value) {
    if (!value || value === UNAVAILABLE || value === "unknown") return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const language = (this._hass.locale && this._hass.locale.language) || this._hass.language;
    const time = date.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === new Date().toDateString()) return time;
    return `${date.toLocaleDateString(language, { weekday: "short" })} ${time}`;
  }

  _fill(el, id) {
    if (!el) return;
    const state = id && this._hass.states[id];
    if (!state || state.state === UNAVAILABLE) {
      el.disabled = true;
      return;
    }
    el.disabled = false;
    const options = ordered(state.attributes.options || []);
    // The current value is shown even when the appliance has left it off the
    // list, so the picker never claims a setting the machine is not on.
    if (!options.includes(state.state) && state.state !== "unknown") options.unshift(state.state);
    const signature = options.join("\n");
    if (el._signature !== signature) {
      el._signature = signature;
      el.innerHTML = options
        .map((o) => `<option value="${escape(o)}">${escape(this._shown(id, o))}</option>`)
        .join("");
    }
    if (!el.matches(":focus")) el.value = state.state;
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

// The cloud hands values over in alphabetical order, which puts 1000 rpm
// before 400. Where every value starts with its number they are put in the
// order of those numbers instead; the appliance still hears its own words.
function ordered(options) {
  const list = [...options];
  if (list.length > 1 && list.every((o) => /^\d/.test(o)))
    list.sort((a, b) => parseFloat(a) - parseFloat(b));
  return list;
}

// What the start button reads as, by the command it sends.
const GO = {
  start: ["mdi:play", "Start"],
  pause: ["mdi:pause", "Pause"],
  resume: ["mdi:play", "Resume"],
};

// What remote control says when it will not take a start from here.
const REMOTE = new Map([
  ["DISABLED", "Remote control is off at the machine."],
  ["NOT_SAFETY_RELEVANT_ENABLED", "Remote start is not armed at the machine."],
  ["TEMPORARY_LOCKED", "Remote control is locked at the machine for now."],
]);

// Phases that say nothing about where the wash has got to.
const QUIET_PHASES = new Set(["UNAVAILABLE", "CYCLE_PHASE_HIDDEN", "unavailable", "unknown"]);

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
    .programme { display: flex; align-items: center; justify-content: space-between;
                 gap: 12px; padding: 14px 16px; border-radius: 16px; margin-bottom: 16px;
                 background: var(--card-background-color, #fff);
                 box-shadow: 0 1px 3px rgba(0,0,0,.10); }
    .picker { font: inherit; padding: 9px 12px; border-radius: 12px;
              color: var(--primary-text-color); background: var(--secondary-background-color);
              border: 1px solid var(--divider-color); }
    .picker.prog { font-weight: 700; color: var(--primary-color); text-align: right;
                   border: none; background: transparent; max-width: 60%; }
    .opts-head { font-weight: 700; margin: 4px 0 10px; color: var(--primary-text-color); }
    .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .fields { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
    .field { display: flex; flex-direction: column; gap: 5px; flex: 1 1 140px; min-width: 120px; }
    .field.slider b { font-weight: 700; color: var(--primary-text-color); }
    .field .picker, .field input[type=range] { width: 100%; }
    .quick { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
    .pill { display: inline-flex; align-items: center; gap: 8px; font: inherit;
            cursor: pointer; padding: 9px 15px 9px 12px; border-radius: 999px;
            border: 1px solid var(--divider-color); background: transparent;
            color: var(--primary-text-color); transition: all .2s ease; --mdc-icon-size: 20px; }
    .pill ha-icon { color: var(--secondary-text-color); }
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

class AegWasherCardEditor extends HTMLElement {
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
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({ device: "Washing machine", name: "Name (optional)" })[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { type: `custom:${CARD}`, ...event.detail.value } },
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

if (!customElements.get(CARD)) {
  customElements.define(CARD, AegWasherCard);
  customElements.define(`${CARD}-editor`, AegWasherCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "AEG Washing Machine",
    description: "A washing machine laid out and driven the way the AEG app does it.",
    preview: true,
  });
}
