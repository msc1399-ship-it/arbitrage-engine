# eBay Marketplace Account Deletion Notifications

This service is independent from Streamlit and receives eBay marketplace account
deletion notifications. It does not call Browse API, refresh market data, or change
radar decisions.

## Configuration

Set these values in `.env`:

```dotenv
EBAY_ACCOUNT_DELETION_ENDPOINT=https://public.example.com/ebay/account-deletion
EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN=replace_with_32_to_80_safe_characters
```

The endpoint must be the exact public HTTPS URL registered at eBay. Localhost and
private IP addresses are rejected. The verification token must contain 32 to 80
ASCII letters, digits, underscores, or hyphens. Invalid configuration stops the
application during startup.

The existing `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_ENVIRONMENT` values
are used to retrieve eBay's notification public key. Secrets and OAuth tokens are
never logged.

## Local execution

```powershell
py -m uvicorn notification_server.app:app --host 0.0.0.0 --port 8000
```

`GET /health` returns only `{"status":"ok"}`. The verification endpoint is:

```text
GET|POST /ebay/account-deletion
```

Local execution is useful for tests, but eBay does not accept localhost as the
registered destination. Production requires a stable, publicly reachable HTTPS
URL with a valid certificate and the exact same URL in the environment setting.

## Verification and processing

The challenge response is the lowercase SHA-256 hex digest of this exact sequence:

```text
challenge_code + verification_token + endpoint
```

POST requests are processed only after `X-EBAY-SIGNATURE` is verified with the
public key identified by its `kid`. Public keys are obtained through eBay's
Notification API and cached for one hour. A missing or invalid signature returns
HTTP 412. If verification cannot be performed, the service returns HTTP 503 with
`PENDING_IMPLEMENTATION`; it never silently accepts the notification.

Accepted notification IDs are stored idempotently in SQLite. The audit table keeps
only the notification ID, receipt time, processing time, and result. Existing eBay
market JSON is searched for the supplied `userId`, `username`, or `eiasToken` and
matching personal fields are removed while anonymous aggregate counts and prices
remain. New eBay market snapshots are sanitized before persistence and do not keep
seller identity fields.

The current eBay collector response may contain `seller.username` inside
`MarketData.raw_data`; this is removed before SQLite persistence. The legacy SQL
schema also defines `listings.seller_name`, and listing URLs may carry external
identifiers. Those fields must not be enabled for eBay without extending the
deletion adapter to that datastore. The current Python application does not write
to that legacy `listings` table.

## Deployment checklist

1. Expose the service through public HTTPS; do not expose Streamlit as this endpoint.
2. Set the exact public URL and a strong valid verification token.
3. Configure eBay application credentials for the same sandbox or production environment.
4. Register and validate the endpoint in the eBay developer portal.
5. Keep the SQLite data directory durable and backed up.
6. Monitor HTTP 412, 503, and 500 responses without logging request bodies or headers.
