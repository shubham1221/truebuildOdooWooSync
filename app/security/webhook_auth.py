"""
TrueBuild Integration Platform — Webhook Authentication.

Validates WooCommerce webhook signatures using HMAC-SHA256.
Uses constant-time comparison to prevent timing attacks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from app.utils.logging import get_logger

logger = get_logger(__name__)


class WebhookAuthError(Exception):
    """Raised when webhook signature validation fails."""
    pass


def validate_webhook_signature(
    raw_body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Validate a WooCommerce webhook signature.

    WooCommerce sends the signature as a base64-encoded HMAC-SHA256 hash
    in the X-WC-Webhook-Signature header.

    Args:
        raw_body: The raw request body bytes (MUST be unmodified).
        signature: The X-WC-Webhook-Signature header value.
        secret: The webhook secret configured in WooCommerce.

    Returns:
        True if the signature is valid.

    Raises:
        WebhookAuthError: If validation fails.
    """
    if not signature:
        logger.warning("webhook_missing_signature")
        raise WebhookAuthError("Missing webhook signature header")

    if not secret:
        logger.error("webhook_secret_not_configured")
        raise WebhookAuthError("Webhook secret not configured")

    # Compute expected HMAC-SHA256 signature
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()

    computed_signature = base64.b64encode(computed_hmac).decode("utf-8")

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(computed_signature, signature):
        logger.warning(
            "webhook_signature_invalid",
            received_signature=signature[:20] + "...",
        )
        raise WebhookAuthError("Invalid webhook signature")

    logger.debug("webhook_signature_valid")
    return True
