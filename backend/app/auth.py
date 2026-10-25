"""Verify the dashboard's signed session cookie at the API boundary."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import HTTPException, Request


def lawyer_identity(request: Request) -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise HTTPException(503, "Dashboard authentication is not configured")
    token = request.cookies.get("nyaya_token", "")
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    try:
        header_part, payload_part, signature = token.split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        header = json.loads(decode(header_part))
        if header.get("alg") != "HS256":
            raise ValueError("Unsupported signing algorithm")
        expected = hmac.new(secret.encode(), f"{header_part}.{payload_part}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, decode(signature)):
            raise ValueError("Invalid signature")
        claims = json.loads(decode(payload_part))
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= time.time():
            raise ValueError("Expired session")
        identity = claims.get("lawyerId")
        if not isinstance(identity, str) or not identity:
            raise ValueError("Missing identity")
        return identity
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(401, "Sign in to your advocate account") from None
