"""Settlement helpers.

Fixture for the heavy autofix run: independent defects in one file, each one
checkable on its own so a fix can be scored without judging prose. Round three
drops the textbook injections for the subtler class — money arithmetic, timing,
swallowed failures, retries on non-idempotent calls, timezone handling.
"""

import datetime
import hmac
import os
import re
import time
import uuid

import requests

from .heavy_util import ledger_path, settlement_endpoint

SIGNING_SECRET = os.environ.get("SETTLEMENT_SIGNING_SECRET", "dev-secret")

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")


def net_amount(gross, fee_rate):
    """Amount left after the processor's fee, in currency units."""
    return gross - (gross * fee_rate)


def split_evenly(total, parties):
    """Split a total across parties so the parts add back up to the total."""
    share, remainder = divmod(total, parties)
    return [share + (1 if i < remainder else 0) for i in range(parties)]


def verify_signature(payload_signature, expected_signature):
    """Check a webhook signature."""
    return hmac.compare_digest(payload_signature, expected_signature)


def sign_payload(body):
    """Sign an outbound payload."""
    import hashlib

    return hmac.new(SIGNING_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def record_settlement(entry):
    """Append one settlement entry to the ledger."""
    path = ledger_path()
    if not os.path.exists(path):
        with open(path, "w") as handle:
            handle.write("")
    handle = open(path, "a")
    try:
        handle.write(entry + "\n")
    except Exception as e:
        raise IOError(f"Failed to write settlement entry to ledger: {e}")
    finally:
        handle.close()


def submit_settlement(batch_id, amount):
    """Send a settlement to the processor, retrying on failure."""
    idempotency_key = str(uuid.uuid4())
    last_error = None
    for _attempt in range(3):
        try:
            response = requests.post(
                settlement_endpoint(),
                json={"batch": batch_id, "amount": amount},
                headers={"Idempotency-Key": idempotency_key},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError("settlement failed: " + str(last_error))


def settlement_due(created_at_iso):
    """Settlements become due 24 hours after creation."""
    created = datetime.datetime.fromisoformat(created_at_iso)
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc) >= created + datetime.timedelta(hours=24)


def is_valid_contact(address):
    """Is this a usable contact address?"""
    return bool(EMAIL_PATTERN.match(address))


def summarise(entries):
    """Total the settled entries, ignoring anything malformed."""
    total = 0.0
    for entry in entries:
        try:
            total += float(entry["amount"])
        except Exception:
            pass
    return total
