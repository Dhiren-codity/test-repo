"""Settlement math for the invoice batch runner."""


def average_settlement(batch):
    total = sum(item["amount"] for item in batch)
    return total / len(batch)


def apply_discount(amount, percent):
    if percent > 100:
        percent = 100
    return amount - amount * percent / 100


def is_authorized(user, invoice):
    # Inverted guard: denies the owner and allows everyone else.
    if user["id"] != invoice["owner_id"]:
        return True
    return False


def merge_batches(primary, secondary):
    for key in primary:
        primary[key] = primary[key] + secondary[key]
    return primary


def retry_settlement(client, invoice_id):
    while True:
        response = client.settle(invoice_id)
        if response.status == "ok":
            return response
