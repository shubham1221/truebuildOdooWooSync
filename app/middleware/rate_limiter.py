"""
TrueBuild Integration Platform — Rate Limiting Middleware.

Redis-based rate limiting for API and webhook endpoints.
Uses sliding window counter algorithm.
"""

from __future__ import annotations

import time

import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting middleware.

    Applies different rate limits to webhook vs general API endpoints.
    Uses client IP as the rate limit key.
    """

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        settings = get_settings()
        self.settings = settings

        try:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.redis.ping()
            self.enabled = True
        except Exception as e:
            logger.warning("rate_limiter_disabled", error=str(e))
            self.enabled = False

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        # Determine rate limit based on endpoint type
        path = request.url.path
        if path.startswith("/webhooks"):
            max_requests = self.settings.WEBHOOK_RATE_LIMIT_REQUESTS
            window = self.settings.WEBHOOK_RATE_LIMIT_WINDOW_SECONDS
            prefix = "rl:wh"
        else:
            max_requests = self.settings.RATE_LIMIT_REQUESTS
            window = self.settings.RATE_LIMIT_WINDOW_SECONDS
            prefix = "rl:api"

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        rate_key = f"{prefix}:{client_ip}"

        try:
            # Sliding window counter
            current_time = int(time.time())
            window_start = current_time - window

            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(rate_key, 0, window_start)
            pipe.zadd(rate_key, {str(current_time): current_time})
            pipe.zcard(rate_key)
            pipe.expire(rate_key, window)
            results = pipe.execute()

            request_count = results[2]

            if request_count > max_requests:
                logger.warning(
                    "rate_limit_exceeded",
                    client_ip=client_ip,
                    path=path,
                    count=request_count,
                    limit=max_requests,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": f"Rate limit exceeded. Max {max_requests} requests per {window}s.",
                        "retry_after": window,
                    },
                    headers={"Retry-After": str(window)},
                )

        except redis.RedisError as e:
            # If Redis is down, allow the request through
            logger.warning("rate_limiter_redis_error", error=str(e))

        return await call_next(request)
