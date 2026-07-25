"""Focused regression tests for API input and rate-limit hardening."""

import asyncio
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from app.middleware import rate_limiter
from app.middleware.rate_limiter import RateLimitMiddleware, SlidingWindowRateLimiter, _get_client_ip
from app.main import check_quantum_connection
from app.schemas import MAX_OPTIMIZATION_STOPS, MAX_QAOA_STOPS, OptimizeRequest


def _request(headers=None, method="GET"):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "method": method, "headers": raw_headers, "client": ("127.0.0.1", 1234)})


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

    def test_rejects_vehicle_payload_until_a_real_vrp_contract_exists(self):
        payload = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [{"name": "Stop", "lat": 16.1, "lon": 108.1}],
            "vehicles": [{"id": "truck-1", "capacity_kg": 100}],
        }
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate(payload)

    def test_rejects_stop_count_over_classical_demo_limit(self):
        payload = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [
                {"name": f"Stop {index}", "lat": 16.0 + index / 100, "lon": 108.0}
                for index in range(MAX_OPTIMIZATION_STOPS + 1)
            ],
        }
        with self.assertRaises(ValidationError):
            OptimizeRequest.model_validate(payload)

    def test_allows_maximum_classical_demo_size_without_quantum(self):
        payload = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [
                {"name": f"Stop {index}", "lat": 16.0 + index / 100, "lon": 108.0}
                for index in range(MAX_OPTIMIZATION_STOPS)
            ],
            "algorithms": ["nearest_neighbor", "or_tools"],
        }
        request = OptimizeRequest.model_validate(payload)
        self.assertEqual(len(request.stops), MAX_OPTIMIZATION_STOPS)

    def test_rejects_qaoa_outside_verified_three_stop_scope(self):
        payload = {
            "depot": {"name": "Depot", "lat": 16.0, "lon": 108.0},
            "stops": [
                {"name": f"Stop {index}", "lat": 16.0 + index / 100, "lon": 108.0}
                for index in range(MAX_QAOA_STOPS + 1)
            ],
            "algorithms": ["qaoa"],
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

    def test_global_429_returns_json_instead_of_raising_unboundlocalerror(self):
        original_limiter = rate_limiter._global_limiter
        rate_limiter._global_limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
        request = _request(method="POST")
        request.scope["path"] = "/api/v1/inspect"
        middleware = RateLimitMiddleware(app=lambda scope, receive, send: None)

        async def next_handler(_: Request) -> Response:
            return Response(status_code=200)

        try:
            response = asyncio.run(middleware.dispatch(request, next_handler))
        finally:
            rate_limiter._global_limiter = original_limiter

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "61")

    def test_read_only_optimization_poll_does_not_consume_global_limit(self):
        original_limiter = rate_limiter._global_limiter
        rate_limiter._global_limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
        request = _request()
        request.scope["path"] = "/api/v1/optimize/example-run"
        middleware = RateLimitMiddleware(app=lambda scope, receive, send: None)

        async def next_handler(_: Request) -> Response:
            return Response(status_code=200)

        try:
            response = asyncio.run(middleware.dispatch(request, next_handler))
        finally:
            rate_limiter._global_limiter = original_limiter

        self.assertEqual(response.status_code, 200)


class QuantumConnectionTests(unittest.TestCase):
    def test_connection_check_does_not_expose_or_require_a_token(self):
        with patch.dict(
            os.environ,
            {"IBM_QUANTUM_TOKEN": "", "QISKIT_IBM_TOKEN": ""},
            clear=False,
        ):
            result = check_quantum_connection()

        self.assertEqual(result.status, "not_configured")
        self.assertFalse(result.token_configured)
        self.assertIsNone(result.token_variable)


if __name__ == "__main__":
    unittest.main()
