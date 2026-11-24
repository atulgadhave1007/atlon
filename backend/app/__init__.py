import logging
import os
import secrets
import sys
import structlog
from flask import Flask, jsonify, send_from_directory
from app.config import get_config, ProductionConfig, validate_production_config
from app.extensions import db, migrate, cors, limiter
from app.middleware.security import add_security_headers, assign_request_id
from app.middleware.tenant import resolve_tenant

# Absolute path to the frontend public directory (sibling of backend/)
_FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'public')
)


def create_app(config_class=None):
    app = Flask(__name__, static_folder=None)

    # ── Configuration ─────────────────────────────────────────────────────────
    cfg = config_class or get_config()
    app.config.from_object(cfg)
    app.config["IS_PRODUCTION"] = isinstance(cfg, type) and issubclass(cfg, ProductionConfig)

    # Refuse to boot production with default secrets or wildcard CORS.
    if app.config["IS_PRODUCTION"]:
        problems = validate_production_config(app.config)
        if problems:
            raise RuntimeError(
                "Refusing to start in production:\n  - " + "\n  - ".join(problems)
            )

    # ── Logging ───────────────────────────────────────────────────────────────
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    cors.init_app(app, resources={
        r"/api/*": {
            "origins": app.config.get("CORS_ORIGINS", ["*"]),
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type", "X-Tenant-Slug", "X-Request-ID"],
        }
    })

    # ── Sentry (optional) ─────────────────────────────────────────────────────
    dsn = app.config.get("SENTRY_DSN")
    if dsn:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()], traces_sample_rate=0.1)

    # ── Middleware ────────────────────────────────────────────────────────────
    app.before_request(assign_request_id)
    app.before_request(resolve_tenant)
    app.after_request(add_security_headers)

    # ── Blueprints ────────────────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Error Handlers ────────────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request", "message": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

    # ── Frontend SPA (dev convenience — nginx handles this in production) ─────
    @app.route("/")
    @app.route("/<path:path>")
    @limiter.exempt
    def spa(path="index.html"):
        # API requests must never fall through to here
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404
        target = path if path and os.path.isfile(os.path.join(_FRONTEND_DIR, path)) else "index.html"
        return send_from_directory(_FRONTEND_DIR, target)

    # ── Health ────────────────────────────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "version": "1.0.0"})

    @app.route("/api/ready")
    def ready():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ready"})
        except Exception as e:
            return jsonify({"status": "not_ready", "error": str(e)}), 503

    # ── DB Init ───────────────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _apply_sqlite_migrations(app)
        _seed_initial_data(app)

    return app


def _register_blueprints(app: Flask):
    from app.api.v1.auth import auth_bp
    from app.api.v1.super_admin import super_bp
    from app.api.v1.tenant import tenant_bp
    from app.api.v1.employees import employees_bp
    from app.api.v1.organization import org_bp
    from app.api.v1.attendance import attendance_bp
    from app.api.v1.leave import leave_bp
    from app.api.v1.payroll import payroll_bp
    from app.api.v1.performance import performance_bp
    from app.api.v1.recruitment import recruitment_bp
    from app.api.v1.training import training_bp
    from app.api.v1.expense import expense_bp
    from app.api.v1.helpdesk import helpdesk_bp
    from app.api.v1.notifications import notifications_bp
    from app.api.v1.reports import reports_bp
    from app.api.v1.lifecycle import lifecycle_bp
    from app.api.v1.exit import exit_bp
    from app.api.v1.biometric import biometric_bp
    from app.api.v1.letters import letters_bp
    from app.api.v1.billing import billing_bp
    from app.api.v1.surveys import bp as surveys_bp
    from app.api.v1.okr import bp as okr_bp
    from app.api.v1.assets import bp as assets_bp
    from app.api.v1.visitors import bp as visitors_bp
    from app.api.v1.timesheets import bp as timesheets_bp

    blueprints = [
        (auth_bp, "/api/auth"),
        (super_bp, "/api/super"),
        (tenant_bp, "/api/tenant"),
        (employees_bp, "/api/employees"),
        (org_bp, "/api/org"),
        (attendance_bp, "/api/attendance"),
        (leave_bp, "/api/leave"),
        (payroll_bp, "/api/payroll"),
        (performance_bp, "/api/performance"),
        (recruitment_bp, "/api/recruitment"),
        (training_bp, "/api/training"),
        (expense_bp, "/api/expense"),
        (helpdesk_bp, "/api/helpdesk"),
        (notifications_bp, "/api/notifications"),
        (reports_bp, "/api/reports"),
        (lifecycle_bp, "/api/lifecycle"),
        (exit_bp, "/api/exit"),
        (biometric_bp, "/api/biometric"),
        (letters_bp, "/api/letters"),
        (billing_bp, "/api/billing"),
        (surveys_bp, "/api/surveys"),
        (okr_bp, "/api/okr"),
        (assets_bp, "/api/assets"),
        (visitors_bp, "/api/visitors"),
        (timesheets_bp, "/api/timesheets"),
    ]
    for bp, prefix in blueprints:
        app.register_blueprint(bp, url_prefix=prefix)


def _apply_sqlite_migrations(app: Flask):
    """Fix schema drift on SQLite that db.create_all() won't fix (it never alters existing tables).
    Uses SQLite's table-reconstruction approach since ALTER COLUMN is not supported."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite"):
        return  # PostgreSQL supports ALTER COLUMN; Alembic handles migrations there

    conn = db.engine.raw_connection()
    try:
        cur = conn.cursor()

        # Fix 1: refresh_tokens.tenant_id — must be nullable for super-admin tokens
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='refresh_tokens'")
        row = cur.fetchone()
        if row and "tenant_id CHAR(36) NOT NULL" in row[0]:
            cur.executescript("""
                PRAGMA foreign_keys=OFF;
                BEGIN;
                ALTER TABLE refresh_tokens RENAME TO _refresh_tokens_old;
                CREATE TABLE refresh_tokens (
                    tenant_id CHAR(36) REFERENCES tenants (id),
                    employee_id CHAR(36) REFERENCES employees (id),
                    super_admin_id CHAR(36) REFERENCES super_admins (id),
                    token_hash VARCHAR(255) NOT NULL UNIQUE,
                    device_info VARCHAR(500),
                    ip_address VARCHAR(45),
                    expires_at DATETIME NOT NULL,
                    is_revoked BOOLEAN,
                    revoked_at DATETIME,
                    last_used_at DATETIME,
                    id CHAR(36) NOT NULL PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    is_deleted BOOLEAN NOT NULL,
                    deleted_at DATETIME
                );
                INSERT INTO refresh_tokens SELECT * FROM _refresh_tokens_old;
                DROP TABLE _refresh_tokens_old;
                COMMIT;
                PRAGMA foreign_keys=ON;
            """)
            conn.commit()

        # Fix 2: audit_logs.tenant_id — must be nullable for pre-auth events
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_logs'")
        row = cur.fetchone()
        if row and "tenant_id CHAR(36) NOT NULL" in row[0]:
            cur.executescript("""
                PRAGMA foreign_keys=OFF;
                BEGIN;
                ALTER TABLE audit_logs RENAME TO _audit_logs_old;
                CREATE TABLE audit_logs (
                    tenant_id CHAR(36) REFERENCES tenants (id),
                    actor_id CHAR(36) REFERENCES employees (id),
                    actor_email VARCHAR(200),
                    actor_role VARCHAR(50),
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(100),
                    entity_id CHAR(36),
                    old_values JSON,
                    new_values JSON,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(500),
                    request_id VARCHAR(100),
                    result VARCHAR(20),
                    error_message TEXT,
                    duration_ms INTEGER,
                    id CHAR(36) NOT NULL PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    is_deleted BOOLEAN NOT NULL,
                    deleted_at DATETIME
                );
                INSERT INTO audit_logs SELECT * FROM _audit_logs_old;
                DROP TABLE _audit_logs_old;
                COMMIT;
                PRAGMA foreign_keys=ON;
            """)
            conn.commit()
        # Fix 3: tenants.bg_image_url — added for per-tenant login background
        cur.execute("PRAGMA table_info(tenants)")
        tenant_cols = {row[1] for row in cur.fetchall()}
        if "bg_image_url" not in tenant_cols:
            cur.execute("ALTER TABLE tenants ADD COLUMN bg_image_url VARCHAR(500)")
            conn.commit()

        # Fix 4: employee_bank_details — account_holder_name and branch_name
        cur.execute("PRAGMA table_info(employee_bank_details)")
        bank_cols = {row[1] for row in cur.fetchall()}
        if "account_holder_name" not in bank_cols:
            cur.execute("ALTER TABLE employee_bank_details ADD COLUMN account_holder_name VARCHAR(200)")
            conn.commit()
        if "branch_name" not in bank_cols:
            cur.execute("ALTER TABLE employee_bank_details ADD COLUMN branch_name VARCHAR(200)")
            conn.commit()

        # Fix 5: employee_experience — company_location, ctc, manager fields
        cur.execute("PRAGMA table_info(employee_experience)")
        exp_cols = {row[1] for row in cur.fetchall()}
        for col_def in [
            ("company_location", "VARCHAR(300)"),
            ("ctc", "NUMERIC(15, 2)"),
            ("manager_name", "VARCHAR(200)"),
            ("manager_email", "VARCHAR(200)"),
            ("manager_mobile", "VARCHAR(20)"),
        ]:
            if col_def[0] not in exp_cols:
                cur.execute(f"ALTER TABLE employee_experience ADD COLUMN {col_def[0]} {col_def[1]}")
        conn.commit()

    except Exception as e:
        conn.rollback()
        import logging
        logging.warning(f"SQLite migration warning: {e}")
    finally:
        conn.close()


def _seed_initial_data(app: Flask):
    from app.models import Plan, PlanTier

    if Plan.query.count() == 0:
        plans = [
            Plan(name="starter", tier=PlanTier.STARTER, display_name="Starter",
                 price_per_employee_inr=50, price_per_employee_usd=1,
                 max_employees=100, max_admins=2,
                 features={"attendance": True, "leave": True, "payroll": False,
                            "performance": False, "recruitment": False, "lms": False}),
            Plan(name="standard", tier=PlanTier.STANDARD, display_name="Standard",
                 price_per_employee_inr=120, price_per_employee_usd=2,
                 max_employees=500, max_admins=5,
                 features={"attendance": True, "leave": True, "payroll": True,
                            "performance": True, "recruitment": False, "lms": False,
                            "biometric": True, "exports": True}),
            Plan(name="premium", tier=PlanTier.PREMIUM, display_name="Premium",
                 price_per_employee_inr=200, price_per_employee_usd=4,
                 max_employees=2000, max_admins=20,
                 features={"attendance": True, "leave": True, "payroll": True,
                            "performance": True, "recruitment": True, "lms": True,
                            "biometric": True, "exports": True, "api": True,
                            "uae_payroll": True, "us_payroll": True}),
            Plan(name="enterprise", tier=PlanTier.ENTERPRISE, display_name="Enterprise",
                 price_per_employee_inr=0, price_per_employee_usd=0,
                 max_employees=999999, max_admins=999,
                 features={"all": True}),
        ]
        for p in plans:
            db.session.add(p)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    _bootstrap_super_admin(app)


def _bootstrap_super_admin(app: Flask):
    """Create the first super admin from SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD.

    - Does nothing if any super admin already exists.
    - No email set: logs a warning and creates nothing.
    - No password set: in production (or tests) logs a warning and creates nothing;
      in development generates a random password and prints it ONCE to stdout.
    - Password set but too weak for the password policy: logs a warning, creates nothing.
    The password itself is never written to the log.

    Returns the created SuperAdmin, or None.
    """
    from app.models import SuperAdmin
    from app.utils.security import hash_password, validate_password

    log = logging.getLogger("atlon.bootstrap")
    if SuperAdmin.query.count() > 0:
        return None

    email = (app.config.get("SUPER_ADMIN_EMAIL") or "").strip().lower()
    password = app.config.get("SUPER_ADMIN_PASSWORD") or ""
    if not email:
        log.warning(
            "No super admin exists and SUPER_ADMIN_EMAIL is not set; none was created. "
            "Set SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD, then restart."
        )
        return None

    generated = False
    if not password:
        if app.config.get("IS_PRODUCTION") or app.config.get("TESTING"):
            log.warning(
                "No super admin exists and SUPER_ADMIN_PASSWORD is not set; none was created. "
                "Set SUPER_ADMIN_PASSWORD, then restart."
            )
            return None
        password = secrets.token_urlsafe(18)
        generated = True
    else:
        problems = validate_password(password)
        if problems:
            log.warning(
                "SUPER_ADMIN_PASSWORD does not meet the password policy (%s); "
                "no super admin was created.", "; ".join(problems)
            )
            return None

    sa = SuperAdmin(email=email, password_hash=hash_password(password), name="Super Admin")
    db.session.add(sa)
    try:
        db.session.commit()
    except Exception:
        # Another worker created it first (unique email); nothing to do.
        db.session.rollback()
        return None

    if generated:
        # Printed once, at creation time only. It is not stored anywhere in clear text.
        print(
            "\n" + "=" * 70
            + f"\n  Super admin created: {email}"
            + f"\n  Generated password : {password}"
            + "\n  This is shown ONCE. Log in and change it now."
            + "\n" + "=" * 70 + "\n",
            file=sys.stdout, flush=True,
        )
    else:
        log.info("Super admin %s created from environment variables.", email)
    return sa
