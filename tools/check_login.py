# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Check the cloud login chain against a real account.

This is not part of the integration. It walks the whole sign in, says which
step fails, and logs every request and answer so a failure can be diagnosed
without guessing.

Press enter at the password prompt to sign in with a code mailed to the
account instead, which is the only way in for an account that has no password.

Nothing secret is printed. The password is read from the terminal and never
echoed, and the log replaces tokens, keys, codes and the address itself with a
note of how long they were, so the output can be pasted into a bug report. Pass
-q to log only failures.

    python tools/check_login.py you@example.com BE
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import traceback
from base64 import b64decode, b64encode
from getpass import getpass
from hashlib import sha1
from hmac import new as hmac_new
from typing import Any

import aiohttp

sys.path.insert(0, ".")

from custom_components.aeg import gigya
from custom_components.aeg.api import AegApi
from custom_components.aeg.auth import AegAuth
from custom_components.aeg.errors import AegError, AegTooManyRequests


def _urlsafe_sign(secret: str, method: str, url: str, params: dict[str, str]) -> str:
    """Sign the way the Android SDK does, with a URL safe digest."""
    base = gigya._signature_base(method, url, params)
    digest = hmac_new(b64decode(secret), base.encode(), sha1).digest()
    return b64encode(digest, altchars=b"-_").decode()


def _step(number: int, what: str) -> None:
    print(f"\n{number}. {what}", flush=True)


def _ok(detail: str = "") -> None:
    print(f"   ok {detail}".rstrip(), flush=True)


def _note(detail: str) -> None:
    print(f"   {detail}", flush=True)


def _redact(value: str) -> str:
    return f"{value[:4]}..." if len(value) > 4 else "..."


async def sign_in(
    client: gigya.GigyaClient, ids: gigya.GigyaIds, email: str
) -> gigya.GigyaSession:
    """Log in with a password, or with a mailed code when none is given."""
    password = getpass(f"password for {email}, empty to use a mailed code: ")
    if password:
        _step(3, "gigya login with password")
        session = await client.login(email, password, ids)
    else:
        _step(3, "gigya sendCode")
        vtoken = await client.send_otp_code(email, ids)
        _ok("code mailed")
        code = input("   code from the mail: ").strip()
        _step(3, "gigya login with code")
        session = await client.login_with_otp(code, vtoken, ids)
    _ok("session token and secret present")
    _note("so targetEnv=mobile does yield a signable session")
    return session


async def check(email: str, country: str) -> int:
    async with aiohttp.ClientSession() as session:
        auth = AegAuth(session, country)

        _step(1, "identity provider")
        provider = await auth.identity_provider()
        _ok(f"tenant {provider.domain}")
        _note(f"regional endpoint {provider.http_base_url}")
        if provider.ws_base_url:
            _note(f"websocket        {provider.ws_base_url}")

        client = gigya.GigyaClient(session, provider.api_key, provider.domain)

        _step(2, "gigya ids")
        ids = await client.ids()
        _ok(f"gmid {_redact(ids.gmid)}")

        gigya_session = await sign_in(client, ids, email)

        _step(4, "accounts.getJWT")
        variant = "standard base64"
        try:
            id_token = await client.jwt(gigya_session, ids)
        except AegError as err:
            _note(f"standard base64 was refused: {err}")
            _step(4, "accounts.getJWT, url safe")
            original = gigya.sign_request
            gigya.sign_request = _urlsafe_sign
            try:
                id_token = await client.jwt(gigya_session, ids)
            finally:
                gigya.sign_request = original
            variant = "url safe base64"
        _ok(f"signed with {variant}")

        _step(5, "token exchange")
        tokens = await auth.exchange(id_token)
        _ok(f"access token good for {int(tokens.expires_at - time.time())}s")

        _step(6, "token refresh")
        try:
            refreshed = await auth.refresh(tokens)
        except AegTooManyRequests as err:
            # The exchange happened seconds ago, so the service is right to
            # refuse. The app recovers the same way, by keeping what it has.
            refreshed = tokens
            _ok("refused as too soon, which is what should happen here")
            _note(f"{err}")
            _note("the client keeps the token it holds when this happens")
        else:
            rotated = refreshed.refresh_token != tokens.refresh_token
            _ok(f"refresh token {'rotated' if rotated else 'unchanged'}")

        api = AegApi(session, auth, refreshed, provider.http_base_url, country)

        _step(7, "appliances")
        appliances = await api.appliances()
        _ok(f"{len(appliances)} found")
        for entry in appliances:
            info: dict[str, Any] = entry.get("applianceData") or {}
            _note(
                f"{_redact(str(entry.get('applianceId', '')))} "
                f"{info.get('modelName', 'unknown model')} "
                f"({entry.get('status', 'unknown status')})"
            )

        for entry in appliances:
            appliance_id = str(entry.get("applianceId", ""))
            if not appliance_id:
                continue
            _step(8, f"capabilities of {_redact(appliance_id)}")
            capabilities = await api.capabilities(appliance_id)
            _ok(f"{len(capabilities)} top level nodes")
            _note(", ".join(sorted(capabilities)[:12]))

    return 0


def main() -> int:
    arguments = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(arguments) != 2:
        print(__doc__)
        return 2
    logging.basicConfig(
        level=logging.WARNING if "-q" in sys.argv else logging.DEBUG,
        format="   %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    email, country = arguments
    try:
        return asyncio.run(check(email, country))
    except AegError as err:
        print(f"\nfailed: {type(err).__name__}: {err}")
        if getattr(err, "code", None) == gigya.INVALID_CREDENTIALS:
            print("that is the wrong password code, so try the mailed code path")
        return 1
    except Exception:
        print("\nfailed with something the client did not expect:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
