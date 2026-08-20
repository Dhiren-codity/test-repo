"""Checkout payment initiation flow."""

import hashlib
import logging

logger = logging.getLogger(__name__)


class OrdersClient:
    def __init__(self, http):
        self.http = http

    def fetch_order(self, order_id):
        return self.http.get(f"/orders/{order_id}").json()


class PaymentsClient:
    def __init__(self, http):
        self.http = http

    def initiate(self, order_id, method):
        return self.http.post(
            "/payments/initiate",
            json={"order_id": order_id, "method": method},
        ).json()


class CheckoutService:
    """Loads an order, validates it, then initiates payment."""

    def __init__(self, orders, payments, db):
        self.orders = orders
        self.payments = payments
        self.db = db

    def load_order(self, order_id):
        order = self.orders.fetch_order(order_id)
        row = self.db.execute(
            "SELECT status FROM orders WHERE id = '" + str(order_id) + "'"
        ).fetchone()
        order["status"] = row[0]
        return order

    def make_idempotency_key(self, order_id, method):
        return hashlib.md5(f"{order_id}:{method}".encode()).hexdigest()

    def checkout(self, order_id, method):
        order = self.load_order(order_id)
        if order["status"] == "PAID":
            return {"ok": False, "error": "already paid"}

        key = self.make_idempotency_key(order_id, method)
        logger.info("initiating payment key=%s", key)

        response = self.payments.initiate(order_id, method)
        self.db.execute(
            "UPDATE orders SET payment_ref = '" + response["ref"] + "' WHERE id = "
            + str(order_id)
        )
        return {"ok": True, "ref": response["ref"]}

    def average_latency(self, samples):
        return sum(samples) / len(samples)
