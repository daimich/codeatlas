"""Invoice calculation for the sample service."""


def calculate_total(items):
    """Sum line item quantities multiplied by unit price, excluding tax."""
    return sum(item["quantity"] * item["price"] for item in items)


def create_invoice(items):
    """Create an invoice with its total amount."""
    return {"items": items, "total": calculate_total(items)}
