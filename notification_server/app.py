from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from notification_server.ebay_account_deletion import (
    AccountDeletionSettings,
    EbayNotificationSignatureVerifier,
    challenge_response,
)
from services.ebay_data_deletion import (
    DEFAULT_DB_PATH,
    EbayDeletionStore,
    extract_account_deletion,
    process_account_deletion,
)

LOGGER = logging.getLogger(__name__)
EXPECTED_TOPIC = "MARKETPLACE_ACCOUNT_DELETION"


def create_app(*, settings=None, database_path=DEFAULT_DB_PATH,
               signature_verifier=None, deletion_processor=process_account_deletion):
    @asynccontextmanager
    async def lifespan(application):
        application.state.settings = (settings or AccountDeletionSettings.from_environment()).validated()
        application.state.deletion_store = EbayDeletionStore(database_path)
        application.state.signature_verifier = (
            signature_verifier or EbayNotificationSignatureVerifier.from_environment()
        )
        application.state.deletion_processor = deletion_processor
        yield

    application = FastAPI(title="eBay Account Deletion Notifications", lifespan=lifespan)

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/ebay/account-deletion")
    def verify_endpoint(challenge_code: str | None = Query(default=None)):
        if not challenge_code:
            raise HTTPException(status_code=400, detail="challenge_code is required")
        return JSONResponse({
            "challengeResponse": challenge_response(
                challenge_code, application.state.settings
            )
        })

    @application.post("/ebay/account-deletion")
    async def receive_notification(request: Request):
        try:
            payload = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Notification must be a JSON object")

        fields = extract_account_deletion(payload)
        if fields["topic"] != EXPECTED_TOPIC:
            raise HTTPException(status_code=400, detail="Unsupported notification topic")
        notification_id = fields.get("notificationId")
        if not notification_id:
            raise HTTPException(status_code=400, detail="notificationId is required")

        verification = await run_in_threadpool(
            application.state.signature_verifier.verify,
            payload,
            request.headers.get("X-EBAY-SIGNATURE"),
        )
        headers = {"X-Ebay-Signature-Status": verification.status}
        if verification.valid is False:
            return JSONResponse(
                {"status": "rejected", "signature_status": verification.status},
                status_code=412,
                headers=headers,
            )
        if verification.valid is None:
            return JSONResponse(
                {"status": "not_processed", "signature_status": verification.status},
                status_code=503,
                headers=headers,
            )

        received_at = datetime.now(timezone.utc).isoformat()
        store = application.state.deletion_store
        if not store.claim(str(notification_id), received_at):
            return JSONResponse(
                {"status": "acknowledged", "duplicate": True,
                 "signature_status": verification.status},
                headers=headers,
            )
        try:
            result = await run_in_threadpool(
                application.state.deletion_processor,
                payload,
                store.path,
            )
            store.complete(str(notification_id), result)
        except Exception:
            store.complete(str(notification_id), "ERROR")
            LOGGER.error(
                "ebay_account_deletion processing_failed notification_id=%s",
                notification_id,
            )
            return JSONResponse(
                {"status": "error", "signature_status": verification.status},
                status_code=500,
                headers=headers,
            )
        return JSONResponse(
            {"status": "acknowledged", "duplicate": False,
             "signature_status": verification.status},
            headers=headers,
        )

    return application


app = create_app()
