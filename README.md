# TrueBuild Integration Platform

## WooCommerce ↔ Odoo Online Integration

Production-grade integration platform for **TrueBuild Deck & Turf** that synchronizes products, orders, inventory, and customers between Odoo Online (master system) and WooCommerce (sales channel).

**Country:** Australia | **Tax:** 10% GST | **Currency:** AUD

---

## Architecture

```
Odoo Online (Master)
    ↕  XML-RPC
Integration Platform (FastAPI + Celery)
    ↕  REST API v3
WooCommerce (Sales Channel)
```

### Stack

| Component | Technology |
|-----------|-----------|
| API Server | FastAPI + Uvicorn |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| Reverse Proxy | Nginx |
| Container | Docker + Docker Compose |
| Language | Python 3.12 |

---

## Quick Start

### 1. Clone and Configure

```bash
cp .env.example .env
# Edit .env with your Odoo and WooCommerce credentials
```

### 2. Run with Docker Compose

```bash
docker-compose up -d
```

This starts all 6 services:
- `truebuild-api` — FastAPI application (port 8000)
- `truebuild-celery-worker` — Background task processor
- `truebuild-celery-beat` — Scheduled task scheduler
- `truebuild-postgres` — PostgreSQL database (port 5432)
- `truebuild-redis` — Redis broker/cache (port 6379)
- `truebuild-nginx` — Reverse proxy (port 80/443)

### 3. Initialize Database

```bash
docker-compose exec api python manage.py init-db
# Or with Alembic:
docker-compose exec api python manage.py migrate
```

### 4. Verify

```bash
curl http://localhost/health
```

---

## Data Flow

| Flow | Source → Destination | Trigger |
|------|---------------------|---------|
| Product Sync | Odoo → WooCommerce | Scheduled (5 min) + Manual |
| Variant Sync | Odoo → WooCommerce | Part of product sync |
| Inventory Sync | Odoo → WooCommerce | Scheduled (5 min) + Manual |
| Order Sync | WooCommerce → Odoo | Webhook + Manual |
| Customer Sync | WooCommerce → Odoo | Part of order sync |

---

## API Endpoints

### Webhooks (WooCommerce → Platform)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhooks/woocommerce/order-created` | New order webhook |
| POST | `/webhooks/woocommerce/order-updated` | Order update webhook |
| POST | `/webhooks/woocommerce/order-refunded` | Order refund webhook |
| POST | `/webhooks/woocommerce/order-cancelled` | Order cancellation webhook |

### Sync Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sync/products` | Trigger full product sync |
| POST | `/api/sync/products/{sku}` | Sync single product |
| POST | `/api/sync/inventory` | Trigger full inventory sync |
| POST | `/api/sync/orders/{id}` | Sync single order |
| GET | `/api/sync/status` | Get sync status overview |
| GET | `/api/sync/logs` | Browse sync audit logs |
| GET | `/api/sync/failed-jobs` | List failed jobs |
| POST | `/api/sync/failed-jobs/{id}/retry` | Retry a failed job |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health check |

---

## CLI Commands

```bash
python manage.py migrate          # Run database migrations
python manage.py init-db          # Create tables directly
python manage.py sync-products    # Full product sync
python manage.py sync-inventory   # Full inventory sync
python manage.py sync-order 5001  # Sync single order
python manage.py retry-failed     # Retry failed jobs
python manage.py health           # Check all connections
```

---

## WooCommerce Webhook Setup

In WooCommerce Dashboard: **Settings → Advanced → Webhooks**

Create these webhooks:

| Name | Topic | Delivery URL | Secret |
|------|-------|-------------|--------|
| Order Created | Order created | `https://your-domain/webhooks/woocommerce/order-created` | (same as WOO_WEBHOOK_SECRET) |
| Order Updated | Order updated | `https://your-domain/webhooks/woocommerce/order-updated` | (same as WOO_WEBHOOK_SECRET) |

---

## Environment Variables

See `.env.example` for the complete list with documentation.

Key variables:

| Variable | Description |
|----------|-------------|
| `ODOO_URL` | Odoo instance URL |
| `ODOO_DB` | Odoo database name |
| `ODOO_USERNAME` | Odoo user email |
| `ODOO_PASSWORD` | Odoo API password |
| `WOO_URL` | WooCommerce store URL |
| `WOO_CONSUMER_KEY` | WooCommerce API key |
| `WOO_CONSUMER_SECRET` | WooCommerce API secret |
| `WOO_WEBHOOK_SECRET` | Webhook signing secret |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection URL |

---

## Production Deployment (Ubuntu)

### 1. Server Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
```

### 2. SSL with Let's Encrypt

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d your-domain.com
# Certificates will be in /etc/letsencrypt/live/your-domain.com/
```

Copy certificates to `nginx/ssl/` and uncomment the HTTPS server block in `nginx/nginx.conf`.

### 3. Deploy

```bash
git clone <repo-url> /opt/truebuild-sync
cd /opt/truebuild-sync
cp .env.example .env
# Edit .env with production credentials
docker compose up -d
docker compose exec api python manage.py init-db
```

### 4. Backup Strategy

- **PostgreSQL:** Daily pg_dump via cron
  ```bash
  0 2 * * * docker exec truebuild-postgres pg_dump -U truebuild truebuild_sync | gzip > /backups/truebuild_$(date +\%Y\%m\%d).sql.gz
  ```
- **Redis:** RDB snapshots (configured by default)
- **Logs:** Rotate with logrotate, archive to S3/GCS

### 5. Monitoring

- Health endpoint: `GET /health` — monitor with uptime services
- Sync logs: `GET /api/sync/logs` — check for failures
- Failed jobs: `GET /api/sync/failed-jobs` — alert on dead letters
- Docker logs: `docker compose logs -f api`

---

## Testing

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v --cov=app --cov-report=term-missing

# Run specific test groups
pytest tests/test_product_sync.py -v
pytest tests/test_order_sync.py -v
pytest tests/test_webhooks.py -v
pytest tests/test_repositories.py -v
```

---

## License

Proprietary — TrueBuild Deck & Turf
