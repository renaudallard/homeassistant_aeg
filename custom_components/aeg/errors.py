"""Errors raised by the AEG cloud client.

The split that matters to a caller is between a request that failed because
the credentials are no longer good, which needs the user to reauthenticate,
and one that failed because the network or the service was unavailable, which
is worth retrying.
"""

from __future__ import annotations


class AegError(Exception):
    """Base class for every error raised by this integration."""


class AegAuthError(AegError):
    """Credentials were rejected and reauthentication is needed.

    Carries the provider error code when there is one, because a config flow
    has to tell a wrong password apart from an account that cannot be logged
    into this way at all.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class AegConnectionError(AegError):
    """The service could not be reached, or answered with something unusable."""


class AegBackendError(AegConnectionError):
    """The service answered with a server side failure."""
