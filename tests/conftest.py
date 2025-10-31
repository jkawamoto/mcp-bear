#  conftest.py
#
#  Copyright (c) 2025 Junpei Kawamoto
#
#  This software is released under the MIT License.
#
#  http://opensource.org/licenses/mit-license.php

# type: ignore
import logging

import pytest

from mcp_bear.cli import init_forwarder


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def setup_forwarder() -> None:
    init_forwarder(logging.Logger(__name__))
