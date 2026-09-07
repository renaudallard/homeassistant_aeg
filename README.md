<p align="center"><img src="assets/header.png" alt="AEG Home Assistant integration" width="640"></p>

# AEG appliances for Home Assistant

Unofficial integration. Not affiliated with, endorsed by, or supported by AEG
or Electrolux.

A Home Assistant integration for AEG appliances, talking to the Electrolux OCP
cloud the way the AEG OneApp does. Onboarding of new hardware is out of scope:
pair the appliance with the vendor app once, then drive it from here.

Requires Home Assistant 2026.9 or newer.

## State of the work

The cloud client is in place and checked. The Home Assistant entry points, the
config flow and the entity platforms are not written yet, so the integration
does not load in Home Assistant as it stands.

| Piece | Where | Done |
| --- | --- | --- |
| Shared HTTP plumbing | `custom_components/aeg/http.py` | yes |
| Gigya login and JWT | `custom_components/aeg/gigya.py` | yes |
| OneAccount tokens | `custom_components/aeg/auth.py` | yes |
| Appliance API | `custom_components/aeg/api.py` | yes |
| Capability to entity mapping | | no |
| Config flow and platforms | | no |
| Websocket for live state | | no |

## How the login works

Signing in takes two services. Neither of them is optional and the order
matters.

1. `GET /one-account-user/api/v1/identity-providers` on the OCP cloud says
   which Gigya tenant this account belongs to, and which regional endpoint its
   appliances live behind. Nothing about the region is hardcoded.
2. Gigya authenticates the user, by password or by a one time code mailed to
   the account, and `accounts.getJWT` mints a JWT for the session. That call is
   signed with HMAC-SHA1 over the session secret.
3. `POST /one-account-authorization/api/v2/token` trades the JWT for an OCP
   access token and refresh token.

Renewal reuses the same token endpoint with a refresh grant, and that call is
the only one carrying the client secret, as HTTP basic auth. The refresh token
rotates every time, so whatever stores it has to write the new one back. The
client reports each new pair through the `on_tokens` listener for exactly that
reason.

Both login paths are implemented. A password reaches the same session as the
one time code, and the code path is there for anyone who would rather not have
a password stored in Home Assistant at all.

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

`brands/` holds the four PNGs that home-assistant/brands expects under
`custom_integrations/aeg/`, ready to be copied into a fork of that repository
when the integration is published. `assets/` holds the repository banner, a
mark for dark backgrounds, favicons and the SVG masters. Rescale from the SVGs
rather than from the PNGs, and use `icon-simplified.svg` below roughly 48 px.

The mark is original artwork for this integration. It is not the AEG logo and
reproduces no AEG or Electrolux trademark.

## Development

The decompiled app and the scratch work live in `tmp/`, which is not tracked.
The app package itself is not tracked either.

    ruff check .
    ruff format --check .
    mypy custom_components/ tests/ tools/
    pytest tests/

`tools/check_login.py` walks the whole login against a real account, from the
provider lookup through to reading an appliance capability tree, and reports
which base64 variant the signature needed. It asks for the password on the
terminal and prints no password, token or full appliance id.

    python tools/check_login.py you@example.com FR

`aiohttp` is the only runtime dependency, and Home Assistant already ships it.
