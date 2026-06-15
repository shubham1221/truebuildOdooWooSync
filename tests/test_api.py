"""
TrueBuild — API Endpoint Tests.

Tests the FastAPI application endpoints using the test client.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    # Override database dependency
    from app.database.db import get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    from main import app
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    @patch("app.api.health.redis")
    @patch("app.api.health.OdooClient")
    @patch("app.api.health.WooCommerceClient")
    def test_health_check(self, mock_woo_cls, mock_odoo_cls, mock_redis, client):
        """Health endpoint should return status."""
        # Mock Redis
        mock_redis_instance = MagicMock()
        mock_redis.from_url.return_value = mock_redis_instance

        # Mock Odoo
        mock_odoo = MagicMock()
        mock_odoo.check_connection.return_value = {"status": "connected", "server_version": "17.0"}
        mock_odoo_cls.return_value = mock_odoo

        # Mock WooCommerce
        mock_woo = MagicMock()
        mock_woo.check_connection.return_value = {"status": "connected", "wc_version": "9.0"}
        mock_woo_cls.return_value = mock_woo

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data


class TestWebhookEndpoints:
    """Tests for webhook endpoints."""

    def test_webhook_no_signature_rejected(self, client):
        """Webhooks without signature should be rejected."""
        response = client.post(
            "/webhooks/order-created",
            json={"id": 1234},
        )
        assert response.status_code == 401

    def test_webhook_invalid_signature_rejected(self, client):
        """Webhooks with invalid signature should be rejected."""
        response = client.post(
            "/webhooks/order-created",
            json={"id": 1234},
            headers={"X-WC-Webhook-Signature": "invalid-signature"},
        )
        assert response.status_code == 401
