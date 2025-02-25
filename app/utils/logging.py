import sys
import time
import json
from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import iterate_in_threadpool
from app.shared.config import get_settings
from app.utils.generate_id import generate_id

settings = get_settings()


def truncate_response(body: str, max_length: int = 1000) -> str:
    """Truncate response body if it's too long."""
    if len(body) > max_length:
        return body[:max_length] + "... [truncated]"
    return body


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = generate_id()

        # Log request start
        logger.info(
            "Request started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query_params=dict(request.query_params),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Get response body if it's JSON or text
            content_type = response.headers.get("content-type", "")
            response_body = None

            if any(t in content_type.lower() for t in ["json", "text", "xml", "html"]):
                body = [section async for section in response.body_iterator]
                response.body_iterator = iterate_in_threadpool(iter(body))

                try:
                    text = body[0].decode() if body else None
                    if text:
                        # Try to parse and re-serialize JSON for pretty printing
                        if "json" in content_type.lower():
                            try:
                                response_body = json.loads(text)
                            except json.JSONDecodeError:
                                response_body = truncate_response(text)
                        else:
                            response_body = truncate_response(text)
                except Exception as e:
                    logger.warning(f"Could not decode response body: {str(e)}")

            # Log request completion
            logger.info(
                "Request completed",
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
                content_type=content_type,
                content_length=response.headers.get("content-length"),
                response=response_body,
            )

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Request failed: {str(e)}", request_id=request_id, duration_ms=round(duration * 1000, 2), exc_info=True
            )
            raise


def setup_logging():
    """Configure Loguru for JSON logging."""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        serialize=settings.LOG_SERIALIZE,
        level=settings.LOG_LEVEL,
    )
