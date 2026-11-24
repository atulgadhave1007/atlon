"""Tenant-ownership checks for IDs that arrive in a request body.

Route handlers already scope their own lookups by ``g.tenant_id``. This module
covers the other direction: foreign keys a client *sends* (``department_id``,
``employee_id``, ``reviewer_ids``...) must point at rows in the caller's tenant,
otherwise a user could link records to another tenant's data.
"""
import uuid
from typing import Mapping, Optional

from flask import g, jsonify

import app.models as _models


def _belongs_to_tenant(model, value) -> bool:
    try:
        row_id = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    query = model.query.filter_by(id=row_id, tenant_id=g.tenant_id)
    if hasattr(model, "is_deleted"):
        query = query.filter_by(is_deleted=False)
    return query.first() is not None


def reject_foreign_refs(data: Optional[Mapping], refs: Mapping[str, str]):
    """Return a ``(response, 400)`` tuple if any referenced ID is not in the tenant.

    ``refs`` maps a request field to a model name in ``app.models``. Empty or
    missing fields are skipped; list values are checked item by item.
    Returns ``None`` when every supplied reference is valid.
    """
    if not data:
        return None
    for field, model_name in refs.items():
        value = data.get(field)
        if value in (None, "", []):
            continue
        model = getattr(_models, model_name)
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item in (None, ""):
                continue
            if not g.tenant_id or not _belongs_to_tenant(model, item):
                return jsonify({"error": f"Invalid {field}"}), 400
    return None
