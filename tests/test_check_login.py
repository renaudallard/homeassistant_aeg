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


"""Tests for the login checker, which is a tool rather than the integration.

Only the parts that decide what it was asked and where a file goes: the rest
talks to a real account and cannot be run here.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tools import check_login
from tools.check_login import _plain


def test_a_model_name_is_kept_as_it_is() -> None:
    assert _plain("EWX1493A") == "EWX1493A"


def test_a_model_name_cannot_choose_the_directory() -> None:
    """It comes back from the cloud and goes into a path."""
    assert _plain("../../etc/passwd") == "etc_passwd"
    assert _plain("a/b") == "a_b"


def test_a_name_with_nothing_left_of_it_still_names_something() -> None:
    assert _plain("..") == "appliance"
    assert _plain("") == "appliance"


@pytest.mark.parametrize("where", ["tmp/x", "tmp/x/", "./tmp/x"])
def test_a_dump_directory_is_taken_however_it_is_written(where: str) -> None:
    """A trailing slash or a leading ./ is still the directory, not an argument."""
    argv = ["check_login.py", "you@example.com", "BE", "--dump", where]
    with (
        patch("sys.argv", argv),
        patch.object(check_login, "check", AsyncMock(return_value=0)) as checked,
        patch("logging.basicConfig"),
    ):
        assert check_login.main() == 0
    assert checked.await_args is not None
    assert checked.await_args.args[0] == "you@example.com"
    assert checked.await_args.args[3] == Path(where)
