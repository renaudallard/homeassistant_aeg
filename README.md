<p align="center">
  <img src="assets/header.png" alt="AEG appliances for Home Assistant" width="640"/>
</p>

<p align="center">
  <a href="https://github.com/renaudallard/homeassistant_aeg/releases/latest">
    <img src="https://img.shields.io/github/v/release/renaudallard/homeassistant_aeg?label=version&style=flat-square&sort=semver" alt="Latest release"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_aeg/releases">
    <img src="https://img.shields.io/github/downloads/renaudallard/homeassistant_aeg/total?style=flat-square&label=downloads" alt="Downloads"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_aeg/actions/workflows/validate.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/renaudallard/homeassistant_aeg/validate.yml?style=flat-square&label=hacs%20%2F%20hassfest" alt="Validate"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_aeg/actions/workflows/test.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/renaudallard/homeassistant_aeg/test.yml?style=flat-square&label=tests" alt="Tests"/>
  </a>
  <a href="https://www.home-assistant.io/">
    <img src="https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5?logo=home-assistant&logoColor=white&style=flat-square" alt="Home Assistant"/>
  </a>
  <a href="https://hacs.xyz">
    <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square" alt="HACS"/>
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/github/license/renaudallard/homeassistant_aeg?style=flat-square" alt="License"/>
  </a>
  <a href="https://www.paypal.me/RenaudAllard">
    <img src="https://img.shields.io/badge/PayPal-Donate-blue.svg?logo=paypal&style=flat-square" alt="PayPal"/>
  </a>
</p>

---

Home Assistant integration for **AEG appliances**, talking to the Electrolux OCP
cloud the way the AEG OneApp does. Pair the appliance with the vendor app once,
then drive it from here.

**Nothing in it knows what a washing machine is.** Every appliance describes
itself, field by field, and the entities are built from that description, so a
model nobody has tried works the same way as the one this was written against.

> Unofficial. Not affiliated with, endorsed by, or supported by AEG or
> Electrolux. Targets Home Assistant **2026.9 or newer**, which itself needs
> Python 3.14.2.

## Highlights

- **Built from what the appliance says** — a command becomes a button, a
  settable flag a switch, a choice a select, a bounded number a number. No
  per-model tables, and no list of appliance types to keep up to date.
- **Only what it will accept** — an appliance also says what it will take right
  now. A washing machine offers START when it is ready to start and PAUSE once
  it is running, freezes its settings mid-cycle, and offers nothing at all
  until remote control has been armed at the machine itself.
- **Live, not polled** — the cloud pushes changes over a websocket, so a cycle
  finishing shows up when it happens. Polling carries on in the background at a
  slower rate to catch whatever a dropped connection missed.
- **Readable readings** — a duration gets a second reading written as a clock,
  a numbered scale reads as its numbers, and whatever the machine is
  complaining about arrives as one problem sensor carrying the codes.
- **Both ways in** — a password, or a one time code mailed to the account,
  which is the only way in for an account that has no password.
- **Quiet by default** — a washing machine describes about 120 fields and most
  of them are the machine talking to itself. The maintenance counters, stored
  cycles and network stack arrive as diagnostics and start disabled; fields the
  model does not have get no entity at all.

## Installing

Add this repository to [HACS](https://hacs.xyz) as a custom repository of
category **Integration** and install it from there, or copy
`custom_components/aeg` into the `custom_components` directory of your Home
Assistant configuration by hand. Either way, restart, then add **AEG** from
*Settings → Devices & services*.

The flow asks how the account signs in, because that cannot be looked up, and
takes either a password or a code sent to the address. The country picks the
server the appliances are on, so it has to be the one the account was
registered in.

Tokens are written into the config entry and renewed in the background. If they
stop working, Home Assistant asks you to sign in again rather than failing
quietly.

## What you get

| The appliance says | You get |
| --- | --- |
| a command, and the commands it takes | a button each |
| a flag it will let you set | a switch |
| a flag it only reports | a binary sensor |
| what it is complaining about | a problem binary sensor, with the codes |
| a choice, and the values it takes | a select |
| a number with a range | a number |
| a length of time | a sensor in seconds, and one reading as a clock |
| anything else it reports | a sensor |

A washing machine comes out as about 67 entities with 47 of them shown: the
programme and its 35 cycles, temperature, spin speed, extra rinse, steam, time
manager, the door, and buttons for on, off, start, pause, resume and reset.
Enable the rest from the device page if you want them.

Two details worth knowing, because they look like faults and are not:

- **The command buttons are unavailable until remote control is armed** at the
  machine. A washer reporting `NOT_SAFETY_RELEVANT_ENABLED` will not take a
  remote start, and the app greys the same buttons out.
- **Water hardness and the softener mode go read-only** while a cycle is
  running, delayed, paused or has just ended. That is the appliance's own rule.

A value that is a name and a number is a step in a scale. Water hardness is
seven steps, and a washing machine names the first three and numbers the rest;
where the numbered steps land on their own place the whole list reads one to
seven. The appliance still hears the name it uses.

## What is not done

- **Nothing has been written to an appliance yet.** Reading is well covered
  against a real machine; the switches, selects, numbers and buttons have never
  been exercised against one, and the shape a command is sent in is inferred
  from the shape state comes back in.
- **Onboarding is out of scope.** Pair new hardware with the vendor app.
- **Nothing is translated.** Entity names come from the appliance's own field
  names, so some of them read awkwardly.

## How the login works

Signing in takes two services, and the order matters.

1. `POST /one-account-authorization/api/v1/token` with a **client credentials**
   grant authorises the application itself. The lookup in the next step is not
   anonymous, so nothing works without this. It is the only call carrying the
   client secret.
2. `GET /one-account-user/api/v1/identity-providers`, carrying that token, says
   which Gigya tenant the account belongs to and which regional endpoint its
   appliances live behind. Nothing about the region is hardcoded.
3. Gigya authenticates the user, by password or by mailed code, and
   `accounts.getJWT` mints a JWT for the session. That call is signed with
   HMAC-SHA1 over the session secret.
4. `POST /one-account-authorization/api/v1/token` trades the JWT for an access
   token and a refresh token, **against the regional endpoint** rather than the
   global one. Its country header comes from the country claim inside the JWT,
   which is what that field is asked of Gigya for.

The app posts steps 1 and 4 to **v2** of the token endpoint with snake_case
field names. That answers 400 here, so v1 with the camelCase names the rest of
the API uses is what this sends, in the request and reading the reply.

The refresh token rotates on every renewal, so whatever holds it has to write
the new one back; the client reports each new pair through a listener for that
reason. Renewing a token that was issued moments earlier is refused with a 429,
which is not a failure while the token in hand still works, so it is kept.

## Where the protocol knowledge comes from

From the AEG OneApp Android package, version 4.30, read with apktool and jadx.
The app is obfuscated, and jadx fails outright on the two classes that matter
most for authentication, so parts of this were read from smali.

The Gigya signature is pinned by tests against values cross checked with
[pyelectroluxocp](https://github.com/Woyken/py-electrolux-ocp), an independent
client known to work against the live service.

Two details could not be read out of the package and were settled by running
`tools/check_login.py` against a real account: asking Gigya for a **mobile**
target does return a session that can sign, and the signature wants **plain
base64**, not the URL safe encoding the Android SDK uses.

## Branding

`custom_components/aeg/brand/` holds the four PNGs that home-assistant/brands
expects under `custom_integrations/aeg/`, ready to copy into a fork of that
repository. They live inside the integration because that is where HACS looks
for them until the brands pull request lands. `assets/` holds the repository
banner and the favicons.

They all come from the AEG application icon and are regenerated by
`tools/make_icons.py`, which needs Pillow. The source is 240 pixels square, so
the 512 pixel icon is an upscale and is softer than the others. The banner is
not a crop, since there is no 4:1 image to cut: it rebuilds the gradient at
banner size and lays the wordmark over it.

The AEG name and logo belong to AEG. They are here to identify the appliances
this integration talks to, the same way every other manufacturer logo appears
in home-assistant/brands.

## Development

    ruff check .
    ruff format --check .
    mypy custom_components/ tests/ tools/
    pytest tests/

`aiohttp` is the only runtime dependency, and Home Assistant ships it. The
checks need `homeassistant` and `pytest-homeassistant-custom-component`, and
`tools/make_icons.py` needs Pillow. None of those are needed to run the
integration. The decompiled app and the scratch work live in `tmp/`, which is
not tracked, as is the app package itself.

The tests load a real washing machine, dumped from an account with the
identifiers removed, and check what comes out of it. The config flow tests
drive the real Home Assistant flow machinery with the cloud mocked at the two
classes the flow talks to, so they cover which step follows which, what lands
in the config entry, and which message a failure puts on the form.

Two workflows run on every push: **Tests** runs the lint, the type check and
the suite, and **Validate** runs HACS validation and hassfest. Neither of the
latter two runs locally, so that workflow is the first sign of a manifest
problem.

### Checking a login by hand

`tools/check_login.py` walks the whole login against a real account, from the
provider lookup through to reading an appliance capability tree, and says which
step fails and why. Press enter at the password prompt to take the mailed code
path instead.

    python tools/check_login.py you@example.com BE
    python tools/check_login.py you@example.com BE --dump tmp/appliances

It logs every request and every answer. Everything that says who you are or
which machine is yours is replaced by a note of how long it was, in bodies and
in paths alike: tokens, keys, codes, the address, the name and town on the
account, and the appliance ids. What kind of appliance it is and what it is
doing stay readable, because a log without those is not worth keeping. That
makes the output safe to paste into a bug report. Pass `-q` to log only
failures.

`--dump` writes each appliance's capability tree and reported state out as
JSON, redacted the same way. That is what the entity mapping is built against.
