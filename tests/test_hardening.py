"""Focused regression tests for API input and rate-limit hardening."""

import unittest

from pydantic import ValidationError
from starlette.requests import Request

from app.middleware.rate_limiter import SlidingWindowRateLimiter, _get_client_ip
from app.schemas import MAX_OPTIMIZATION_STOPS, OptimizeRequest


def _request(headers=None):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "headers": raw_headers, "client": ("127.0.0.1", 1234)})


class InputHardeningTests(unittest.TestCase):
    def test_rejects_blank_location_name(self):
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate({
                "depot": {"name": " ", "lat": 16.0, "lon": 108.0},
                "stops": [{"name": "Stop", "lat": 16.1, "lon": 108.1}],
            })

    def test_rejects_out_of_range_coordinates(self):
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate({
                "depot": {"name": "Depot", "lat": 91, "lon": 108.0},
                "stops": [{"name": "Stop", "lat": 16.1, "lon": 108.1}],
            })

    def test_rejects_unsupported_or_duplicate_algorithms(self):
        base = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [{"name": "Stop", "lat": 16.1, "lon": 108.1}],
        }
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate({**base, "algorithms": ["unknown"]})
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate({**base, "algorithms": ["qaoa", "qaoa"]})

    def test_rejects_stop_count_that_can_exhaust_quantum_simulator(self):
        payload = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [
                {"name": f"Stop {index}", "lat": 16.0 + index / 100, "lon": 108.0}
                for index in range(MAX_OPTIMIZATION_STOPS + 1)
            ],
        }
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate(payload)


class RateLimitHardeningTests(unittest.TestCase):
    def test_limiter_stops_at_configured_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        self.assertTrue(limiter.is_allowed("client")[0])
        self.assertTrue(limiter.is_allowed("client")[0])
        allowed, metadata = limiter.is_allowed("client")
        self.assertFalse(allowed)
        self.assertEqual(metadata["remaining"], 0)

    def test_untrusted_forwarded_header_cannot_choose_rate_limit_identity(self):
        request = _request({"x-forwarded-for": "203.0.113.7"})
        self.assertEqual(_get_client_ip(request), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
