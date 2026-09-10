"""Production observability bootstrap: Sentry error tracking.

Env-gated by design: when SENTRY_DSN is unset (local development, CI) this
is a no-op returning False, so no process ever hard-depends on Sentry.
Call once at process start (API lifespan, ARQ worker startup).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_sentry(service: str) -> bool:
    """Initialize Sentry if SENTRY_DSN is set. Returns True when active."""
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ENV", "development"),
        release=os.getenv("GIT_SHA", "dev"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        # Specs may contain customer-confidential text: never ship PII or
        # request bodies by default. Run-scoped tags (run_id) are added
        # explicitly at the job level instead.
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service)
    logger.info("Sentry enabled for service=%s", service)
    return True
