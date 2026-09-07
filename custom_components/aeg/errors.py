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


class AegTooManyRequests(AegConnectionError):
    """The service asked us to slow down.

    Renewing a token that was issued moments ago is refused this way. It is
    not a failure if the token in hand still works, which is how the app
    treats it.
    """
