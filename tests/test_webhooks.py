"""
TrueBuild — Webhook Unit Tests.

Tests webhook signature validation and endpoint handling.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from app.security.webhook_auth import WebhookAuthError, validate_webhook_signature


class TestWebhookAuth:
    """Tests for webhook HMAC-SHA256 signature validation."""

    def test_valid_signature(self):
        """Valid signature should return True."""
        secret = "test-webhook-secret"
        body = b'{"id": 1234, "status": "processing"}'

        # Compute expected signature
        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(computed).decode("utf-8")

        result = validate_webhook_signature(body, signature, secret)
        assert result is True

    def test_invalid_signature(self):
        """Invalid signature should raise WebhookAuthError."""
        secret = "test-webhook-secret"
        body = b'{"id": 1234}'
        wrong_signature = base64.b64encode(b"invalid").decode("utf-8")

        with pytest.raises(WebhookAuthError, match="Invalid webhook signature"):
            validate_webhook_signature(body, wrong_signature, secret)

    def test_missing_signature(self):
        """Missing signature should raise WebhookAuthError."""
        with pytest.raises(WebhookAuthError, match="Missing webhook signature"):
            validate_webhook_signature(b"body", "", "secret")

    def test_missing_secret(self):
        """Missing secret should raise WebhookAuthError."""
        with pytest.raises(WebhookAuthError, match="Webhook secret not configured"):
            validate_webhook_signature(b"body", "signature", "")

    def test_tampered_body(self):
        """Tampered body should fail validation."""
        secret = "test-webhook-secret"
        original_body = b'{"id": 1234}'
        tampered_body = b'{"id": 9999}'

        # Compute signature for original body
        computed = hmac.new(secret.encode("utf-8"), original_body, hashlib.sha256).digest()
        signature = base64.b64encode(computed).decode("utf-8")

        # Validate against tampered body
        with pytest.raises(WebhookAuthError):
            validate_webhook_signature(tampered_body, signature, secret)

    def test_constant_time_comparison(self):
        """Verify we use constant-time comparison (functional test)."""
        secret = "secret"
        body = b"test"

        computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        signature = base64.b64encode(computed).decode("utf-8")

        # Should succeed
        assert validate_webhook_signature(body, signature, secret) is True

        # Flip one character — should fail
        bad_sig = signature[:-1] + ("A" if signature[-1] != "A" else "B")
        with pytest.raises(WebhookAuthError):
            validate_webhook_signature(body, bad_sig, secret)
