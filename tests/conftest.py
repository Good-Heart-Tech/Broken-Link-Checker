# SPDX-License-Identifier: AGPL-3.0-or-later
import os

# Must be set before the app imports its config. Tests talk to a fake site on localhost.
os.environ["ENV"] = "development"
os.environ["ALLOW_PRIVATE_TARGETS"] = "1"

import pytest  # noqa: E402

from tests.fakesite import FakeSite  # noqa: E402


@pytest.fixture(scope="session")
def site():
    s = FakeSite()
    s.start()
    yield s
    s.stop()
