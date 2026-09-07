"""Errors raised by the AEG cloud client.

The split that matters to a caller is between a request that failed because
the credentials are no longer good, which needs the user to reauthenticate,
and one that failed because the network or the service was unavailable, which
is worth retrying.
"""


class AegError(Exception):
    """Base class for every error raised by this integration."""


class AegAuthError(AegError):
    """Credentials were rejected and reauthentication is needed."""


class AegConnectionError(AegError):
    """The service could not be reached, or answered with something unusable."""


class AegBackendError(AegConnectionError):
    """The service answered with a server side failure."""
