"""``python -m tests``: the offline suites through unittest, the same ones ``python -m pytest`` runs.

The live API suite is left out on purpose: it would call the real API whenever ZEROBOUNCE_API_KEY is set.
Run it explicitly with ``python -m unittest tests.zero_bounce_integration_test``.
"""

import unittest

from .test_offline_api import OfflineApiTest  # noqa: F401
from .test_offline_edges import (  # noqa: F401
    DocumentedVariantsTest,
    ErrorBodyTest,
    OptionalFieldsTest,
    ResponseModelTest,
    TransportFailureTest,
)
from .test_security_offline import (  # noqa: F401
    KeyFormatTest,
    NoContextLeakTest,
    TransportPlacementTest,
    WarmupBodyRedactionTest,
)
from .test_streaming_and_regions_offline import RegionalBaseUrlTest, StreamedDownloadTest  # noqa: F401
from .test_warmup_offline import WarmupTest  # noqa: F401
from .zero_bounce_test_case import ZeroBounceTestCase  # noqa: F401

if __name__ == "__main__":
    unittest.main()
