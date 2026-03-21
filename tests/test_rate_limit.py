import time
from agents.rate_limit import RateLimiter

def test_allows_within_limit():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("client-1") is True

def test_blocks_over_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("client-1")
    assert limiter.is_allowed("client-1") is False

def test_different_clients_independent():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed("client-1")
    limiter.is_allowed("client-1")
    assert limiter.is_allowed("client-1") is False
    assert limiter.is_allowed("client-2") is True

def test_window_expires():
    limiter = RateLimiter(max_requests=1, window_seconds=1)
    assert limiter.is_allowed("c") is True
    assert limiter.is_allowed("c") is False
    time.sleep(1.1)
    assert limiter.is_allowed("c") is True
