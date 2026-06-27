from flask import g
import uuid


def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    if hasattr(g, "request_id"):
        response.headers["X-Request-ID"] = g.request_id
    return response


def assign_request_id():
    g.request_id = str(uuid.uuid4())
