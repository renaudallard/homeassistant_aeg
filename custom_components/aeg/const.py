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

"""Constants for the AEG appliance integration.

The brand credentials below are the production values shipped in the OneApp
Android packages. They identify the app to the Electrolux OCP cloud and are the
same for every installation, so they are not user secrets.

AEG and Electrolux are the same cloud and the same appliance API behind two
builds of the same app. Which one an account belongs to decides only what the
app calls itself while signing in, and an account of one brand cannot sign in
as the other, so it is asked for rather than guessed.
"""

from dataclasses import dataclass

DOMAIN = "aeg"

# Config entry keys of our own. The account and country use the Home Assistant
# constants. The tokens live in the entry because the refresh token rotates on
# every renewal and has to survive a restart.
CONF_BRAND = "brand"
CONF_BASE_URL = "base_url"
CONF_WS_URL = "ws_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

# Electrolux OCP, production tier. The app also ships dev and staging hosts,
# which we have no use for. The websocket endpoint is not here because it is
# not fixed: the provider lookup says which one this account streams from.
OCP_BASE_URL = "https://api.ocp.electrolux.one"


@dataclass(frozen=True)
class Brand:
    """How one build of the OneApp identifies itself."""

    # What the cloud calls it, which is what the provider lookup is asked for.
    key: str
    # What to call it in front of somebody, and on the device page.
    name: str
    client_id: str
    client_secret: str
    api_key: str


AEG = Brand(
    key="aeg",
    name="AEG",
    client_id="AEGOneApp",
    client_secret=(
        "G6PZWyneWAZH6kZePRjZAdBbyyIu3qUgDGUDkat7obfU9ByQSgJPNy8xRo99vzcgWExX"
        "9N48gMJo3GWaHbMJsohIYOQ54zH2Hid332UnRZdvWOCWvWNnMNLalHoyH7xU"
    ),
    api_key="PEdfAP7N7sUc95GJPePDU54e2Pybbt6DZtdww7dz",
)

ELECTROLUX = Brand(
    key="electrolux",
    name="Electrolux",
    client_id="ElxOneApp",
    client_secret=(
        "8UKrsKD7jH9zvTV7rz5HeCLkit67Mmj68FvRVTlYygwJYy4dW6KF2cVLPKeWzUQUd6"
        "KJMtTifFf4NkDnjI7ZLdfnwcPtTSNtYvbP7OzEkmQD9IjhMOf5e1zeAQYtt2yN"
    ),
    api_key="2AMqwEV5MqVhTKrRCyYfVF8gmKrd2rAmp7cUsfky",
)

BRANDS = {brand.key: brand for brand in (AEG, ELECTROLUX)}

# Entries made before there were two of them are all AEG, this having been an
# AEG integration, so that is what an entry saying nothing means.
DEFAULT_BRAND = AEG


def brand_for(key: str | None) -> Brand:
    """The brand an entry belongs to, whatever it happens to hold."""
    return BRANDS.get(str(key or "").lower(), DEFAULT_BRAND)


# OneAccount. The app talks to v2 of the token endpoint, which uses the
# standard snake_case OAuth field names.
# The app talks to v2 with snake_case field names, but that answers 400 to the
# same exchange that v1 accepts, so v1 with the camelCase names is what we use.
# v2 is kept here because it is what the app does, should it ever be worth
# another look.
TOKEN_PATH_V2 = "/one-account-authorization/api/v2/token"
TOKEN_PATH_V1 = "/one-account-authorization/api/v1/token"
IDENTITY_PROVIDERS_PATH = "/one-account-user/api/v1/identity-providers"

GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
GRANT_REFRESH_TOKEN = "refresh_token"
GRANT_CLIENT_CREDENTIALS = "client_credentials"

# Appliance service. The listing and the capability tree are v2; what an
# appliance actually is comes from v3, which the app reads one appliance at a
# time. There is a v3 batch as well, but it answers with a bare list carrying
# nothing to match a member back to the appliance it is about.
APPLIANCES_PATH = "/appliance/api/v2/appliances"
APPLIANCES_V3_PATH = "/appliance/api/v3/appliances"

# Refresh this long before the access token actually expires, so a call that
# starts just under the wire does not race the expiry.
TOKEN_EXPIRY_MARGIN = 60.0

REQUEST_TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0
