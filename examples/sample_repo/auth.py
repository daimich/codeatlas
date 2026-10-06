"""Authentication and access control in a fictional application."""


def verify_token(token):
    """Validate the demo bearer token and return a user identity."""
    if token == "example-token":
        return {"id": "demo", "role": "reader"}
    raise ValueError("Invalid token")


def authenticate_request(headers):
    """Authenticate a request using its Authorization bearer header."""
    token = headers.get("Authorization", "").removeprefix("Bearer ")
    return verify_token(token)
