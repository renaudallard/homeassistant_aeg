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

This is not part of the integration. It exists to prove the login end to end
and to settle the two details that could not be read out of the app package:
whether asking for a mobile target really yields a session that can sign, and
which base64 variant the Gigya signature needs.

Press enter at the password prompt to sign in with a code mailed to the
account instead, which is the only way in for an account that has no password.

The password is read from the terminal, is never echoed, and is never written
to a file or a log. Tokens are not printed either, only whether they arrived
and how long they last.

    python tools/check_login.py you@example.com FR
"""

from __future__ import annotations

import asyncio
import sys
import time
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
from custom_components.aeg.errors import AegError


def _urlsafe_sign(secret: str, method: str, url: str, params: dict[str, str]) -> str:
    """Sign the way the Android SDK does, with a URL safe digest."""
    base = gigya._signature_base(method, url, params)
    digest = hmac_new(b64decode(secret), base.encode(), sha1).digest()
    return b64encode(digest, altchars=b"-_").decode()


def _step(number: int, what: str) -> None:
    print(f"{number}. {what:.<38} ", end="", flush=True)


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
        print("ok  code mailed")
        code = input("   code from the mail: ").strip()
        _step(3, "gigya login with code")
        session = await client.login_with_otp(code, vtoken, ids)
    print("ok  session token and secret present")
    print("   so targetEnv=mobile does yield a signable session")
    return session


async def check(email: str, country: str) -> int:
    async with aiohttp.ClientSession() as session:
        auth = AegAuth(session, country)

        _step(1, "identity provider")
        provider = await auth.identity_provider()
        print(f"ok  tenant {provider.domain}")
        print(f"   regional endpoint {provider.http_base_url}")
        if provider.ws_base_url:
            print(f"   websocket        {provider.ws_base_url}")

        client = gigya.GigyaClient(session, provider.api_key, provider.domain)

        _step(2, "gigya ids")
        ids = await client.ids()
        print(f"ok  gmid {_redact(ids.gmid)}")

        gigya_session = await sign_in(client, ids, email)

        _step(4, "accounts.getJWT")
        variant = "standard base64"
        try:
            id_token = await client.jwt(gigya_session, ids)
        except AegError as err:
            print(f"failed with standard base64: {err}")
            _step(4, "accounts.getJWT, url safe")
            original = gigya.sign_request
            gigya.sign_request = _urlsafe_sign
            try:
                id_token = await client.jwt(gigya_session, ids)
            finally:
                gigya.sign_request = original
            variant = "url safe base64"
        print(f"ok  signed with {variant}")

        _step(5, "token exchange")
        tokens = await auth.exchange(id_token)
        lifetime = int(tokens.expires_at - time.time())
        print(f"ok  access token good for {lifetime}s")

        _step(6, "token refresh")
        refreshed = await auth.refresh(tokens)
        rotated = refreshed.refresh_token != tokens.refresh_token
        print(f"ok  refresh token {'rotated' if rotated else 'unchanged'}")

        api = AegApi(session, auth, refreshed, provider.http_base_url, country)

        _step(7, "appliances")
        appliances = await api.appliances()
        print(f"ok  {len(appliances)} found")
        for entry in appliances:
            info: dict[str, Any] = entry.get("applianceData") or {}
            print(
                f"   {_redact(str(entry.get('applianceId', '')))} "
                f"{info.get('modelName', 'unknown model')} "
                f"({entry.get('status', 'unknown status')})"
            )

        for entry in appliances:
            appliance_id = str(entry.get("applianceId", ""))
            if not appliance_id:
                continue
            _step(8, f"capabilities of {_redact(appliance_id)}")
            capabilities = await api.capabilities(appliance_id)
            print(f"ok  {len(capabilities)} top level nodes")
            print(f"   {', '.join(sorted(capabilities)[:12])}")

    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    email, country = sys.argv[1], sys.argv[2]
    try:
        return asyncio.run(check(email, country))
    except AegError as err:
        code = getattr(err, "code", None)
        if code == gigya.INVALID_CREDENTIALS:
            print(f"failed: {err}")
            print("that is the wrong password code, so try the mailed code path")
            return 1
        print(f"failed: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
