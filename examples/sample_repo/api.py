from auth import authenticate_request
from billing import create_invoice


def handle_invoice(headers, items):
    """Authenticate the caller before creating a billing invoice."""
    user = authenticate_request(headers)
    invoice = create_invoice(items)
    return {"user": user["id"], "invoice": invoice}
