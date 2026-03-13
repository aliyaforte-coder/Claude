# YNAB Transaction Enrichment API

A personal API service that enriches and validates YNAB transactions by cross-referencing SimpleFin, Privacy.com, and Amazon order data.

## Setup

1. Copy `.env.example` to `.env` and fill in your credentials
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `uvicorn src.main:app --reload`

Or with Docker:

```bash
docker compose up --build
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/validate` | SimpleFin ↔ YNAB transaction validation |
| `POST` | `/enrich/privacy` | Privacy.com → YNAB enrichment |
| `POST` | `/enrich/amazon` | Amazon → YNAB enrichment |
| `POST` | `/enrich/all` | Run all enrichment modules |
| `GET`  | `/health` | Health check with API connectivity tests |
| `GET`  | `/status` | Last run timestamps and results |

All enrichment endpoints support `dry_run=true` (default) to preview changes without modifying YNAB.

## Authentication

Set `API_KEY` in `.env` and pass it via the `X-API-Key` header. If unset, auth is disabled.

## Configuration

- `data/category_mappings.json` — merchant → category and Amazon category → YNAB category overrides
- Account mapping for SimpleFin ↔ YNAB can be configured in the validation endpoint
