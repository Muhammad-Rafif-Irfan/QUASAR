"""Ensure an unavailable OSM provider cannot stall an optimization run."""

import time
import unittest
from unittest.mock import patch

from app.services import routing


class OSMnxDeadlineTests(unittest.TestCase):
    def test_osmnx_context_returns_before_deadline(self):
        expected = (None, None, [[0.0, 1.0], [1.0, 0.0]])
        with patch.object(routing, "_build_osmnx_context", return_value=expected):
            self.assertEqual(routing._run_osmnx_with_deadline([]), expected)

    def test_osmnx_context_times_out_without_blocking_caller(self):
        old_deadline = routing.OSMNX_DEADLINE_SECONDS
        routing.OSMNX_DEADLINE_SECONDS = 0.01
        try:
            with patch.object(routing, "_build_osmnx_context", side_effect=lambda _: time.sleep(0.05)):
                with self.assertRaises(TimeoutError):
                    routing._run_osmnx_with_deadline([])
        finally:
            routing.OSMNX_DEADLINE_SECONDS = old_deadline


if __name__ == "__main__":
    unittest.main()
