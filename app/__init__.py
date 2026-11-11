"""Application factory: configuration, database, protections and page routes."""
import os
from pathlib import Path
import yaml
from flask import Flask, render_template, redirect, url_for, request, flash, abort, jsonify, send_file
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from .models import db, User, Application, Invite, Share, AccessLog

login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
BASE = Path(__file__).resolve().parent.parent


def _load_env():
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def _read_config():
    folder = BASE / "config"
    names = ("scheme.yaml", "texts.yaml", "roadmap.yaml", "links.yaml", "food_guide.yaml", "risk_rules.yaml", "pack_checklist.yaml", "glossary.yaml")
    loaded = {}
    for name in names:
        path = folder / name
        if not path.is_file():
            raise RuntimeError(f"Required configuration is missing: {path.name}")
        with path.open(encoding="utf8") as source:
            loaded[path.stem] = yaml.safe_load(source)
        if not loaded[path.stem]:
            raise RuntimeError(f"Configuration is empty or malformed: {path.name}")
    # Keep guidance adjacent to BTWEA for route code while retaining its
    # separately labelled top-level section in scheme.yaml.
    loaded["scheme"]["btwea"].setdefault("ldc_guidance", loaded["scheme"].get("ldc_guidance", {}))
    loaded["forms"] = {}
    forms_folder = folder / "forms"
    for path in sorted(forms_folder.glob("*.yaml")):
        with path.open(encoding="utf8") as source:
            loaded["forms"][path.stem] = yaml.safe_load(source)
    if not loaded["forms"]:
        raise RuntimeError("Required form-helper configuration is missing.")
    if not all(str(link.get("url", "")).startswith("https://") and link.get("last_verified") for link in loaded["links"].values()):
        raise RuntimeError("Every official link needs an https URL and last_verified date.")
    return loaded


def create_app(test_config=None):
    _load_env()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", ""),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///app.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        MAIL_BACKEND=os.getenv("MAIL_BACKEND", "file"),
        MAIL_FROM=os.getenv("MAIL_FROM", "noreply@saor.example"),
        APP_BASE_URL=os.getenv("APP_BASE_URL", "http://localhost:5000"),
        INVITE_EXPIRY_DAYS=int(os.getenv("INVITE_EXPIRY_DAYS", "7")),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["MAIL_BACKEND"] not in ("file", "console"):
        raise RuntimeError("MAIL_BACKEND must be 'file' or 'console'.")
    if not app.config.get("SECRET_KEY") or app.config["SECRET_KEY"] == "change-me":
        if not app.debug and not app.testing:
            raise RuntimeError("Set SECRET_KEY in .env before running Saor outside debug mode.")
        app.config["SECRET_KEY"] = "local-development-only"
    app.config["SAOR_CONFIG"] = _read_config()
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please log in to continue."
    csrf.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        return user if user and user.status == "active" else None

    @app.context_processor
    def shared_template_values():
        return {"notice": app.config["SAOR_CONFIG"]["texts"]["notice"], "links": app.config["SAOR_CONFIG"]["links"]}

    from .routes import register_routes
    register_routes(app)
    _register_commands(app)
    return app


def _register_commands(app):
    """CLI commands create the first administrator and labelled demo workspace."""
    import click
    from datetime import date, timedelta
    import json
    import secrets
    from werkzeug.security import generate_password_hash

    @app.cli.command("create-admin")
    def create_admin():
        email = click.prompt("Administrator email").strip().lower()
        password = click.prompt("Password (at least 10 characters)", hide_input=True, confirmation_prompt=True)
        if len(password) < 10:
            raise click.ClickException("Use at least 10 characters.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("An account already uses that email.")
        user = User(email=email, role="admin", status="active")
        user.set_password(password)
        db.session.add(user); db.session.commit()
        click.echo("Administrator account created.")

    @app.cli.command("seed")
    def seed():
        """Load fictional demo accounts and an illustrative vegan snack business."""
        accounts = [
            ("demo-admin@saor.example", "admin"),
            ("demo-applicant@saor.example", "applicant"),
            ("demo-mentor@saor.example", "mentor"),
        ]
        existed = any(User.query.filter_by(email=email).first() for email, _ in accounts)
        password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(12)
        users = {}
        for email, role in accounts:
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(email=email, role=role, status="active")
                user.set_password(password)
                db.session.add(user); db.session.flush()
            users[role] = user
        applicant = users["applicant"]
        record = Application.query.filter_by(user_id=applicant.id).first()
        if not record:
            today = date.today()
            demo = {
                "profile": {"business_name": "Organic Cacao & Oat Energy Bar (60g)", "idea": "Small-batch vegan cacao and oat energy bars, sold to local shops and directly to customers.", "customers": "Local independent food shops, market customers and online repeat buyers.", "where_trade": "Prepared in an appropriate registered kitchen and sold through local retailers and direct orders.", "background": "Demo data: food product development and small-batch production experience.", "town": "Galway", "county": "Galway", "structure": "sole trader", "startup_spend": "1800", "funding": "Illustrative personal savings and start-up planning."},
                "eligibility": {"payment_option": "ja", "claim_start": (today - timedelta(days=420)).isoformat(), "checks": {"age_18": "yes", "under_66": "yes", "right_to_work": "yes", "employed": "no", "new_business": "yes", "in_ireland": "yes", "recent_claim": "no", "already_trading": "no"}},
                "market": {"difference": "A compact, vegan snack with a short ingredient list, careful sourcing and a small-batch local identity. Price and availability will be tested with real customers before launch.", "self_employment": {"one_customer": "no", "sets_prices": "yes", "sets_hours": "yes", "owns_equipment": "yes", "year_round": "yes"}, "competitors": [{"name": "Demo local snack maker A", "location": "Galway", "offering": "Vegan oat bite", "price": 2.3, "distance": 8}, {"name": "Demo local snack maker B", "location": "Galway", "offering": "Cacao protein bar", "price": 2.8, "distance": 11}, {"name": "Demo local snack maker C", "location": "Galway", "offering": "Organic seed bar", "price": 3.4, "distance": 16}]},
                "food": {"hse": True, "allergens": True, "claims": True, "insurance": True, "haccp": False}, "notes": [{"section": "market", "body": "Demo observation: compare local retail prices and package sizes before confirming positioning.", "source": "My own", "link": "", "date": ""}],
                "milestones": {"intreo": {"date": (today - timedelta(days=30)).isoformat()}, "syob": {"date": (today - timedelta(days=22)).isoformat()}},
                "product": {"name": "Organic Cacao & Oat Energy Bar (60g)", "batch_size": 100, "wastage_pct": 0, "labour_minutes": 60, "hourly_rate": 15, "overhead": 0.2, "wholesale": 1.5, "retail": 2.8, "recipe": [{"name": "Gluten-free oats (kg)", "price": 3.5, "quantity": 2.5}, {"name": "Raw cacao powder (kg)", "price": 14, "quantity": 0.8}, {"name": "Agave syrup (kg)", "price": 6, "quantity": 1.5}, {"name": "Compostable wrappers (each)", "price": 0.2, "quantity": 100}]},
                "capacity": {"days": 4, "hours": 4, "batch_hours": 3.5, "setup_hours": 0.5, "help_hours": 0},
                "projection": {"fixed_cost": 950, "units_month": 1600, "wholesale_mix": 60, "weekly_payment": 250, "drawings": 900, "growth_pct": 3},
                "pack": {"btw2": True, "projection": True, "business_plan": True, "syob": True}, "uploads": []
            }
            record = Application(user_id=applicant.id, data_json=json.dumps(demo, ensure_ascii=False))
            db.session.add(record); db.session.flush()
            db.session.add(Share(application_id=record.id, mentor_email=users["mentor"].email, active=True))
        db.session.commit()
        click.echo("Demo data ready. These accounts are fictional and for demonstration only:")
        click.echo(f"Administrator: {accounts[0][0]}")
        click.echo(f"Applicant:     {accounts[1][0]}")
        click.echo(f"Mentor:        {accounts[2][0]}")
        if existed and not os.getenv("DEMO_PASSWORD"):
            click.echo("Existing demo accounts were kept. Their password was not changed or displayed.")
        else:
            click.echo(f"Demo password: {password}")
