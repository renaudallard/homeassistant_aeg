<p align="center"><img src="assets/header.png" alt="AEG Home Assistant integration" width="640"></p>

# AEG appliances for Home Assistant

Unofficial integration. Not affiliated with, endorsed by, or supported by AEG
or Electrolux.

A Home Assistant integration for AEG appliances, talking to the Electrolux OCP
cloud the way the AEG OneApp does. Onboarding of new hardware is out of scope:
pair the appliance with the vendor app once, then drive it from here.

Requires Home Assistant 2026.9 or newer, which itself needs Python 3.14.2.

## State of the work

The integration loads and an account can be added through the interface. It
exposes no entities yet, so once added it sits there doing nothing useful: the
capability tree still has to be mapped onto Home Assistant entities.

| Piece | Where | Done |
| --- | --- | --- |
| Shared HTTP plumbing | `custom_components/aeg/http.py` | yes |
| Gigya login and JWT | `custom_components/aeg/gigya.py` | yes |
| OneAccount tokens | `custom_components/aeg/auth.py` | yes |
| Appliance API | `custom_components/aeg/api.py` | yes |
| Config flow, with reauthentication | `custom_components/aeg/config_flow.py` | yes |
| Capability to entity mapping | | no |
| Entity platforms | | no |
| Websocket for live state | | no |

## How the login works

Signing in takes two services. Neither of them is optional and the order
matters.

1. `POST /one-account-authorization/api/v1/token` with a client credentials
   grant authorises the application itself. The lookup in the next step is not
   anonymous, so nothing works without this.
2. `GET /one-account-user/api/v1/identity-providers`, carrying that token, says
   which Gigya tenant this account belongs to, and which regional endpoint its
   appliances live behind. Nothing about the region is hardcoded.
3. Gigya authenticates the user, by password or by a one time code mailed to
   the account, and `accounts.getJWT` mints a JWT for the session. That call is
   signed with HMAC-SHA1 over the session secret.
4. `POST /one-account-authorization/api/v1/token` trades the JWT for an OCP
   access token and refresh token, against the regional endpoint rather than
   the global one. Its country header comes from the country claim inside the
   JWT, which is what that field is asked of Gigya for.

The app uses v2 of the token endpoint with snake_case field names. That answers
400 to the same exchange v1 accepts, so v1 is what this uses, with the
camelCase names the rest of the API uses.

Renewal reuses the same token endpoint with a refresh grant, and that call is
the only one carrying the client secret, as HTTP basic auth. The refresh token
rotates every time, so whatever stores it has to write the new one back. The
client reports each new pair through the `on_tokens` listener for exactly that
reason.

Both login paths are implemented, and the config flow needs both. An account
that has no password can only get in with a code mailed to it, the same way the
Philips HomeID integration works.

Nothing tells you in advance which an account needs. The app does not look it
up either: it remembers per email address whether that person last used a code,
and only offers the choice at all when a server side feature flag is on. So the
config flow should ask rather than guess, and treat a rejected password as a
cue to offer the code instead. `AegAuthError` carries the Gigya error code for
that, and `gigya.INVALID_CREDENTIALS` is the one that means the password was
wrong.

## Adding an account

Add this repository to HACS as a custom repository of category Integration and
install it from there, or copy `custom_components/aeg` into the
`custom_components` directory of your Home Assistant configuration by hand.
Either way, restart and then add the AEG integration from the interface. It asks how the account signs in, because that cannot be looked up,
and takes either a password or a code sent to the address. The country is what
picks the server the appliances are on, so it has to be the one the account was
registered in.

The tokens are written into the config entry and renewed in the background. If
they ever stop working, Home Assistant asks to sign in again rather than
failing quietly.

## Where the protocol knowledge comes from

From the AEG OneApp Android package, version 4.30, read with apktool and jadx.
The app is obfuscated, and jadx fails outright on the two classes that matter
most for authentication, so parts of this were read from smali.

The Gigya signature is pinned by tests against values cross checked with
[pyelectroluxocp](https://github.com/Woyken/py-electrolux-ocp), an independent
client known to work against the live service.

Two things are inferred rather than confirmed against the service. Running
`tools/check_login.py` against a real account settles both, and says which of
the two it found:

- `targetEnv=mobile` is what should make Gigya return a session token and
  secret rather than a browser cookie value. A cookie value cannot sign
  `accounts.getJWT`. The client fails loudly if the pair is missing.
- The Android SDK base64 encodes the signature URL safe, while the Python
  client it was checked against uses plain base64. Plain base64 is what is
  known to work, so that is what is sent.

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

The decompiled app and the scratch work live in `tmp/`, which is not tracked.
The app package itself is not tracked either.

    ruff check .
    ruff format --check .
    mypy custom_components/ tests/ tools/
    pytest tests/

`tools/check_login.py` walks the whole login against a real account, from the
provider lookup through to reading an appliance capability tree, and reports
which base64 variant the signature needed. Press enter at the password prompt
to take the mailed code path instead.

It logs every request and every answer, so a failure can be read rather than
guessed at. Everything that says who you are or which machine is yours is
replaced by a note of how long it was, in bodies and in paths alike: tokens,
keys, codes, the address, the name and town on the account, and the appliance
ids. What kind of appliance it is and what it is doing stay readable, because a
log without those is not worth keeping. That makes the output safe to paste
into a bug report. Pass `-q` to log only failures.

    python tools/check_login.py you@example.com FR

`aiohttp` is the only runtime dependency, and Home Assistant already ships it.
The checks need `homeassistant` and `pytest-homeassistant-custom-component`,
and `tools/make_icons.py` needs Pillow. None of those are needed to run the
integration.

The config flow tests drive the real Home Assistant flow machinery with the
cloud mocked at the two classes the flow talks to, so they cover which step
follows which, what lands in the config entry, and which message a failure
puts on the form.

On every push the Validate workflow runs HACS validation and hassfest, the
Home Assistant manifest and translation checks. Neither runs locally, so the
first sign of a manifest problem is that workflow.
