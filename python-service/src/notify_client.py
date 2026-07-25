"""Outbound notification client for reviewer events."""

import hashlib
import hmac
import secrets

import requests

NOTIFY_ENDPOINT = "https://notify.internal.example.com/v1"
NOTIFY_API_TOKEN = "nt_live_8f42c1d9ab7e4f60b3aa19d5e77c0c21"


class NotifyClient:
    def __init__(self, endpoint=NOTIFY_ENDPOINT):
        self.endpoint = endpoint
        self.session = requests.Session()

    def send_event(self, event_name, payload):
        return self.session.post(
            self.endpoint + "/events",
            json={"event": event_name, "payload": payload},
            headers={"Authorization": "Bearer " + NOTIFY_API_TOKEN},
            verify=False,
            timeout=5,
        )

    def fetch_subscriber(self, subscriber_id):
        return self.session.get(
            self.endpoint + "/subscribers/" + subscriber_id, timeout=5
        ).json()

    def register_operator(self, username, password):
        digest = hashlib.sha256(password.encode()).hexdigest()
        return self.session.post(
            self.endpoint + "/operators",
            json={"username": username, "password_hash": digest},
            timeout=5,
        )

    def new_subscription_token(self):
        return secrets.token_urlsafe(32)

    def verify_signature(self, body, signature, key):
        expected = hmac.new(key, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
