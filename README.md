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

Home Assistant integration for **AEG and Electrolux appliances**, talking to
the Electrolux OCP cloud the way the OneApp does. Pair the appliance with the
vendor app once, then drive it from here.

**Nothing in it knows what a washing machine is.** Every appliance describes
itself, field by field, and the entities are built from that description, so a
model nobody has tried works the same way as the one this was written against.

> Unofficial. Not affiliated with, endorsed by, or supported by AEG or
> Electrolux. Targets Home Assistant **2026.9 or newer**, which itself needs
> Python 3.14.2. The domain stays `aeg`, so an entry made before Electrolux
> accounts were understood keeps working untouched.

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
  slower rate to catch whatever a dropped connection missed, and a look is
  arranged for just after an appliance says it is about to finish, because the
  end of a cycle is the one thing the cloud regularly forgets to mention.
- **Kept as history** — a reading that is a number says so, which is what
  makes Home Assistant graph it and keep it. A cycle counter is added up
  rather than averaged. Nothing claims a unit an appliance has not made
  plain: a percentage of humidity, parts per million of carbon dioxide and
  micrograms of particulates are named, and a load weight is left as the
  number the machine reports.
- **Readable readings** — a duration gets a second reading written as a clock,
  and the time left to a cycle counts down by the second rather than waiting to
  be told. There is a **finishes at** timestamp beside it. A scale whose steps
  say their own numbers reads as those numbers, and whatever the machine is
  complaining about arrives as one problem sensor with the codes.
- **Both ways in** — a password, or a one time code mailed to the account,
  which is the only way in for an account that has no password.
- **Either brand** — AEG and Electrolux are two builds of the same app in
  front of the same cloud. Which one an account was made in decides only how
  this signs in, so both are offered and the rest is identical.
- **Named for what it is** — an account listing calls every washing machine
  WM, so the device page asks the appliance separately what model it is and
  shows that, with the product number beside it.
- **Kept between starts** — a capability tree is fifty kilobytes and describes
  the model rather than what it is doing. An appliance publishes a hash of its
  own capabilities, so the tree is fetched again only when that says it is
  worth fetching. What the appliance is goes in the same place and is asked
  for once, being one answer for the life of the machine.
- **Quiet by default** — a washing machine describes about 120 fields and most
  of them are the machine talking to itself. The maintenance counters, stored
  cycles and network stack arrive as diagnostics and start disabled; fields the
  model does not have get no entity at all.
- **Settings kept apart from controls** — water hardness, the panel lock and
  the end of cycle sound are things you set once, so they sit under
  Configuration on the device page rather than among the spin speeds.
- **Two commands it will not hand you** — an appliance describes a command
  that takes it off the account and one that wipes its network unit exactly
  the way it describes start and pause. Those two get no entity, hidden or
  otherwise. Pair and unpair in the vendor app, which is where they belong.

## Installing

Add this repository to [HACS](https://hacs.xyz) as a custom repository of
category **Integration** and install it from there, or copy
`custom_components/aeg` into the `custom_components` directory of your Home
Assistant configuration by hand. Either way, restart, then add **AEG** from
*Settings → Devices & services*, whichever of the two brands the account is.

The flow asks how the account signs in, because that cannot be looked up, and
takes either a password or a code sent to the address. The country picks the
server the appliances are on, so it has to be the one the account was
registered in. The brand is which app the account was made in: an account
belongs to one of the two and the other's credentials will not reach it.

Tokens are written into the config entry and renewed in the background. If they
stop working, Home Assistant asks you to sign in again rather than failing
quietly. It has to be the same account: signing in as somebody else is refused
rather than quietly pointing the entry at another household's appliances.

**Reconfigure** on the entry signs in again without waiting to be asked, which
is how to correct the country. Picking the wrong one leaves the entry talking
to a server the appliances are not on, and setting the integration up again to
fix that would cost every entity id and all the history with them.

An appliance unpaired in the vendor app stops being listed, and its device can
then be deleted from its own page. One that is still on the account cannot: it
would come back on the next look as a new device with nothing behind it.

## What you get

| The appliance says | You get |
| --- | --- |
| a command, and the commands it takes | a button each |
| a flag it will let you set | a switch |
| a flag it only reports | a binary sensor |
| what it is complaining about | a problem binary sensor, with the codes |
| a choice, and the values it takes | a select |
| a number with a range | a number |
| what firmware it is running | an update entity, and whether one is in hand |
| the version its network unit is on | the firmware line on the device page |
| a mode and a target temperature | a thermostat, as well as the parts |
| a length of time | a sensor in seconds, and one reading as a clock |
| how long is left | a clock counting down, and a timestamp of the finish |
| anything else it reports | a sensor |

A washing machine comes out as 69 entities with 54 of them shown: the
programme and its 35 cycles, temperature, spin speed, extra rinse, steam, time
manager, the door, and buttons for on, off, start, pause, resume, reset and
clearing the personalised cycle. Enable the rest from the device page if you
want them.

An appliance added to the account turns up on the next look, which loads the
entry again to read what the new one can do.

The device is named for the model it was sold as, with the product number from
its rating plate beside it. The account listing does not carry either: it gives
the kind of thing an appliance is, so a house of AEG washing machines is a
house of appliances all called WM. Each one is asked what it is once and
remembered. An appliance the cloud will not answer for keeps the type from the
listing, which is where it stood before, and is asked again on the next start.

The firmware on the device page is the network unit's, which is the one an
update is about, so it says the same thing as the update entity rather than a
second version that disagrees with it.

A capability tree covers a range of models, so it describes fields a given
machine does not have. Those get no entity, and one left over from an earlier
version is taken away, but only once the appliance has been reachable and has
never reported the field. An appliance that is asleep or quiet keeps
everything it has, and so does one the account left out of a listing, along
with the record of what it has been seen reporting.

Every appliance also gets a **connection** sensor. When the cloud stops calling
an appliance reachable, what it last said stays readable, so a wash can be
looked at afterwards; the connection sensor is what says the machine has gone,
rather than every other entity saying it at once. Controls do go unavailable,
since there is nothing to set on an appliance that cannot be reached.

Six details worth knowing, because they look like faults and are not:

- **The command buttons are unavailable until remote control is armed** at the
  machine. A washer reporting `NOT_SAFETY_RELEVANT_ENABLED` will not take a
  remote start, and the app greys the same buttons out. They also go
  unavailable wherever the appliance says it will take no command at all, as an
  oven does while it is waiting out a delayed start.
- **Water hardness and the softener mode go read-only** while a cycle is
  running, delayed, paused or has just ended. That is the appliance's own rule.
- **Steam and stain go read-only below forty degrees**, on a cold wash
  included. That is the appliance's own rule as well.
- **A select offers fewer choices in some states than in others.** An air
  conditioner drops TURBO from its fan speeds in its automatic and fan only
  modes, so the list shrinks with the mode. Whatever it is set to now stays
  on the list either way. The thermostat gathering the same fields up offers
  the same choices.
- **The programme decides what the rest of the wash will take.** A washing
  machine offers six spin speeds on one programme and three on another, and
  the eco programme fixes the temperature at forty and turns economy on, so
  those two controls go unavailable while it is selected. That is the
  appliance's own rule, written into the programme rather than into the
  field, and picking another programme hands the controls back.
- **An appliance can report a temperature twice**, once in each scale, and it
  writes the scale into the field name. Both are read on the scale they are
  on, so two readings that look like the same room temperature under different
  names are the same reading, and agree once Home Assistant has converted them.

The clock counting down cannot drift from what the appliance says, because
every figure that arrives replaces the one being counted from: pick a shorter
programme and it is on the new time as soon as the cloud mentions it. It only
counts down while the appliance says it is running: a washing machine that has
finished puts the length of the programme it is set to back where the time
left was, and counting that down would show a wash nobody has started. It writes
a state every second while a cycle runs, so exclude
`sensor.*_time_to_end_formatted` from the recorder if that history is not worth
keeping. The finishes at timestamp says the same thing and writes nothing
between updates.

Whichever field is counting down is also what says when to look again. Once
less than a minute is left, one look is arranged for seventy seconds later and
no more are until it has been taken, so a machine counting in seconds does not
book sixty of them on its way to zero. That is there because the cloud goes on
pushing the door and the connection while saying nothing about the wash, and
the stream working is exactly what makes polling ease off to ten minutes: the
moment it matters most is the moment the account is otherwise asked least
often.

A handful of fields are drawn by what they say rather than by what they are
called: the door looks open when it is open, the lock looks locked when it is
locked, and the machine shows what it is up to. The rest get a picture guessed
from the name, which costs a wrong picture rather than a wrong reading when it
guesses wrong.

A value that is a name and a number is a step in a scale, and a field whose
values all say their own number is shown as those numbers. The appliance still
hears the name it uses.

A field that names some of its steps and numbers the rest keeps the words it
uses for all of them. Water hardness is seven steps with the first three named,
and the cloud hands values over in alphabetical order, so they arrive as HARD,
MEDIUM, SOFT and nothing in them says which is the first step. Numbering them
off the order they came in would offer the hardest setting as one of seven.

## Reporting a problem

The device page offers to download diagnostics, and that is the one to send:
it carries the whole of what that appliance said about itself, what model it
says it is, what it is reporting, what it will accept right now, and whether
the stream is carrying the updates or polling is. The integration entry offers
the same thing for every appliance on the account at once, which is worth
having only when the trouble is with the account rather than with a machine.

Both are redacted the same way the logs are, so tokens, keys, cookies, the
address on the account and the appliance's own identifier are replaced by a
note of their length, whether they arrived as text or as a number. What kind
of appliance it is, what it is doing, and the codes for whatever it is
complaining about all stay readable.

For a model this has never seen, that download is the one thing a report cannot
do without.

## When the controls go unavailable

An appliance that the cloud has stopped hearing from cannot be set to anything,
so every control on it goes unavailable. Readings stay, holding whatever it
last said. The **connection** sensor says which it is.

An appliance talks to the cloud itself, over MQTT on **port 8883**, not through
Home Assistant. A firewall that blocks outbound 8883 takes the appliance off
the network without anything on the Home Assistant side looking wrong, and
every entity goes unavailable while the integration carries on talking to the
cloud quite happily. Check the connection sensor first, and the appliance's own
network settings after that.

## How the login works

Signing in takes two services, and the order matters. Every step below is the
same for both brands: only the client id, its secret and the API key differ,
and those come from whichever build of the app the account was made in.

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

## Branding

The icons are AEG's, the domain being `aeg` and this having started as an AEG
integration. An Electrolux account gets the same ones.

`custom_components/aeg/brand/` holds the four PNGs that home-assistant/brands
expects under `custom_integrations/aeg/`, ready to copy into a fork of that
repository. Home Assistant has served them from there itself since 2026.3, and
prefers them to anything on the brands CDN. The HACS panel does not read them:
it asks the CDN directly, and shows a logo here only because Electrolux put one
under `aeg` when they added their own brand icons. `assets/` holds the
repository banner and the favicons.

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
drive the real Home Assistant flow machinery, so they cover which step follows
which, what lands in the config entry, and which message a failure puts on the
form.

Nothing in them touches the network. The cloud is stood in for wherever it is
talked to: the calls, the connection it pushes changes over, and the two
classes the config flow signs in through.

Two workflows run on every push: **Tests** runs the lint, the type check and
the suite, and **Validate** runs HACS validation and hassfest. Neither of the
latter two runs locally, so that workflow is the first sign of a manifest
problem.

A third, **Autorelease**, runs only when the version in the manifest changes.
It holds the release back on the same three checks, then tags the commit,
writes the release with the notes running from the tag before it, and puts a
zip of `custom_components/aeg` on it. Releasing is therefore a matter of
bumping the version and pushing. A release written by hand before the workflow
gets there keeps its own notes and is only given the zip, which is how a
release worth writing up properly still gets one.

### Regenerating the names and the translations

`tools/make_names.py` works out which platforms each named field turns up on,
from every capability tree to hand, and writes both the table at the bottom of
`names.py` and the entity text in `strings.json`. Run it after adding a name.

Most of those trees are the ones the app ships, which live in `tmp/base` and
are not in the repository, so a fresh checkout has only the two the tests use.
It refuses to write anything when the trees to hand say nothing about a field
that is already named and placed, rather than quietly dropping two thirds of
the entity text and every translation of it.

`icons.json` holds the fields whose picture moves with their reading, keyed by
the same name the text is looked up under. It is written by hand, and
`icons.py` keeps a list of what is in it so that nothing guesses an icon over
one of them. A test holds the two to each other, so a field added to one and
not the other fails rather than quietly losing its picture.

`tools/make_translations.py` writes every language file from
`tools/translations.json`, which holds what each English string says in each
language. The words are data rather than code, so translating does not mean
reading Python. It reports anything it had no words for and leaves that in
English.

### Checking a login by hand

`tools/check_login.py` walks the whole login against a real account, from the
provider lookup through to reading an appliance capability tree, and says which
step fails and why. Press enter at the password prompt to take the mailed code
path instead.

    python tools/check_login.py you@example.com BE
    python tools/check_login.py you@example.com BE --brand electrolux
    python tools/check_login.py you@example.com BE --dump tmp/appliances

It logs every request and every answer. Everything that says who you are or
which machine is yours is replaced by a note of how long it was, in bodies, in
headers and in paths alike: tokens, keys, codes, the session cookies the
identity service sets, the address, the name and town on the account, and the
appliance ids. What kind of appliance it is and what it is
doing stay readable, because a log without those is not worth keeping. That
makes the output safe to paste into a bug report. Pass `-q` to log only
failures.

`--dump` writes what each appliance is, its capability tree and its reported
state out as JSON, redacted the same way. That is what the entity mapping is
built against.
