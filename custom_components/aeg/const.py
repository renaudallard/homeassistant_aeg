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

The brand credentials below are the production values shipped in the AEG
OneApp Android package. They identify the app to the Electrolux OCP cloud and
are the same for every installation, so they are not user secrets.
"""

DOMAIN = "aeg"

# Config entry keys of our own. The account and country use the Home Assistant
# constants. The tokens live in the entry because the refresh token rotates on
# every renewal and has to survive a restart.
CONF_BASE_URL = "base_url"
CONF_WS_URL = "ws_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

# Electrolux OCP, production tier. The app also ships dev and staging hosts,
# which we have no use for. The websocket endpoint is not here because it is
# not fixed: the provider lookup says which one this account streams from.
OCP_BASE_URL = "https://api.ocp.electrolux.one"

# Brand identity of the AEG build of the OneApp.
BRAND = "aeg"
CLIENT_ID = "AEGOneApp"
CLIENT_SECRET = (
    "G6PZWyneWAZH6kZePRjZAdBbyyIu3qUgDGUDkat7obfU9ByQSgJPNy8xRo99vzcgWExX"
    "9N48gMJo3GWaHbMJsohIYOQ54zH2Hid332UnRZdvWOCWvWNnMNLalHoyH7xU"
)
API_KEY = "PEdfAP7N7sUc95GJPePDU54e2Pybbt6DZtdww7dz"

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
