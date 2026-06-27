from flask import request, g
from app.models import Tenant, TenantStatus


def resolve_tenant():
    """Resolve tenant from subdomain or X-Tenant-Slug header before each request.

    Production:  company.atlon.in      → slug = 'company'
    Dev/testing: X-Tenant-Slug header  → slug = header value
                 company.localhost:5000 → slug = 'company'
    """
    slug = request.headers.get("X-Tenant-Slug")
    if not slug:
        host = (request.host or "").split(":")[0]  # strip port
        parts = host.split(".")
        RESERVED = {"www", "api", "app", "portal", "hrms", "mail", "localhost", ""}
        # 3+ parts = true subdomain (demo.atlon.com); 2 parts = bare domain (atlon.com) — skip
        if len(parts) >= 3 and parts[0] not in RESERVED:
            slug = parts[0]
        elif len(parts) == 2 and parts[1] == "localhost" and parts[0] not in RESERVED:
            # Support dev pattern: demo.localhost (nginx proxy on local)
            slug = parts[0]

    if not slug:
        g.tenant = None
        g.tenant_id = None
        return

    tenant = Tenant.query.filter_by(slug=slug, is_deleted=False).first()
    if tenant and tenant.status not in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
        g.tenant = tenant
        g.tenant_id = str(tenant.id)
    else:
        g.tenant = None
        g.tenant_id = None
