"""Page handlers. Business rules are delegated to app.services."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import secrets
import re
from pathlib import Path
import math
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required, login_user, logout_user
from .access import application_for_user
from .models import db, User, Application, Invite, Share, AccessLog
from .services.calculators import product_cost, capacity, project, longest_negative_streak, year_margin, break_even_month, low_sales_months
from .services.eligibility import precheck
from .services.mailer import send_email
from .services.roadmap import roadmap_rows
from .services.risk import build_flags
from .services.dossier import dossier_metrics

PRIVACY_HINT = "Do not include health information, ID or PPS numbers, bank details or other people's personal details."
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _number(form, key, default=0, maximum=None):
    """Parse non-negative form numbers and reject infinities or impossible values."""
    raw = form.get(key, default)
    if raw in (None, ""):
        raw = default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid number for {key.replace('_', ' ')}.")
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        limit = f" and no more than {maximum}" if maximum is not None else ""
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be 0{limit}.")
    return value


def _valid_email(value):
    return bool(EMAIL_PATTERN.fullmatch(value or ""))


def _data(app_record):
    try:
        result = json.loads(app_record.data_json or "{}")
    except (TypeError, json.JSONDecodeError):
        result = {}
    result.setdefault("profile", {})
    result.setdefault("eligibility", {})
    result.setdefault("market", {"competitors": [], "difference": "", "self_employment": {}})
    result.setdefault("food", {})
    result.setdefault("notes", [])
    result.setdefault("milestones", {})
    result.setdefault("product", {"name": "", "batch_size": 1, "recipe": []})
    result.setdefault("capacity", {})
    result.setdefault("projection", {})
    result.setdefault("pack", {})
    result.setdefault("uploads", [])
    return result


def _save(app_record, data):
    app_record.data_json = json.dumps(data, ensure_ascii=False)
    db.session.commit()


def _log(action, application_id=None, target_user_id=None):
    db.session.add(AccessLog(actor_user_id=current_user.id, application_id=application_id,
                             target_user_id=target_user_id, action=action))
    db.session.commit()


def _applicant_app(write=False):
    # Applicant pages may render forms even on GET; mentors must use read-only routes.
    return application_for_user(write=True)


def _summary(app_record):
    data = _data(app_record)
    scheme = current_app.config["SAOR_CONFIG"]["scheme"]["btwea"]
    options = scheme["qualifying"]["payment_options"]
    eligibility = precheck(data["eligibility"], options, minimum_paid_days=scheme["qualifying"]["minimum_paid_days"], paid_days_per_week=scheme["qualifying"]["paid_days_per_week"])
    prod = data["product"]
    cost = product_cost(prod) if prod.get("batch_size") else {"unit_cost": 0, "wholesale_margin": 0, "retail_margin": 0}
    capacity_result = capacity({**data["capacity"], "max_weekly_hours_alone": scheme["ldc_guidance"]["max_weekly_production_hours_alone"]})
    projection_input = {**data["projection"], "product": prod, "year_1_pct": scheme["allowance"]["year_1_pct"], "year_2_pct": scheme["allowance"]["year_2_pct"]}
    rows = project(projection_input)
    return data, eligibility, cost, capacity_result, rows


def register_routes(app):
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = User.query.filter_by(email=email).first()
            if user and user.status == "active" and user.check_password(request.form.get("password", "")):
                login_user(user)
                return redirect(url_for("home"))
            flash("Those sign-in details did not work. Check them and try again.", "error")
        return render_template("login.html", title="Log in")

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html", title="Privacy notice")

    @app.route("/home")
    @login_required
    def home():
        if current_user.role == "admin":
            return redirect(url_for("admin_users"))
        if current_user.role == "mentor":
            return redirect(url_for("mentor_home"))
        return redirect(url_for("roadmap"))

    @app.route("/roadmap", methods=["GET", "POST"])
    @login_required
    def roadmap():
        record = _applicant_app()
        if request.method == "POST":
            data = _data(record)
            key = request.form.get("milestone", "")
            if key in {"intreo", "syob", "ldc", "pack_sent", "decision", "trading"}:
                data["milestones"][key] = {"date": request.form.get("date", ""), "outcome": request.form.get("outcome", "")}
                _save(record, data)
                flash("Roadmap update saved.", "success")
            return redirect(url_for("roadmap"))
        data, eligibility, cost, cap, rows = _summary(record)
        steps = app.config["SAOR_CONFIG"]["roadmap"]
        guidance = app.config["SAOR_CONFIG"]["scheme"]["btwea"]["ldc_guidance"]
        flags = build_flags(data, eligibility, cap, rows, guidance)
        rows_view = roadmap_rows(steps, data, eligibility, flags)
        actions = []
        next_step = next((step for step in rows_view if step["status"] == "Do now"), None)
        if next_step:
            actions.append({"title": next_step["title"], "detail": next_step["detail"], "link": next_step["link"]})
        acknowledged = set(data.get("risk_acknowledged", []))
        red_flag = next((flag for flag in flags if flag["severity"] == "Red" and flag["id"] not in acknowledged), None)
        if red_flag:
            actions.append({"title": red_flag["title"], "detail": red_flag["fix"], "link": "/risks"})
        if not data["product"].get("name") or not data["capacity"].get("days") or not data["projection"].get("units_month"):
            actions.append({"title": "Add what you know about your numbers", "detail": "Product, capacity and sales assumptions are needed for the projection.", "link": "/numbers"})
        return render_template("roadmap.html", title="Your roadmap", steps=rows_view, milestones=data["milestones"],
                               actions=actions[:3],
                               eligibility=eligibility, warning=app.config["SAOR_CONFIG"]["texts"]["premature_trading"],
                               revenue=app.config["SAOR_CONFIG"]["texts"]["revenue_timing"],
                               official=app.config["SAOR_CONFIG"]["links"]["btwea_guidelines"])

    @app.route("/eligibility", methods=["GET", "POST"])
    @login_required
    def eligibility_page():
        record = _applicant_app()
        data = _data(record)
        config = app.config["SAOR_CONFIG"]["scheme"]["btwea"]
        options = config["qualifying"]["payment_options"]
        if request.method == "POST":
            checks = {key: request.form.get(key, "") for key in ("age_18", "under_66", "right_to_work", "employed", "new_business", "in_ireland", "recent_claim", "already_trading")}
            data["eligibility"] = {"payment_option": request.form.get("payment_option", ""), "claim_start": request.form.get("claim_start", ""), "checks": checks}
            data["eligibility"]["result"] = precheck(data["eligibility"], options, minimum_paid_days=config["qualifying"]["minimum_paid_days"], paid_days_per_week=config["qualifying"]["paid_days_per_week"])
            _save(record, data)
            flash("Your answers are saved and the estimate is refreshed.", "success")
            return redirect(url_for("eligibility_page"))
        result = precheck(data["eligibility"], options, minimum_paid_days=config["qualifying"]["minimum_paid_days"], paid_days_per_week=config["qualifying"]["paid_days_per_week"])
        return render_template("eligibility.html", title="Eligibility pre-check", data=data["eligibility"], result=result, options=options,
                               official=app.config["SAOR_CONFIG"]["links"]["btwea_guidelines"])

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        record = _applicant_app(); data = _data(record)
        if request.method == "POST":
            fields = ("business_name", "idea", "customers", "where_trade", "background", "town", "county", "structure", "startup_spend", "funding")
            data["profile"] = {key: request.form.get(key, "").strip() for key in fields}
            try:
                data["profile"]["startup_spend"] = _number(request.form, "startup_spend")
            except ValueError as error:
                flash(str(error), "error"); return redirect(url_for("profile"))
            _save(record, data); flash("Business profile saved.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html", title="Your business profile", profile_data=data["profile"], hint=PRIVACY_HINT)

    @app.route("/research", methods=["GET", "POST"])
    @login_required
    def research():
        record = _applicant_app(); data = _data(record); market = data["market"]
        if request.method == "POST":
            action = request.form.get("action")
            if action == "competitor":
                try:
                    name = request.form.get("name", "").strip()
                    if not name: raise ValueError("Add a competitor business name.")
                    market["competitors"].append({"name": name, "location": request.form.get("location", "").strip(), "offering": request.form.get("offering", "").strip(), "price": _number(request.form, "price"), "distance": _number(request.form, "distance")})
                except ValueError as error:
                    flash(str(error), "error"); return redirect(url_for("research"))
            elif action == "remove_competitor":
                index = int(request.form.get("index", -1))
                if 0 <= index < len(market["competitors"]): market["competitors"].pop(index)
            elif action == "market":
                market["difference"] = request.form.get("difference", "").strip()
                market["self_employment"] = {key: request.form.get(key, "") for key in ("one_customer", "sets_prices", "sets_hours", "owns_equipment", "year_round")}
            elif action == "note":
                link = request.form.get("link", "").strip()
                if link and not link.startswith("https://"):
                    flash("Source links must begin with https://.", "error"); return redirect(url_for("research"))
                data["notes"].append({"section": request.form.get("section", "market"), "body": request.form.get("body", "").strip(), "source": request.form.get("source", "My own"), "link": link, "date": request.form.get("source_date", "")})
            _save(record, data); flash("Research saved.", "success"); return redirect(url_for("research"))
        return render_template("research.html", title="Market research", market=market, notes=data["notes"], hint=PRIVACY_HINT)

    @app.route("/food", methods=["GET", "POST"])
    @login_required
    def food():
        record = _applicant_app(); data = _data(record); items = app.config["SAOR_CONFIG"]["food_guide"]
        if request.method == "POST":
            first_sale = request.form.get("planned_first_sale_date", "")
            data["food"] = {**data["food"], **{item["id"]: request.form.get(item["id"]) == "on" for item in items}, "planned_first_sale_date": first_sale}
            _save(record, data); flash("Food guide progress saved.", "success"); return redirect(url_for("food"))
        notify_by = None
        if data["food"].get("planned_first_sale_date"):
            try: notify_by = (date.fromisoformat(data["food"]["planned_first_sale_date"]) - timedelta(days=28)).isoformat()
            except ValueError: pass
        return render_template("food.html", title="Food guide", items=items, done=data["food"], links=app.config["SAOR_CONFIG"]["links"], uploads=data["uploads"], notify_by=notify_by)

    @app.route("/numbers", methods=["GET", "POST"])
    @login_required
    def numbers():
        record = _applicant_app(); data = _data(record)
        if request.method == "POST":
            try:
                batch_size = _number(request.form, "batch_size", 1)
                if batch_size < 1 or not batch_size.is_integer(): raise ValueError("Batch size must be a whole number of at least 1.")
                data["product"] = {"name": request.form.get("product_name", "").strip(), "batch_size": int(batch_size), "wastage_pct": _number(request.form, "wastage_pct", 0, 100), "labour_minutes": _number(request.form, "labour_minutes"), "hourly_rate": _number(request.form, "hourly_rate"), "overhead": _number(request.form, "overhead"), "wholesale": _number(request.form, "wholesale"), "retail": _number(request.form, "retail"), "recipe": []}
                ingredient_names = request.form.getlist("ingredient_name")
                ingredient_prices = request.form.getlist("ingredient_price")
                quantities = request.form.getlist("ingredient_qty")
                for name, price, quantity in zip(ingredient_names, ingredient_prices, quantities):
                    if name.strip(): data["product"]["recipe"].append({"name": name.strip(), "price": _number({"price": price}, "price"), "quantity": _number({"quantity": quantity}, "quantity")})
                    elif price or quantity: raise ValueError("Give each ingredient a name, price and quantity.")
            except ValueError as error:
                flash(str(error), "error"); return redirect(url_for("numbers"))
            try:
                data["capacity"] = {key: _number(request.form, key) for key in ("days", "hours", "batch_hours", "setup_hours", "help_hours")}
            except ValueError as error:
                flash(str(error), "error"); return redirect(url_for("numbers"))
            data["capacity"]["batch_size"] = data["product"]["batch_size"]
            try:
                data["projection"] = {key: _number(request.form, key, 30 if key == "sales_down_pct" else 10 if key == "ingredient_up_pct" else 0, 100 if key in ("wholesale_mix", "sales_down_pct") else None) for key in ("fixed_cost", "units_month", "wholesale_mix", "weekly_payment", "drawings", "growth_pct", "sales_down_pct", "ingredient_up_pct")}
            except ValueError as error:
                flash(str(error), "error"); return redirect(url_for("numbers"))
            _save(record, data); flash("Product and projection inputs saved.", "success"); return redirect(url_for("numbers"))
        prod = data["product"]
        cost = product_cost(prod)
        scheme = app.config["SAOR_CONFIG"]["scheme"]["btwea"]
        cap = capacity({**data["capacity"], "batch_size": prod["batch_size"], "max_weekly_hours_alone": scheme["ldc_guidance"]["max_weekly_production_hours_alone"]})
        rows = project({**data["projection"], "product": prod, "year_1_pct": scheme["allowance"]["year_1_pct"], "year_2_pct": scheme["allowance"]["year_2_pct"]})
        return render_template("numbers.html", title="Your numbers", data=data, cost=cost, cap=cap, rows=rows,
                               margin_1=year_margin(rows, 1), margin_2=year_margin(rows, 2), worst_streak=longest_negative_streak(rows, "worse"),
                               break_even=break_even_month(rows), low_sales=low_sales_months(rows))

    @app.route("/risks", methods=["GET", "POST"])
    @login_required
    def risks():
        record = _applicant_app(); data, eligibility, cost, cap, rows = _summary(record)
        if request.method == "POST":
            data["risk_acknowledged"] = request.form.getlist("acknowledged")
            _save(record, data); flash("Risk review saved. Flags remain visible so you can keep working on them.", "success")
            return redirect(url_for("risks"))
        guidance = app.config["SAOR_CONFIG"]["scheme"]["btwea"]["ldc_guidance"]
        flags = build_flags(data, eligibility, cap, rows, guidance)
        red_ids = {flag["id"] for flag in flags if flag["severity"] == "Red"}
        kept_acknowledgements = [item for item in data.get("risk_acknowledged", []) if item in red_ids]
        if kept_acknowledgements != data.get("risk_acknowledged", []):
            data["risk_acknowledged"] = kept_acknowledgements
            _save(record, data)
        return render_template("risks.html", title="Risk review", flags=flags, warning=app.config["SAOR_CONFIG"]["texts"]["premature_trading"], acknowledged=set(data.get("risk_acknowledged", [])))

    @app.route("/pack", methods=["GET", "POST"])
    @login_required
    def pack():
        record = _applicant_app(); data = _data(record)
        if request.method == "POST":
            data["pack"] = {key: request.form.get(key) == "on" for key in ("btw2", "projection", "business_plan", "syob")}
            _save(record, data); flash("Checklist saved.", "success"); return redirect(url_for("pack"))
        checks = [("btw2", "Completed Form BTW 2 with your Enterprise Officer"), ("projection", "One-year financial projection"), ("business_plan", "Full business plan, including business structure"), ("syob", "Confirmation of your Start Your Own Business course")]
        return render_template("pack.html", title="Application pack", checks=checks, saved=data["pack"], links=app.config["SAOR_CONFIG"]["links"])

    @app.route("/share", methods=["GET", "POST"])
    @login_required
    def share():
        record = _applicant_app(); data = _data(record)
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            if not _valid_email(email): flash("Enter a valid email address.", "error")
            else:
                item = Share.query.filter_by(application_id=record.id, mentor_email=email).first()
                if item: item.active = True
                else: db.session.add(Share(application_id=record.id, mentor_email=email, active=True))
                db.session.commit(); _log("share", record.id); flash("Mentor access updated. They need an invited mentor account using this email.", "success")
            return redirect(url_for("share"))
        shares = Share.query.filter_by(application_id=record.id, active=True).all()
        log = AccessLog.query.filter_by(application_id=record.id).order_by(AccessLog.created_at.desc()).all()
        return render_template("share.html", title="Share with a mentor", shares=shares, log=log)

    @app.post("/share/<int:share_id>/remove")
    @login_required
    def unshare(share_id):
        record = _applicant_app(); item = Share.query.filter_by(id=share_id, application_id=record.id).first_or_404()
        item.active = False; db.session.commit(); _log("unshare", record.id); flash("Mentor access removed.", "success"); return redirect(url_for("share"))

    @app.route("/mentor")
    @login_required
    def mentor_home():
        if current_user.role != "mentor": abort(403)
        records = Application.query.join(Share, Share.application_id == Application.id).filter(Share.mentor_email == current_user.email, Share.active.is_(True)).all()
        for record in records: _log("mentor_view", record.id)
        return render_template("mentor.html", title="Shared workspaces", records=records)

    @app.route("/mentor/<int:application_id>")
    @login_required
    def mentor_view(application_id):
        if current_user.role != "mentor": abort(403)
        record = application_for_user(application_id, write=False); _log("mentor_view", record.id)
        data, eligibility, cost, cap, rows = _summary(record)
        return render_template("mentor_view.html", title="Mentor view", record=record, data=data, eligibility=eligibility, cost=cost, cap=cap, rows=rows)

    @app.route("/mentor/<int:application_id>/dossier")
    @login_required
    def mentor_dossier(application_id):
        if current_user.role != "mentor": abort(403)
        record = application_for_user(application_id, write=False); _log("mentor_view_dossier", record.id)
        data, eligibility, cost, cap, rows = _summary(record)
        guidance = app.config["SAOR_CONFIG"]["scheme"]["btwea"]["ldc_guidance"]
        return render_template("dossier.html", title="Applicant dossier · read only", data=data, eligibility=eligibility, cost=cost, cap=cap, rows=rows,
                               warning=app.config["SAOR_CONFIG"]["texts"]["premature_trading"], links=app.config["SAOR_CONFIG"]["links"],
                               config_food=app.config["SAOR_CONFIG"]["food_guide"], margin1=year_margin(rows, 1), margin2=year_margin(rows, 2),
                               metrics=dossier_metrics(rows, cost, cap), risk_flags=build_flags(data, eligibility, cap, rows, guidance), read_only=True)

    @app.route("/dossier")
    @login_required
    def dossier():
        if current_user.role == "mentor":
            return redirect(url_for("mentor_home"))
        record = _applicant_app(); data, eligibility, cost, cap, rows = _summary(record)
        guidance = app.config["SAOR_CONFIG"]["scheme"]["btwea"]["ldc_guidance"]
        return render_template("dossier.html", title="Your dossier", data=data, eligibility=eligibility, cost=cost, cap=cap, rows=rows,
                               warning=app.config["SAOR_CONFIG"]["texts"]["premature_trading"], links=app.config["SAOR_CONFIG"]["links"],
                               config_food=app.config["SAOR_CONFIG"]["food_guide"], margin1=year_margin(rows, 1), margin2=year_margin(rows, 2),
                               metrics=dossier_metrics(rows, cost, cap), risk_flags=build_flags(data, eligibility, cap, rows, guidance))

    @app.route("/forms/<form_id>")
    @login_required
    def form_helper(form_id):
        if form_id not in {"btw2", "tr1", "hse"}: abort(404)
        record = _applicant_app(); data = _data(record)
        fields = {
            "btw2": [("Business name", data["profile"].get("business_name", "")), ("Business idea", data["profile"].get("idea", "")), ("Business structure", data["profile"].get("structure", "")), ("Town and county", f"{data['profile'].get('town', '')}, {data['profile'].get('county', '')}")],
            "tr1": [("Business name", data["profile"].get("business_name", "")), ("Business structure", data["profile"].get("structure", "")), ("Planned start-up spend", data["profile"].get("startup_spend", ""))],
            "hse": [("Business name", data["profile"].get("business_name", "")), ("Food product", data["product"].get("name", "")), ("Town and county", f"{data['profile'].get('town', '')}, {data['profile'].get('county', '')}")],
        }[form_id]
        links = app.config["SAOR_CONFIG"]["links"]
        official = links["revenue_tr1" if form_id == "tr1" else "hse_food" if form_id == "hse" else "btwea_guidelines"]
        return render_template("form_helper.html", title={"btw2": "Form BTW 2 helper", "tr1": "Revenue Form TR1 helper", "hse": "HSE notification helper"}[form_id], fields=fields, official=official,
                               warning=app.config["SAOR_CONFIG"]["texts"]["premature_trading"], revenue=app.config["SAOR_CONFIG"]["texts"]["revenue_timing"], form_id=form_id,
                               reference_id={"btw2": "btw2", "tr1": "tr1", "hse": "hse"}[form_id])

    @app.route("/reference/<reference_id>")
    @login_required
    def reference_pdf(reference_id):
        if current_user.role not in {"applicant", "mentor"}:
            abort(403)
        filenames = {
            "btw2": "Back_to_Work_Enterprise_Allowance_-_BTW_2_Application_Form.pdf",
            "tr1": "Revenue TR1 Form.pdf",
            "hse": "Notify the HSE about starting a food business.pdf",
            "btwea": "Operational Guidelines: Back to Work Enterprise Allowance.pdf",
            "allowance": "Back to Work Enterprise Allowance.pdf",
        }
        filename = filenames.get(reference_id)
        if not filename:
            abort(404)
        path = Path(current_app.root_path).parent / "reference" / filename
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=False, download_name=filename)

    @app.route("/export")
    @login_required
    def export():
        if current_user.role != "applicant": abort(403)
        record = _applicant_app(); _log("export", record.id)
        return jsonify({"email": current_user.email, "application": _data(record)})

    @app.route("/account/delete", methods=["GET", "POST"])
    @login_required
    def delete_account():
        if current_user.role != "applicant": abort(403)
        record = _applicant_app()
        if request.method == "POST" and request.form.get("confirm") == "yes":
            user_id = current_user.id
            folder = Path(app.config["UPLOAD_FOLDER"]) / str(record.id)
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
            Share.query.filter_by(application_id=record.id).delete()
            Invite.query.filter_by(user_id=user_id).delete()
            db.session.add(AccessLog(actor_user_id=user_id, application_id=record.id, action="delete"))
            db.session.delete(record); user = db.session.get(User, user_id); db.session.delete(user); db.session.commit()
            logout_user(); flash("Your account and saved work were deleted.", "success"); return redirect(url_for("login"))
        return render_template("delete.html", title="Delete account")

    @app.route("/upload", methods=["POST"])
    @login_required
    def upload():
        record = _applicant_app(write=True); file = request.files.get("file")
        allowed = {"pdf", "doc", "docx", "png", "jpg", "jpeg"}
        if not file or not file.filename or "." not in file.filename:
            flash("Choose a PDF, Word, PNG or JPG document.", "error"); return redirect(url_for("food"))
        extension = file.filename.rsplit(".", 1)[1].lower()
        if extension not in allowed:
            flash("This file type is not supported.", "error"); return redirect(url_for("food"))
        header = file.stream.read(8)
        file.stream.seek(0)
        signatures = {
            "pdf": lambda value: value.startswith(b"%PDF-"),
            "png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpg": lambda value: value.startswith(b"\xff\xd8\xff"),
            "jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
            "doc": lambda value: value.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
            "docx": lambda value: value.startswith(b"PK\x03\x04"),
        }
        if not signatures[extension](header):
            flash("The file contents do not match the selected file type.", "error"); return redirect(url_for("food"))
        folder = Path(app.config["UPLOAD_FOLDER"]) / str(record.id); folder.mkdir(parents=True, exist_ok=True)
        stored = secrets.token_hex(24) + "." + extension; file.save(folder / stored)
        data = _data(record); data["uploads"].append({"name": secure_filename(file.filename), "stored": stored, "size": (folder / stored).stat().st_size})
        _save(record, data); flash("Document uploaded to your private workspace.", "success"); return redirect(url_for("food"))

    @app.route("/uploads/<int:application_id>/<stored>")
    @login_required
    def download(application_id, stored):
        record = application_for_user(application_id, write=False)
        data = _data(record); item = next((x for x in data["uploads"] if x["stored"] == stored), None)
        if not item: abort(404)
        path = Path(app.config["UPLOAD_FOLDER"]) / str(record.id) / stored
        if not path.is_file(): abort(404)
        return send_file(path, as_attachment=True, download_name=item["name"])

    @app.route("/admin/users", methods=["GET", "POST"])
    @login_required
    def admin_users():
        if current_user.role != "admin": abort(403)
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower(); role = request.form.get("role", "applicant")
            if not _valid_email(email) or role not in {"applicant", "mentor"}:
                flash("Enter a valid email and account type.", "error")
            elif User.query.filter_by(email=email).first():
                flash("An account already uses that email.", "error")
            else:
                user = User(email=email, role=role, status="invited", invited_by_user_id=current_user.id); db.session.add(user); db.session.flush()
                if role == "applicant": db.session.add(Application(user_id=user.id, data_json="{}"))
                filename = _new_invitation(user)
                db.session.commit(); _admin_log("invite", user.id)
                flash(f"Invitation recorded in {filename}. No real email is sent in this version.", "success")
            return redirect(url_for("admin_users"))
        users = User.query.order_by(User.created_at.desc()).all()
        accounts = [{"user": user, "inviter": db.session.get(User, user.invited_by_user_id) if user.invited_by_user_id else None} for user in users]
        return render_template("admin.html", title="Manage accounts", accounts=accounts)

    def _new_invitation(user):
        token = secrets.token_urlsafe(32); digest = hashlib.sha256(token.encode()).hexdigest()
        for invite in Invite.query.filter_by(user_id=user.id).all(): invite.used_at = datetime.now(timezone.utc)
        invite = Invite(user_id=user.id, token_hash=digest, expires_at=datetime.now(timezone.utc) + timedelta(days=app.config["INVITE_EXPIRY_DAYS"]))
        db.session.add(invite)
        link = f"{app.config['APP_BASE_URL'].rstrip('/')}/invite/{token}"
        inviter = db.session.get(User, user.invited_by_user_id) if user.invited_by_user_id else None
        who = inviter.email if inviter else "your administrator"
        body = f"You have been invited to Saor by {who}.\n\nSet your password here: {link}\nThis link is valid for {app.config['INVITE_EXPIRY_DAYS']} days.\n\nIndependent preparation tool. Not part of Intreo, the Department of Social Protection or any LDC.\nIf you were not expecting this email, ignore it."
        return send_email(app, user.email, "You have been invited to Saor", body)

    def _admin_log(action, target):
        db.session.add(AccessLog(actor_user_id=current_user.id, target_user_id=target, action=action)); db.session.commit()

    @app.post("/admin/users/<int:user_id>/<action>")
    @login_required
    def admin_action(user_id, action):
        if current_user.role != "admin": abort(403)
        user = db.session.get(User, user_id) or abort(404)
        if action == "resend":
            filename = _new_invitation(user); db.session.commit(); _admin_log("resend", user.id)
            flash(f"New set-password link recorded in {filename}. Older links no longer work.", "success")
        elif action in ("deactivate", "reactivate"):
            if user.id == current_user.id and action == "deactivate": abort(400)
            user.status = "deactivated" if action == "deactivate" else "active"; db.session.commit(); _admin_log(action, user.id)
            flash(f"Account {action}d.", "success")
        else: abort(404)
        return redirect(url_for("admin_users"))

    @app.route("/invite/<token>", methods=["GET", "POST"])
    def accept_invite(token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        invite = Invite.query.filter_by(token_hash=digest).first()
        valid = invite and not invite.used_at and invite.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        if not valid:
            return render_template("invite.html", title="Set your password", invalid=True), 400
        user = db.session.get(User, invite.user_id)
        if request.method == "POST":
            password = request.form.get("password", ""); confirm = request.form.get("confirm", "")
            if len(password) < 10: flash("Use at least 10 characters.", "error")
            elif password != confirm: flash("The passwords do not match.", "error")
            elif request.form.get("consent") != "yes": flash("Please read the privacy notice and confirm to continue.", "error")
            else:
                user.set_password(password); user.status = "active"; user.consent_at = datetime.now(timezone.utc); invite.used_at = datetime.now(timezone.utc); db.session.commit()
                flash("Your account is ready. You can now log in.", "success"); return redirect(url_for("login"))
        return render_template("invite.html", title="Set your password", invalid=False, email=user.email)

    @app.route("/notes", methods=["POST"])
    @login_required
    def add_note():
        return redirect(url_for("research"))
