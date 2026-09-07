"""Constants for the AEG appliance integration.

The brand credentials below are the production values shipped in the AEG
OneApp Android package. They identify the app to the Electrolux OCP cloud and
are the same for every installation, so they are not user secrets.
"""

DOMAIN = "aeg"

# Electrolux OCP, production tier. The app also ships dev and staging hosts,
# which we have no use for.
OCP_BASE_URL = "https://api.ocp.electrolux.one"
OCP_WS_URL = "wss://ws.eu.ocp.electrolux.one"

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
TOKEN_PATH = "/one-account-authorization/api/v2/token"
IDENTITY_PROVIDERS_PATH = "/one-account-user/api/v1/identity-providers"
CURRENT_USER_PATH = "/one-account-user/api/v1/users/current"

GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
GRANT_REFRESH_TOKEN = "refresh_token"

# Appliance service.
APPLIANCES_PATH = "/appliance/api/v2/appliances"

# Refresh this long before the access token actually expires, so a call that
# starts just under the wire does not race the expiry.
TOKEN_EXPIRY_MARGIN = 60.0

REQUEST_TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0
