"""Validate Payhip's documented webhook shape, with no network or secret logging.

Payhip sends sha256(api_key), NOT a payload HMAC. Treat the received signature
as a bearer credential; never expose it in responses, logs or browser code.
See https://help.payhip.com/article/115-webhooks.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import TypeAdapter, EmailStr, ValidationError

_email_adapter = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class PurchaseEvent:
    transaction_id: str
    product_key: str
    buyer_email: str
    refunded: bool


def parse_event(payload: dict, api_key: str, product_key: str) -> PurchaseEvent | None:
    if not api_key or not product_key:
        raise HTTPException(503, "Payhip purchase verification is not configured")
    supplied = payload.get("signature")
    expected = hashlib.sha256(api_key.encode()).hexdigest()
    if (
        not isinstance(supplied, str)
        or not re.fullmatch(r"[0-9a-f]{64}", supplied)
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(401, "Invalid Payhip signature")
    kind = payload.get("type")
    if kind not in ("paid", "refunded"):
        return None  # subscription access is deliberately not sold by this integration
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 100:
        raise HTTPException(400, "Invalid Payhip items")
    if not any(
        isinstance(i, dict) and i.get("product_key") == product_key for i in items
    ):
        return None
    if payload.get("is_gift"):
        # The documented paid payload doesn't identify the recipient; do not grant
        # a gift buyer access that was intended for a different email address.
        return None
    transaction = payload.get("id")
    if not isinstance(transaction, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,160}", transaction
    ):
        raise HTTPException(400, "Invalid transaction ID")
    try:
        email = (
            str(_email_adapter.validate_python(payload.get("email"))).strip().lower()
        )
    except ValidationError:
        raise HTTPException(400, "Invalid purchase email") from None
    price = payload.get("price")
    if type(price) is not int or price <= 0:
        raise HTTPException(400, "A positive paid price is required")
    if kind == "refunded":
        refunded = payload.get("amount_refunded")
        if type(refunded) is not int or not 0 < refunded <= price:
            raise HTTPException(400, "Invalid refund amount")
        if refunded < price:
            return None  # retain access for a partial refund
    return PurchaseEvent(transaction, product_key, email, kind == "refunded")


async def record_event(conn, event: PurchaseEvent) -> None:
    # A full refund creates a tombstone even if the paid event arrives later.
    # A replayed paid event can never clear refunded_at or change the email.
    await conn.execute(
        """INSERT INTO study_purchases
            (transaction_id, product_key, buyer_email, paid_at, refunded_at)
            VALUES ($1,$2,$3, CASE WHEN $4 THEN NULL ELSE NOW() END,
                    CASE WHEN $4 THEN NOW() ELSE NULL END)
            ON CONFLICT (transaction_id, product_key) DO UPDATE SET
                refunded_at = CASE WHEN $4 THEN COALESCE(study_purchases.refunded_at, NOW())
                                   ELSE study_purchases.refunded_at END
            WHERE study_purchases.buyer_email = EXCLUDED.buyer_email""",
        event.transaction_id,
        event.product_key,
        event.buyer_email,
        event.refunded,
    )
