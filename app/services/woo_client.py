"""
TrueBuild Integration Platform — WooCommerce REST API Client.

Production-grade wrapper around WooCommerce REST API v3.
Uses httpx for HTTP calls with OAuth query-string authentication (HTTPS).
Handles rate limiting, retries, pagination, and batch operations.

WooCommerce is a SALES CHANNEL only — never the source of truth.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class WooCommerceAPIError(Exception):
    """Raised when a WooCommerce API call fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: Any = None,
    ):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class WooCommerceClient:
    """
    WooCommerce REST API v3 client.

    Authenticates via OAuth query parameters (consumer_key / consumer_secret)
    over HTTPS. Provides methods for products, variations, orders, and
    inventory management.

    Usage:
        client = WooCommerceClient()
        products = client.get("products", params={"per_page": 50})
    """

    def __init__(
        self,
        url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        api_version: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.url = (url or settings.WOO_URL).rstrip("/")
        self.consumer_key = consumer_key or settings.WOO_CONSUMER_KEY
        self.consumer_secret = consumer_secret or settings.WOO_CONSUMER_SECRET
        self.api_version = api_version or settings.WOO_API_VERSION
        self.timeout = timeout or settings.WOO_TIMEOUT
        self.verify_ssl = verify_ssl if verify_ssl is not None else settings.WOO_VERIFY_SSL

        self.base_url = f"{self.url}/wp-json/{self.api_version}"
        self._client: httpx.Client | None = None

    # ── HTTP Client Management ───────────────────────────────────────────

    def _get_client(self) -> httpx.Client:
        """Get or create the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.timeout),
                verify=self.verify_ssl,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def _build_url(self, endpoint: str) -> str:
        """Build the full API URL for an endpoint."""
        endpoint = endpoint.lstrip("/")
        return f"{self.base_url}/{endpoint}"

    def _add_auth_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Add OAuth authentication parameters to the query string."""
        params = dict(params or {})
        params["consumer_key"] = self.consumer_key
        params["consumer_secret"] = self.consumer_secret
        return params

    # ── Core HTTP Methods ────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Any:
        """
        Make an HTTP request to the WooCommerce API.

        Handles rate limiting (429) and server errors (5xx) with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            json_data: JSON body payload
            max_retries: Maximum retry attempts for transient errors

        Returns:
            Parsed JSON response.

        Raises:
            WooCommerceAPIError: If the request fails after retries.
        """
        url = self._build_url(endpoint)
        auth_params = self._add_auth_params(params)
        client = self._get_client()

        last_error = None
        for attempt in range(max_retries + 1):
            start_time = time.monotonic()
            try:
                response = client.request(
                    method=method,
                    url=url,
                    params=auth_params,
                    json=json_data,
                )
                duration_ms = int((time.monotonic() - start_time) * 1000)

                # Rate limited — wait and retry
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(
                        "woo_rate_limited",
                        endpoint=endpoint,
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    time.sleep(retry_after)
                    continue

                # Server error — retry with backoff
                if response.status_code >= 500:
                    logger.warning(
                        "woo_server_error",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue

                # Client error — fail immediately
                if response.status_code >= 400:
                    body = self._safe_json(response)
                    error_msg = body.get("message", response.text) if isinstance(body, dict) else response.text
                    logger.error(
                        "woo_api_error",
                        endpoint=endpoint,
                        method=method,
                        status_code=response.status_code,
                        error=error_msg,
                        duration_ms=duration_ms,
                    )
                    raise WooCommerceAPIError(
                        f"WooCommerce API error ({response.status_code}): {error_msg}",
                        status_code=response.status_code,
                        response_body=body,
                    )

                # Success
                logger.debug(
                    "woo_api_call",
                    endpoint=endpoint,
                    method=method,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
                return self._safe_json(response)

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "woo_timeout",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    timeout=self.timeout,
                )
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
            except httpx.RequestError as e:
                last_error = e
                logger.error(
                    "woo_request_error",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

        raise WooCommerceAPIError(
            f"WooCommerce API request failed after {max_retries + 1} attempts: {last_error}",
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        """Safely parse JSON response."""
        try:
            return response.json()
        except Exception:
            return response.text

    # ── Public API Methods ───────────────────────────────────────────────

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request."""
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        """Make a POST request."""
        return self._request("POST", endpoint, json_data=data)

    def put(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        """Make a PUT request."""
        return self._request("PUT", endpoint, json_data=data)

    def delete(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make a DELETE request."""
        params = params or {}
        params.setdefault("force", "true")
        return self._request("DELETE", endpoint, params=params)

    # ── Pagination Helper ────────────────────────────────────────────────

    def get_all(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch all records from a paginated endpoint.

        Args:
            endpoint: API endpoint
            params: Additional query parameters
            max_pages: Safety limit on pages to fetch

        Returns:
            Combined list of all records.
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)
        params.setdefault("page", 1)

        all_records: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            params["page"] = page
            records = self.get(endpoint, params)
            if not records or not isinstance(records, list):
                break
            all_records.extend(records)
            if len(records) < params["per_page"]:
                break

        logger.info(
            "woo_fetched_all",
            endpoint=endpoint,
            total_records=len(all_records),
        )
        return all_records

    # ── Product Operations ───────────────────────────────────────────────

    def create_product(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new WooCommerce product."""
        result = self.post("products", data)
        logger.info("woo_product_created", product_id=result.get("id"), sku=data.get("sku"))
        return result

    def update_product(self, product_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing WooCommerce product."""
        result = self.put(f"products/{product_id}", data)
        logger.info("woo_product_updated", product_id=product_id)
        return result

    def get_product(self, product_id: int) -> dict[str, Any]:
        """Get a WooCommerce product by ID."""
        return self.get(f"products/{product_id}")

    def get_product_by_sku(self, sku: str) -> dict[str, Any] | None:
        """Find a WooCommerce product by SKU."""
        products = self.get("products", params={"sku": sku})
        if isinstance(products, list) and products:
            return products[0]
        return None

    def list_products(
        self,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """List WooCommerce products."""
        return self.get("products", params=params)

    def delete_product(self, product_id: int) -> Any:
        """Delete a WooCommerce product."""
        return self.delete(f"products/{product_id}")

    # ── Variation Operations ─────────────────────────────────────────────

    def create_variation(
        self,
        product_id: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a product variation."""
        result = self.post(f"products/{product_id}/variations", data)
        logger.info(
            "woo_variation_created",
            product_id=product_id,
            variation_id=result.get("id"),
            sku=data.get("sku"),
        )
        return result

    def update_variation(
        self,
        product_id: int,
        variation_id: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a product variation."""
        result = self.put(f"products/{product_id}/variations/{variation_id}", data)
        logger.info(
            "woo_variation_updated",
            product_id=product_id,
            variation_id=variation_id,
        )
        return result

    def list_variations(
        self,
        product_id: int,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """List all variations for a product."""
        return self.get_all(f"products/{product_id}/variations", params=params)

    def batch_update_variations(
        self,
        product_id: int,
        create: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        Batch create/update/delete variations.

        Uses WooCommerce batch endpoint for efficiency.
        """
        data: dict[str, Any] = {}
        if create:
            data["create"] = create
        if update:
            data["update"] = update
        if delete:
            data["delete"] = delete
        return self.post(f"products/{product_id}/variations/batch", data)

    # ── Category Operations ──────────────────────────────────────────────

    def get_categories(
        self,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """List product categories."""
        return self.get_all("products/categories", params=params)

    def create_category(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a product category."""
        result = self.post("products/categories", data)
        logger.info("woo_category_created", category_id=result.get("id"), name=data.get("name"))
        return result

    def find_category_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a category by name."""
        categories = self.get("products/categories", params={"search": name, "per_page": 10})
        if isinstance(categories, list):
            for cat in categories:
                if cat.get("name", "").lower() == name.lower():
                    return cat
        return None

    # ── Order Operations ─────────────────────────────────────────────────

    def get_order(self, order_id: int) -> dict[str, Any]:
        """Get a WooCommerce order by ID."""
        return self.get(f"orders/{order_id}")

    def list_orders(
        self,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """List WooCommerce orders."""
        return self.get("orders", params=params)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update an order (e.g., add a note)."""
        return self.put(f"orders/{order_id}", data)

    # ── Product Attribute Operations ─────────────────────────────────────

    def get_attributes(self) -> list[dict[str, Any]]:
        """List all product attributes."""
        return self.get_all("products/attributes")

    def create_attribute(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a product attribute."""
        result = self.post("products/attributes", data)
        logger.info("woo_attribute_created", attribute_id=result.get("id"), name=data.get("name"))
        return result

    def find_or_create_attribute(self, name: str) -> dict[str, Any]:
        """Find an existing attribute by name, or create it."""
        attrs = self.get_attributes()
        for attr in attrs:
            if attr.get("name", "").lower() == name.lower():
                return attr
        return self.create_attribute({
            "name": name,
            "slug": name.lower().replace(" ", "-"),
            "type": "select",
            "order_by": "menu_order",
            "has_archives": False,
        })

    # ── Stock Management ─────────────────────────────────────────────────

    def update_stock(
        self,
        product_id: int,
        stock_quantity: int,
        manage_stock: bool = True,
    ) -> dict[str, Any]:
        """Update stock quantity for a simple product."""
        return self.update_product(product_id, {
            "manage_stock": manage_stock,
            "stock_quantity": stock_quantity,
        })

    def update_variation_stock(
        self,
        product_id: int,
        variation_id: int,
        stock_quantity: int,
        manage_stock: bool = True,
    ) -> dict[str, Any]:
        """Update stock quantity for a product variation."""
        return self.update_variation(product_id, variation_id, {
            "manage_stock": manage_stock,
            "stock_quantity": stock_quantity,
        })

    # ── Health Check ─────────────────────────────────────────────────────

    def check_connection(self) -> dict[str, Any]:
        """
        Test the connection to WooCommerce.

        Returns:
            Dictionary with connection status.
        """
        try:
            # Fetch system status (lightweight endpoint)
            result = self.get("system_status")
            return {
                "status": "connected",
                "url": self.url,
                "wc_version": result.get("environment", {}).get("version", "unknown")
                if isinstance(result, dict)
                else "unknown",
            }
        except WooCommerceAPIError as e:
            # Even a 401/403 means the server is reachable
            if e.status_code in (401, 403):
                return {
                    "status": "auth_error",
                    "error": str(e),
                    "url": self.url,
                }
            return {
                "status": "error",
                "error": str(e),
                "url": self.url,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "url": self.url,
            }
