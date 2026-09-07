"""Test fixtures.

The Home Assistant test harness will not load an integration out of
custom_components unless something asks it to, so every test here does.
"""

from collections.abc import Generator

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    yield
