import os
import re
import csv
import io
import json
import math
import base64
import smtplib
import secrets
import hmac
import hashlib
import html
import threading
import time
import random
import uuid
from urllib.parse import urlparse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, render_template_string, redirect, url_for, flash, Response, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func
from sqlalchemy.orm import deferred
from sqlalchemy.exc import IntegrityError, OperationalError, DataError, InterfaceError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
import click
try:
    from transformers import pipeline
except ImportError:
    pipeline = None

# Headless thread-safe Matplotlib configuration
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

# ==========================================
# APP INITIALIZATION & ENVIRONMENT SECRETS
# ==========================================
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # the site sits behind an HTTPS proxy (Caddy / Cloudflare) in production

def _load_secret_key():
    env_key = os.getenv("SECRET_KEY")
    if env_key: return env_key
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flask_secret_key")
    try:
        if os.path.exists(key_path):
            with open(key_path, "r") as fh:
                saved = fh.read().strip()
            if saved: return saved
        new_key = secrets.token_hex(32)
        with open(key_path, "w") as fh: fh.write(new_key)
        try: os.chmod(key_path, 0o600)
        except OSError: pass
        return new_key
    except OSError:
        return secrets.token_hex(32)

app.secret_key = _load_secret_key()
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "postgresql://postgres:admin@localhost:5432/ccc_sentiment").replace("postgres://", "postgresql://", 1)   # some hosts hand out the old "postgres://" form
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Hardened Cookie Policies
app.config['SESSION_COOKIE_SECURE'] = os.getenv("FLASK_ENV") == "production"
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"

try: SESSION_IDLE_DAYS = max(1, int(os.getenv("SESSION_IDLE_DAYS", "30")))
except ValueError: SESSION_IDLE_DAYS = 30
SESSION_IDLE_LIFETIME = timedelta(days=SESSION_IDLE_DAYS)
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_IDLE_LIFETIME
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['REMEMBER_COOKIE_DURATION'] = SESSION_IDLE_LIFETIME
app.config['REMEMBER_COOKIE_REFRESH_EACH_REQUEST'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = app.config['SESSION_COOKIE_SECURE']
app.config['REMEMBER_COOKIE_SAMESITE'] = "Lax"
app.config['WTF_CSRF_TIME_LIMIT'] = None

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgresql"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_timeout": 10,
        "connect_args": {"connect_timeout": 5, "options": "-c statement_timeout=20000"},
    }

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["2000 per hour"], storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))   # set RATELIMIT_STORAGE_URI (e.g. a Redis URL) when running more than one worker

# ==========================================
# LIVE SMTP GMAIL DISPATCH CONFIGURATION
# ==========================================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
MAIL_SENDER = os.getenv("MAIL_SENDER", "sentimentanalysissystem@gmail.com")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "") 

_mail_pool = ThreadPoolExecutor(max_workers=2)

def send_verification_email(recipient_email, code, username, purpose="verify"):
    try:
        is_reset = (purpose == "reset")
        msg = EmailMessage()
        msg['Subject'] = (
            "City College of Calamba — Password Reset Code"
            if is_reset else
            "City College of Calamba — Community Portal Passcode"
        )
        msg['From'] = f"CCC Community Feedback Collective <{MAIL_SENDER}>"
        msg['To'] = recipient_email
        safe_username = html.escape(username)
        action_line = (
            "We received a request to reset your password. Enter the 6-digit security code below to set a new password:"
            if is_reset else
            "Welcome to the student community voice collective. Use your 6-digit code below to activate your account:"
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, sans-serif; background-color: #070d1d; color: #f8fafc; padding: 30px; margin: 0;">
            <div style="max-width: 500px; margin: 0 auto; background: #0f1a30; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 28px; text-align: center;">
                <h2 style="color: #60a5fa; margin: 0 0 6px 0; font-size: 20px;">City College of Calamba</h2>
                <p style="color: #94a3b8; font-size: 12px; text-transform: uppercase;">Participatory Student Feedback Collective</p>
                <div style="border-top: 1px solid rgba(255,255,255,0.08); margin: 18px 0;"></div>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left;">Hello <strong>{safe_username}</strong>,</p>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left;">{action_line}</p>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #fbbf24; background: #070d1d; border: 1.5px dashed rgba(245, 158, 11, 0.6); padding: 14px; border-radius: 10px; margin: 24px 0;">
                    {code}
                </div>
                <p style="color: #94a3b8; font-size: 12px; text-align: left;">This passcode confirms your institutional identity. Do not share this code. It will expire in 10 minutes.</p>
            </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype='html')

        if not MAIL_PASSWORD: return
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(MAIL_SENDER, MAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"[-] SMTP Delivery Notice: {e}")

# ==========================================
# ERROR HANDLING & API GUARDS
# ==========================================
class ClientError(ValueError): pass
class ModelUnavailable(RuntimeError): pass

def json_body():
    data = request.get_json(silent=True)
    if data is None: raise ClientError("Request body must be valid JSON.")
    if not isinstance(data, dict): raise ClientError("Request body must be a JSON object.")
    return data

def sfield(data, key, default="", max_len=None, label=None):
    v = data.get(key, default)
    if v is None: v = default
    if not isinstance(v, str): raise ClientError(f"'{label or key}' must be text.")
    v = v.strip()
    if max_len and len(v) > max_len: raise ClientError(f"'{label or key}' is too long (max {max_len} characters).")
    return v

def ifield(data, key, default=None, label=None):
    v = data.get(key, default)
    if v is None: raise ClientError(f"'{label or key}' is required.")
    if isinstance(v, bool): raise ClientError(f"'{label or key}' must be a number.")
    try: n = int(v)
    except (TypeError, ValueError): raise ClientError(f"'{label or key}' must be a number.")
    if abs(n) > 2_000_000_000: raise ClientError(f"'{label or key}' is out of range.")
    return n

def text_of(v): return v.strip() if isinstance(v, str) else ""

# SECURE BROWSER CACHE LOCKOUT
@app.after_request
def apply_security_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.endpoint == "form_header_image" and response.status_code == 200:
        pass   # keeps the private, versioned cache header set by the route
    else:
        # Aggressively block BFCache (Back-Forward Cache) for authenticated pages
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@app.context_processor
def inject_asset_url():
    def asset_url(filename):
        try: v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError: v = 0
        return url_for('static', filename=filename, v=v)
    return {"asset_url": asset_url}

EXP_NOTE_RE = re.compile(r'^EXP:(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?\|$')

def clean_expiry_tag(value):
    if value is None or value == "": return None
    if not isinstance(value, str): raise ClientError("Invalid expiration value.")
    m = EXP_NOTE_RE.match(value.strip())
    if not m: raise ClientError("Invalid expiration value.")
    try:
        when = datetime.strptime(f"{m.group(1)} {m.group(2) or '23:59'}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise ClientError("Invalid expiration date.")
    if when < datetime.now(): raise ClientError("Expiration must be a date and time that has not passed yet.")
    return value.strip()

@app.errorhandler(CSRFError)
def csrf_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Session expired or invalid CSRF token. Reload the page."}), 400
    if current_user.is_authenticated:
        return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard')) 
    return render_template("auth.html", error="Session expired. Please log in again.", mode="login"), 400

FRIENDLY_HTTP = {
    400: "The request could not be understood. Please refresh the page and try again.",
    401: "Your session has expired. Please sign in again.",
    403: "You do not have permission to do that.",
    404: "That item or page was not found.",
    405: "That action is not allowed here.",
    413: "That upload or post is too large.",
    415: "The request must be sent as JSON.",
    429: "Too many requests. Please wait a moment and try again.",
}

def classify_exception(e):
    if isinstance(e, ClientError): return str(e), 400, False
    if isinstance(e, HTTPException):
        code = e.code or 500
        return FRIENDLY_HTTP.get(code, e.description or "Request failed."), code, code >= 500
    if isinstance(e, csv.Error): return "The CSV file is malformed or contains invalid characters.", 400, False
    if isinstance(e, IntegrityError): return "This action conflicts with existing data.", 409, False
    if isinstance(e, DataError): return "One of the submitted values is invalid or too long.", 400, False
    if isinstance(e, (OperationalError, InterfaceError, PoolTimeoutError)): return "The database is busy or temporarily unavailable. Please try again in a moment.", 503, True
    if isinstance(e, ModelUnavailable): return "The AI sentiment engine is still starting up. Please try again shortly.", 503, True
    if isinstance(e, (ValueError, TypeError, KeyError)): return "Invalid request payload.", 400, True
    return "Something went wrong processing your request.", 500, True

def _safe_rollback():
    try: db.session.rollback()
    except Exception: pass

def _session_active():
    """Cheap 'is someone signed in' check that never touches the database (safe inside error handlers)."""
    try: return bool(session.get("_user_id"))
    except Exception: return False

SIGNED_IN_ERROR_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Something went wrong</title>
<style>
  *{box-sizing:border-box} body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:radial-gradient(circle at 50% 0%,#12213f 0%,#070d1c 70%);color:#e2e8f0}
  .card{width:min(460px,100%);background:#14213a;border:1px solid rgba(239,68,68,.5);border-top:6px solid #ef4444;border-radius:18px;padding:30px 26px 24px;text-align:center;box-shadow:0 30px 70px rgba(0,0,0,.55)}
  .ic{width:62px;height:62px;margin:0 auto 14px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(239,68,68,.16);color:#ef4444;font-size:30px;font-weight:800}
  h1{margin:0 0 8px;font-size:1.25rem;color:#f8fafc} p{margin:0;line-height:1.6;color:#cbd5e1;overflow-wrap:anywhere} small{display:block;margin-top:10px;color:#94a3b8}
  .row{display:flex;gap:10px;margin-top:22px} .row>*{flex:1}
  a.btn,button.btn{display:block;width:100%;padding:12px 14px;border-radius:12px;font:inherit;font-weight:700;font-size:.95rem;cursor:pointer;text-decoration:none;text-align:center}
  a.btn{background:#2563eb;color:#fff;border:0} button.btn{background:transparent;color:#fb7185;border:1px solid rgba(244,63,94,.5)}
  button.btn:hover{background:rgba(244,63,94,.12)}
</style></head><body>
<main class="card" role="alert">
  <div class="ic">!</div>
  <h1>Something went wrong</h1>
  <p>{{ msg }}</p>
  <small>You are still signed in. Nothing was lost.</small>
  <div class="row">
    <a class="btn" href="{{ url_for('index') }}">Back to my portal</a>
    <form method="POST" action="{{ url_for('logout') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn" type="submit">Sign Out</button></form>
  </div>
</main></body></html>"""

def signed_in_error_response(msg, status):
    """Error page for people who are still signed in: always offers a way back and a Sign Out button (never the login form)."""
    try:
        resp = Response(render_template_string(SIGNED_IN_ERROR_PAGE, msg=msg), status=status, mimetype="text/html")
    except Exception:
        resp = Response(f"{msg} You are still signed in. Go to / to continue.", status=status, mimetype="text/plain")
    return resp

@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    is_api = request.path.startswith("/api/")
    if isinstance(e, HTTPException) and not is_api:
        if (e.code or 500) < 400 or not _session_active(): return e   # redirects and signed-out visitors keep the default behaviour
    _safe_rollback()
    msg, status, log_it = classify_exception(e)
    if log_it: app.logger.exception("Unhandled error")
    if is_api: return jsonify({"error": msg}), status
    if _session_active(): return signed_in_error_response(msg, status)
    try: return render_template("auth.html", error=msg, mode="login"), status
    except Exception: return msg, status

def api_guard(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            _safe_rollback()
            msg, status, log_it = classify_exception(e)
            if log_it: app.logger.exception(f"API failure in {fn.__name__}")
            return jsonify({"error": msg}), status
    return wrapper

def csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

# ==========================================
# AUTHENTICATION & DATA MODELS
# ==========================================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.session_protection = "basic"

@login_manager.unauthorized_handler
def handle_unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Your session has expired. Please sign in again.", "code": "AUTH_REQUIRED"}), 401
    flash(login_manager.login_message, login_manager.login_message_category)
    return redirect(url_for("login"))

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="Student - Regular")
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.Text, nullable=True)
    verification_hash = db.Column(db.String(64), nullable=True)
    verification_expires = db.Column(db.DateTime, nullable=True)
    verification_attempts = db.Column(db.Integer, default=0, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    tour_seen = db.Column(db.Boolean, default=False)   # has been asked about the guided tour (so the welcome question only appears once)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    privacy_consent_at = db.Column(db.DateTime, nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class UserLoginLog(db.Model):
    __tablename__ = 'user_login_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    login_time = db.Column(db.DateTime, default=datetime.utcnow)

class AcademicYear(db.Model):
    __tablename__ = 'academic_years'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.String(20), unique=True, nullable=False)

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)

def get_active_term():
    """Returns the MISD-configured (academic_year, semester) so Town Hall posts never hard-code the term."""
    try:
        rows = {r.key: r.value for r in SystemSetting.query.filter(SystemSetting.key.in_(["active_academic_year", "active_semester"])).all()}
        yr = rows.get("active_academic_year") or "2026-2027"
        sem = rows.get("active_semester") or "1st Semester"
        return yr, sem
    except Exception:
        _safe_rollback()
        return "2026-2027", "1st Semester"

def set_active_term(year_val, sem_val):
    for k, v in (("active_academic_year", year_val), ("active_semester", sem_val)):
        row = db.session.get(SystemSetting, k)
        if row:
            row.value = v
        else:
            db.session.add(SystemSetting(key=k, value=v))
    db.session.commit()

class EvaluationForm(db.Model):
    __tablename__ = 'evaluation_forms'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, nullable=True)
    form_category = db.Column(db.String(100), nullable=False, default="Community Initiative")
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.String(150), nullable=False, default="ALL")
    subject_code = db.Column(db.String(50), nullable=True)
    section_target = db.Column(db.String(50), nullable=True, default="ALL")
    deadline_date = db.Column(db.String(50), nullable=True)
    max_responses = db.Column(db.Integer, nullable=True, default=0)
    academic_year = db.Column(db.String(20), nullable=False, default="2026-2027")
    semester = db.Column(db.String(30), nullable=False, default="1st Semester")
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by_name = db.Column(db.String(150), nullable=False)
    created_by_role = db.Column(db.String(50), nullable=False)
    questions_json = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    share_token = db.Column(db.String(32), nullable=True)   # unguessable id used by the shareable /s/<token> link
    theme_json = db.Column(db.Text, nullable=True)           # look of the survey: accent colour, background, font, header preset
    header_image = deferred(db.Column(db.Text, nullable=True))   # optional uploaded header picture (validated data URL), only loaded when needed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FormResponseRecord(db.Model):
    __tablename__ = 'form_response_records'
    __table_args__ = (db.UniqueConstraint('form_id', 'student_id', name='uq_form_student'),)
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('evaluation_forms.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class FormAnonymousSubmission(db.Model):
    __tablename__ = 'form_anonymous_submissions'
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('evaluation_forms.id', ondelete='CASCADE'), nullable=False)
    answers_json = db.Column(db.Text, nullable=False)

class Feedback(db.Model):
    __tablename__ = 'feedback_records'
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, nullable=True)
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.String(150), nullable=True, default="General")
    academic_year = db.Column(db.String(20), nullable=False, default="2026-2027")
    semester = db.Column(db.String(30), nullable=False, default="1st Semester")
    raw_text = db.Column(db.Text, nullable=False)
    cleaned_text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.String(20), nullable=False)
    ai_sentiment = db.Column(db.String(20), nullable=True)      # original AI-predicted polarity before any MISD override
    human_sentiment = db.Column(db.String(20), nullable=True)   # MISD human-verified or corrected ground-truth polarity
    verified_by = db.Column(db.String(150), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    confidence = db.Column(db.Float, nullable=False)
    aspect_breakdown = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(50), nullable=False, default="Portal")
    import_batch = db.Column(db.String(36), nullable=True)   # which CSV import brought this row in (lets MISD undo a whole import)
    has_profanity = db.Column(db.Boolean, default=False)       # the original comment contained profanity (the stored text is masked)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class ImportBatch(db.Model):
    __tablename__ = 'import_batches'
    id = db.Column(db.String(36), primary_key=True)
    filename = db.Column(db.String(255), nullable=False, default="")
    uploaded_by = db.Column(db.String(150), nullable=False, default="")
    file_sha256 = db.Column(db.String(64), nullable=True)
    total_rows = db.Column(db.Integer, default=0)
    importable = db.Column(db.Integer, default=0)
    imported = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    duplicates = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="running")     # running | completed | rolled_back
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    rolled_back_at = db.Column(db.DateTime, nullable=True)

class CommunityPost(db.Model):
    __tablename__ = 'community_posts'
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    author_name = db.Column(db.String(150), nullable=True)
    target_channel = db.Column(db.String(50), nullable=False, default="ALL")
    author_department = db.Column(db.String(50), nullable=False, default="DCI")
    author_role = db.Column(db.String(100), nullable=True, default="Student - Regular")
    is_announcement = db.Column(db.Boolean, default=False)
    program = db.Column(db.String(150), nullable=True, default="General")
    category = db.Column(db.String(100), nullable=False, default="Campus Facilities & Infrastructure")
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.Text, nullable=True)
    link_url = db.Column(db.Text, nullable=True)
    is_edited = db.Column(db.Boolean, default=False)
    edited_at = db.Column(db.DateTime, nullable=True)
    sentiment = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    aspect_breakdown = db.Column(db.Text, nullable=False)
    score = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default="Open")
    action_note = db.Column(db.Text, nullable=True)
    action_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CommunityPostVote(db.Model):
    __tablename__ = 'community_post_votes'
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='uq_post_vote'),)
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    vote_type = db.Column(db.Integer, nullable=False, default=1)

class CommunityResolutionVote(db.Model):
    __tablename__ = 'community_resolution_votes'
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='uq_res_vote'),)
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reaction_type = db.Column(db.Integer, nullable=False)

class CommunityComment(db.Model):
    __tablename__ = 'community_comments'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False, index=True)
    author_department = db.Column(db.String(50), nullable=False)
    author_role = db.Column(db.String(100), nullable=True, default="Student - Regular")
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LexiconTerm(db.Model):
    __tablename__ = 'lexicon_terms'
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, int(user_id))
    return u if u and u.is_verified else None

# =========================================================
# INITIALIZATION HELPERS
# =========================================================
DEFAULT_LEXICON = {
    "positive": ["good", "great", "best", "clear", "helpful", "perfect", "nice", "solid", "goods", "mabait", "bait", "maayos", "ayos", "magaling", "galing", "sulit", "malinaw", "linaw", "approachable", "easy", "petiks", "chill", "husay", "mahusay", "sipag", "masipag", "ganda"],
    "negative": ["bad", "worst", "hard", "useless", "hot", "slow", "late", "boring", "sabaw", "lutang", "panget", "mahirap", "hirap", "mainit", "init", "magulo", "gulo", "mabilis", "confusing", "fast", "sungit", "masungit", "kupal", "bagsak", "tamad", "bastos", "walang kwenta", "mabagal", "bagal", "sira"],
    "intensifiers": ["sobrang", "sobra", "masyado", "very", "super", "really", "so", "grabe", "napaka", "ubod", "saksakan", "talaga", "tunay", "lubos"],
    "negations": ["not", "hindi", "di", "never", "wala", "eme", "charot", "charing", "joke"]
}

def seed_database():
    existing_words = {t.word for t in LexiconTerm.query.all()}
    for cat, words in DEFAULT_LEXICON.items():
        for w in words:
            if w.lower() not in existing_words:
                db.session.add(LexiconTerm(word=w.lower(), category=cat))

    existing_years = {y.year for y in AcademicYear.query.all()}
    for yr in ["2024-2025", "2025-2026", "2026-2027"]:
        if yr not in existing_years:
            db.session.add(AcademicYear(year=yr))

    if not db.session.get(SystemSetting, "active_academic_year"):
        db.session.add(SystemSetting(key="active_academic_year", value="2026-2027"))
    if not db.session.get(SystemSetting, "active_semester"):
        db.session.add(SystemSetting(key="active_semester", value="1st Semester"))

    # Auto-provision MISD account on cloud hosts (e.g. Render Free Tier where interactive shell is unavailable)
    misd_pwd = os.getenv("MISD_PASSWORD", "").strip()
    if misd_pwd:
        misd_user = os.getenv("MISD_USERNAME", "misd_admin").strip() or "misd_admin"
        misd_email = os.getenv("MISD_EMAIL", "misd@ccc.edu.ph").strip().lower() or "misd@ccc.edu.ph"
        existing_misd = User.query.filter((User.username == misd_user) | (User.email == misd_email)).first()
        if existing_misd:
            existing_misd.role = "MISD"
            existing_misd.is_verified = True
            existing_misd.set_password(misd_pwd)
        else:
            new_misd = User(username=misd_user, email=misd_email, role="MISD", department="DCI", program="ALL", is_verified=True, privacy_consent_at=datetime.utcnow())
            new_misd.set_password(misd_pwd)
            db.session.add(new_misd)

    db.session.commit()

def setup_database():
    with app.app_context():
        db.create_all()
        alter_queries = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_hash VARCHAR(64);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_expires TIMESTAMP;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_attempts INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(180);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'Student - Regular';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_consent_at TIMESTAMP;",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'DCI';",
            "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS section_target VARCHAR(50) DEFAULT 'ALL';",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'Portal';",
            "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS share_token VARCHAR(32);",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_evaluation_forms_share_token ON evaluation_forms (share_token);",
            "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS theme_json TEXT;",
            "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS header_image TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tour_seen BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS import_batch VARCHAR(36);",
            "CREATE INDEX IF NOT EXISTS ix_feedback_import_batch ON feedback_records (import_batch);",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS has_profanity BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS ai_sentiment VARCHAR(20);",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS human_sentiment VARCHAR(20);",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS verified_by VARCHAR(150);",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP;",
            "UPDATE feedback_records SET ai_sentiment = sentiment WHERE ai_sentiment IS NULL;",
            "UPDATE feedback_records SET program = 'BSIT' WHERE UPPER(TRIM(program)) = 'ACT' OR program ILIKE '%Associate in Computer Technology%';",
            "UPDATE community_posts SET program = 'BSIT' WHERE UPPER(TRIM(program)) = 'ACT' OR program ILIKE '%Associate in Computer Technology%';",
            "CREATE INDEX IF NOT EXISTS ix_feedback_filters ON feedback_records (department, source, academic_year, semester);"
        ]
        for q in alter_queries:
            try:
                db.session.execute(text(q))
                db.session.commit()
            except Exception:
                db.session.rollback()
        seed_database()

@app.cli.command("create-misd")
@click.option("--username", prompt=True)
@click.option("--email", prompt=True)
@click.password_option()
def create_misd_command(username, email, password):
    """Creates (or upgrades) an MISD administrator. MISD accounts cannot be made from the sign-up page, so run this once on a new server."""
    username, email = username.strip(), email.strip().lower()
    user = User.query.filter((User.username == username) | (User.email == email)).first()
    if user:
        user.role = "MISD"; user.is_verified = True; user.set_password(password); action = "updated"
    else:
        user = User(username=username, email=email, role="MISD", department="DCI", program="ALL", is_verified=True)
        user.set_password(password); db.session.add(user); action = "created"
    db.session.commit()
    click.echo(f"MISD account '{username}' {action}.")

@app.cli.command("mask-existing-profanity")
def mask_existing_profanity_command():
    """One-time cleanup: permanently hides profanity in rows saved before the filter existed (feedback, posts, comments, survey answers)."""
    def mask_json(text):
        try: data = json.loads(text)
        except Exception: return text
        return json.dumps(mask_any(data))
    total = 0
    jobs = [(Feedback, ("raw_text", "cleaned_text"), ("aspect_breakdown",)), (CommunityPost, ("content",), ("aspect_breakdown",)),
            (CommunityComment, ("content",), ()), (FormAnonymousSubmission, (), ("answers_json",))]
    for model, text_fields, json_fields in jobs:
        changed = 0
        for i, row in enumerate(model.query.yield_per(500), 1):
            dirty = False
            for f in text_fields:
                old = getattr(row, f)
                if isinstance(old, str) and has_profanity(old):
                    setattr(row, f, mask_profanity(old)); dirty = True
                    if hasattr(row, "has_profanity") and f == "raw_text": row.has_profanity = True
            for f in json_fields:
                old = getattr(row, f)
                if isinstance(old, str):
                    new = mask_json(old)
                    if new != old: setattr(row, f, new); dirty = True
            if dirty: changed += 1
            if i % 500 == 0: db.session.commit()
        db.session.commit()
        click.echo(f"{model.__name__}: {changed} row(s) cleaned")
        total += changed
    click.echo(f"Done. {total} row(s) cleaned in total.")

@app.cli.command("init-db")
def init_db_command():
    setup_database()
    print("Database Initialized successfully.")

# =========================================================
# NLP PIPELINE & ABSA CONFIGURATION (THREAD-SAFE)
# =========================================================
ROBERTA_MODEL_IDENTIFIER = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "").strip()
# On Render's 512MB Free Tier, loading 1.1GB of local PyTorch weights causes an Out-Of-Memory crash unless explicitly enabled
LOW_MEMORY_MODE = os.getenv("LOW_MEMORY_MODE", "1" if os.getenv("RENDER") else "0").strip() == "1"

_init_lock = threading.Lock()
_clf = None
_clf_retry_after = 0.0

def _query_hf_inference_api(text_input):
    """Calls Hugging Face Serverless Inference API for cardiffnlp/twitter-xlm-roberta-base-sentiment (uses 0 MB model RAM on Render)."""
    if not HF_API_TOKEN:
        return None
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{ROBERTA_MODEL_IDENTIFIER}",
        f"https://api-inference.huggingface.co/models/{ROBERTA_MODEL_IDENTIFIER}"
    ]
    payload = json.dumps({"inputs": text_input[:512]}).encode("utf-8")
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Authorization": f"Bearer {HF_API_TOKEN}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # HF API returns [[{"label": "...", "score": ...}, ...]] or [{"label": "...", "score": ...}]
                if isinstance(data, list) and data:
                    candidates = data[0] if isinstance(data[0], list) else data
                    if candidates and isinstance(candidates[0], dict) and "label" in candidates[0]:
                        best = max(candidates, key=lambda x: float(x.get("score", 0.0)))
                        return {"label": best["label"], "score": float(best.get("score", 0.75))}
        except Exception:
            continue
    return None

def get_classifier():
    global _clf, _clf_retry_after
    if HF_API_TOKEN:
        return lambda txt: [_query_hf_inference_api(txt) or {"label": "neutral", "score": 0.75}]
    if LOW_MEMORY_MODE or pipeline is None:
        return lambda txt: [{"label": "neutral", "score": 0.75}]
    if _clf is None:
        if time.time() < _clf_retry_after:
            return lambda txt: [{"label": "neutral", "score": 0.75}]
        with _init_lock:
            if _clf is None:
                try: _clf = pipeline("sentiment-analysis", model=ROBERTA_MODEL_IDENTIFIER, model_kwargs={"local_files_only": True})
                except Exception:
                    try: _clf = pipeline("sentiment-analysis", model=ROBERTA_MODEL_IDENTIFIER)
                    except Exception as load_err:
                        _clf_retry_after = time.time() + 60
                        app.logger.warning("Local RoBERTa load skipped/failed (falling back to lexicon baseline): %s", load_err)
                        return lambda txt: [{"label": "neutral", "score": 0.75}]
    return _clf

ASPECT_CATEGORIES = {
    "Instructional Delivery & Pedagogy": ["lecture", "turo", "explain", "speak", "speaks", "discussion", "mabilis", "fast", "slow", "teaching", "lesson", "clear", "malinaw", "linaw", "confusing", "exam", "quiz", "task", "activity", "galing", "magaling"],
    "Faculty Demeanor & Approachability": ["talk", "approachable", "mabait", "bait", "attitude", "sungit", "masungit", "easy", "friendly", "accommodating", "strict", "patient", "galit", "snob", "ugali", "pakikitungo", "demeanor", "prof", "maam", "sir"],
    "Campus Facilities & Infrastructure": ["room", "classroom", "fan", "electric fan", "aircon", "mainit", "init", "hot", "computer", "wifi", "internet", "projector", "lab", "laboratory", "chair", "upuan"]
}

def get_active_lexicon():
    terms = LexiconTerm.query.all()
    lex = {"positive": set(), "negative": set(), "intensifiers": set(), "negations": set()}
    for t in terms:
        if t.category in lex: lex[t.category].add(t.word.lower())
    # Profanity is read as an intensifier: it makes whatever sentiment it sits next to stronger (the words themselves are never stored or shown)
    lex["intensifiers"] |= {w for w in ({x.lower() for x in DEFAULT_PROFANITY} | {t.word.lower() for t in terms if t.category == "profanity"}) if " " not in w}
    return lex

def preprocess_taglish_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'[^\w\s,\.\-!?]', '', text)
    return text.strip()[:2000]

def segment_compound_text(text):
    clauses = re.split(r"(?<=[.!?])\s+|\b(?:but|pero|kaso|kaso lang|however|although|while|yet)\b", text, flags=re.IGNORECASE)
    cleaned = [c.strip() for c in clauses if len(c.strip()) > 2]
    return cleaned[:12] if cleaned else [text]

def detect_aspect(clause):
    clause_lower = clause.lower()
    for aspect, keywords in ASPECT_CATEGORIES.items():
        if any(re.search(r'\b' + re.escape(k) + r'\b', clause_lower) for k in keywords):
            return aspect
    return "General Academic Feedback"

def strip_tagalog_prefix(word):
    for prefix in ["napaka", "pinaka", "nakaka", "nag", "mag", "ma"]:
        if word.startswith(prefix) and len(word) > len(prefix) + 2:
            return word[len(prefix):]
    return word

def evaluate_clause(clause, lexicon):
    clause_lower = clause.lower()
    roberta_result = get_classifier()(clause[:512])[0]
    raw_label = str(roberta_result['label']).strip().lower()
    roberta_score = round(roberta_result['score'], 4)

    if "pos" in raw_label or raw_label == "label_2": roberta_polarity = "Positive"
    elif "neg" in raw_label or raw_label == "label_0": roberta_polarity = "Negative"
    elif "star" in raw_label:
        stars = int(raw_label[0])
        roberta_polarity = "Positive" if stars >= 4 else "Neutral" if stars == 3 else "Negative"
    else: roberta_polarity = "Neutral"

    words = re.findall(r'\b\w+\b', clause_lower)
    token_scores = []
    net_lexical_score = 0.0
    pending_negation = False
    pending_intensifier = 1.0
    sarcasm_markers = {"eme", "charot", "charing", "joke"}

    for word in words:
        root = strip_tagalog_prefix(word)
        token_info = {"word": word, "base_score": 0, "final_score": 0.0, "role": "Neutral (0)"}

        if word in sarcasm_markers or root in sarcasm_markers:
            token_info["role"] = "Sarcasm Invalidator"
            token_info["base_score"] = -1
            token_info["final_score"] = -1.0
            token_scores.append(token_info)
            continue

        if word in lexicon["negations"] or root in lexicon["negations"]:
            pending_negation = True
            token_info["role"] = "Negator (Inverts Next)"
        elif word in lexicon["intensifiers"] or root in lexicon["intensifiers"]:
            pending_intensifier = 1.5
            token_info["role"] = "Intensifier (1.5x Multiplier)"
        elif (word in lexicon["positive"]) or (root in lexicon["positive"]):
            base = 1.0
            effective = base * pending_intensifier
            if pending_negation:
                effective = -effective
                token_info["role"] = f"Positive (Inverted to -{abs(effective)})"
            else:
                token_info["role"] = f"Positive (+{effective})"
            token_info["base_score"] = 1
            token_info["final_score"] = round(effective, 2)
            net_lexical_score += effective
            pending_negation = False; pending_intensifier = 1.0
        elif (word in lexicon["negative"]) or (root in lexicon["negative"]):
            base = -1.0
            effective = base * pending_intensifier
            if pending_negation:
                effective = -effective
                token_info["role"] = f"Negative (Inverted to +{abs(effective)})"
            else:
                token_info["role"] = f"Negative ({effective})"
            token_info["base_score"] = -1
            token_info["final_score"] = round(effective, 2)
            net_lexical_score += effective
            pending_negation = False; pending_intensifier = 1.0
        else:
            token_info["base_score"] = 0; token_info["final_score"] = 0.0; token_info["role"] = "Neutral (0)"
        token_scores.append(token_info)

    has_sarcasm = bool(set(words) & sarcasm_markers)

    if has_sarcasm: polarity = "Negative"; explanation = f"RoBERTa: {roberta_score}. Slang sarcasm invalidator ('eme/charot') triggered."
    elif net_lexical_score > 0: polarity = "Positive"; explanation = f"RoBERTa: {roberta_score}. Lexical score (+{round(net_lexical_score, 2)}) confirmed Positive sentiment."
    elif net_lexical_score < 0: polarity = "Negative"; explanation = f"RoBERTa: {roberta_score}. Lexical score ({round(net_lexical_score, 2)}) confirmed Negative sentiment."
    else: polarity = roberta_polarity; explanation = f"RoBERTa Confidence: {roberta_score}. Neutral lexical baseline."

    return polarity, roberta_score, explanation, token_scores, round(net_lexical_score, 2), has_sarcasm

def run_absa_pipeline(raw_comment, lexicon=None):
    if lexicon is None: lexicon = get_active_lexicon()
    cleaned = preprocess_taglish_text(raw_comment)
    clauses = segment_compound_text(cleaned)
    breakdown, polarities = [], []

    for clause in clauses:
        aspect = detect_aspect(clause)
        polarity, score, explanation, token_scores, lexical_score, has_sarcasm = evaluate_clause(clause, lexicon)
        polarities.append(polarity)
        breakdown.append({
            "aspect": aspect, 
            "clause": clause, 
            "polarity": polarity, 
            "score": score, 
            "lexical_score": lexical_score, 
            "token_scores": token_scores, 
            "explanation": explanation,
            "has_sarcasm": has_sarcasm
        })

    pos_count = polarities.count("Positive")
    neg_count = polarities.count("Negative")
    overall = "Positive" if pos_count > neg_count else "Negative" if neg_count > pos_count else "Neutral"
    avg_confidence = round(sum(item["score"] for item in breakdown) / len(breakdown), 4) if breakdown else 0
    return cleaned, overall, avg_confidence, breakdown

# ==========================================
# HIGH-DPI MATPLOTLIB ENGINE (WITH CACHE)
# ==========================================
_chart_cache = {}
CHART_THEMES = {
    "dark":  {"empty": "#1e293b", "ring": "#0f1a30", "muted": "#64748b", "label": "#94a3b8", "center": "#f8fafc", "grid": "#334155", "tick_x": "#94a3b8", "tick_y": "#64748b"},
    "light": {"empty": "#e2e8f0", "ring": "#f8fafc", "muted": "#64748b", "label": "#475569", "center": "#0f172a", "grid": "#cbd5e1", "tick_x": "#475569", "tick_y": "#64748b"},
}
_CHART_MAX = 50

def cached_chart(kind, key, builder):
    k = (kind, key)
    if k not in _chart_cache:
        img = builder()
        if not img: return ""
        if len(_chart_cache) >= _CHART_MAX: _chart_cache.pop(next(iter(_chart_cache)))
        _chart_cache[k] = img
    return _chart_cache[k]

def build_pie_internal(pos, neg, neu, theme="dark"):
    try:
        T = CHART_THEMES.get(theme, CHART_THEMES["dark"])
        fig = Figure(figsize=(3.0, 3.0), dpi=200, facecolor='none')
        FigureCanvas(fig)
        ax = fig.add_subplot(111); ax.set_facecolor('none')

        total = pos + neg + neu
        if total == 0:
            ax.pie([1], colors=[T['empty']], wedgeprops={'edgecolor': T['ring'], 'linewidth': 2, 'width': 0.42})
            ax.text(0, 0, '0\nVOICES', ha='center', va='center', color=T['muted'], fontsize=8.5, fontweight='bold', linespacing=1.2)
        else:
            counts, colors, labels = [], [], []
            if pos > 0: counts.append(pos); colors.append('#10b981'); labels.append(f'{pos}')
            if neg > 0: counts.append(neg); colors.append('#f43f5e'); labels.append(f'{neg}')
            if neu > 0: counts.append(neu); colors.append('#f59e0b'); labels.append(f'{neu}')

            wedges, texts, autotexts = ax.pie(
                counts, labels=labels, colors=colors, autopct='%1.0f%%', pctdistance=0.72,
                labeldistance=1.14, startangle=135, textprops={'color': T['label'], 'fontsize': 8, 'weight': 'bold'},
                wedgeprops={'edgecolor': T['ring'], 'linewidth': 2.5, 'width': 0.42}
            )
            for at in autotexts: at.set_color('#ffffff'); at.set_fontsize(7.5); at.set_weight('bold')
            ax.text(0, 0, f'{total}\nVOICES', ha='center', va='center', color=T['center'], fontsize=9, fontweight='800', linespacing=1.2)

        ax.axis('equal'); fig.subplots_adjust(left=0.06, right=0.94, top=0.94, bottom=0.06)
        buf = io.BytesIO(); fig.savefig(buf, format='png', transparent=True, dpi=200); buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception: return ""

def build_bar_internal(aspects, theme="dark"):
    try:
        T = CHART_THEMES.get(theme, CHART_THEMES["dark"])
        fig = Figure(figsize=(3.4, 3.0), dpi=200, facecolor='none')
        FigureCanvas(fig)
        ax = fig.add_subplot(111); ax.set_facecolor('none')

        categories = ['Pedagogy', 'Demeanor', 'Facilities']
        pos_vals = [aspects.get('Instructional Delivery', {}).get('pos', 0), aspects.get('Faculty Demeanor', {}).get('pos', 0), aspects.get('Facilities', {}).get('pos', 0)]
        neg_vals = [aspects.get('Instructional Delivery', {}).get('neg', 0), aspects.get('Faculty Demeanor', {}).get('neg', 0), aspects.get('Facilities', {}).get('neg', 0)]

        x = [0, 1, 2]; width = 0.38
        ax.bar(x, pos_vals, width, label='Positive', color='#10b981', zorder=3)
        ax.bar(x, neg_vals, width, bottom=pos_vals, label='Negative', color='#f43f5e', zorder=3)

        ax.set_xticks(x); ax.set_xticklabels(categories, color=T['tick_x'], fontsize=8, fontweight='600')
        ax.tick_params(axis='y', colors=T['tick_y'], labelsize=7.5, length=0)
        ax.tick_params(axis='x', length=0)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.grid(axis='y', color=T['grid'], linestyle=':', linewidth=0.8, alpha=0.5, zorder=1)

        fig.subplots_adjust(left=0.15, right=0.95, top=0.92, bottom=0.14)
        buf = io.BytesIO(); fig.savefig(buf, format='png', transparent=True, dpi=200); buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception: return ""

def generate_matplotlib_pie(pos, neg, neu, theme="dark"): return cached_chart("pie", (pos, neg, neu, theme), lambda: build_pie_internal(pos, neg, neu, theme))
def generate_matplotlib_bar(aspect_counts, theme="dark"): return cached_chart("bar", tuple(sorted((k, v["pos"], v["neg"]) for k, v in aspect_counts.items())) + (theme,), lambda: build_bar_internal(aspect_counts, theme))

def compute_prescriptive_insights(records):
    if not records: return [{"level": "Community Baseline", "aspect": "Academic Community Pulse", "ratio": 0, "recommendation": "Community listening portal active."}]
    aspect_stats = {
        "Instructional Delivery & Pedagogy": {"pos": 0, "neg": 0, "neu": 0},
        "Faculty Demeanor & Approachability": {"pos": 0, "neg": 0, "neu": 0},
        "Campus Facilities & Infrastructure": {"pos": 0, "neg": 0, "neu": 0}
    }
    for r in records:
        try:
            for item in json.loads(r.aspect_breakdown):
                asp, pol = item.get("aspect"), str(item.get("polarity")).strip().capitalize()
                if asp in aspect_stats and pol in ["Positive", "Negative", "Neutral"]:
                    aspect_stats[asp]["pos" if pol == "Positive" else "neg" if pol == "Negative" else "neu"] += 1
        except Exception: continue

    insights = []
    for asp, stats in aspect_stats.items():
        total_mentions = stats["pos"] + stats["neg"] + stats["neu"]
        if total_mentions >= 3:
            neg_ratio = stats["neg"] / total_mentions
            if neg_ratio >= 0.40:
                if asp == "Campus Facilities & Infrastructure": insights.append({"level": "Community Action Alert", "aspect": asp, "ratio": round(neg_ratio * 100, 1), "recommendation": "Elevated student concerns regarding campus facilities. Student Council should submit an actionable report to General Services."})
                elif asp == "Instructional Delivery & Pedagogy": insights.append({"level": "Pedagogical Dialogue Request", "aspect": asp, "ratio": round(neg_ratio * 100, 1), "recommendation": "Pacing concerns noted by student body. Recommend consultative forum on syllabus pacing."})
                elif asp == "Faculty Demeanor & Approachability": insights.append({"level": "Student Welfare Advisory", "aspect": asp, "ratio": round(neg_ratio * 100, 1), "recommendation": "Approachability concerns recorded. Recommend active student-faculty rapport initiatives."})
    if not insights: insights.append({"level": "Community Baseline", "aspect": "Student Body Sentiment Index", "ratio": 0, "recommendation": "Student feedback is within positive academic bounds."})
    return insights

# ==========================================
# AUTHENTICATION & REGISTRATION
# ==========================================
def issue_otp(user):
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.verification_hash = hmac.new(app.config["SECRET_KEY"].encode(), code.encode(), hashlib.sha256).hexdigest()
    user.verification_expires = datetime.utcnow() + timedelta(minutes=10)
    user.verification_attempts = 0
    return code

def verify_hashed_otp(user, code):
    if not user.verification_hash or not user.verification_expires or user.verification_attempts >= 5 or datetime.utcnow() > user.verification_expires: return False
    user.verification_attempts += 1
    attempt_hash = hmac.new(app.config["SECRET_KEY"].encode(), code.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(user.verification_hash, attempt_hash)

@app.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        department = "DCI"
        selected_role = request.form.get('role', 'Student - Regular').strip()
        cleaned_programs = [p.strip() for p in request.form.getlist('program') if p.strip()]
        privacy_consent = request.form.get('privacy_consent', '')

        if not username or not email or not password:
            return render_template('auth.html', error="All fields are required.", mode="signup")
        if privacy_consent != 'yes':
            return render_template('auth.html', error="You must review and agree to the Data Privacy Consent Notice (RA 10173) before registering.", mode="signup")
        if len(username) > 150 or len(email) > 180 or len(selected_role) > 50 or len(password) > 128:
            return render_template('auth.html', error="One of the fields is too long.", mode="signup")
        if len(password) < 6:
            return render_template('auth.html', error="Password must be at least 6 characters long.", mode="signup")
        if not email.endswith('@ccc.edu.ph'):
            return render_template('auth.html', error="Registration is restricted to official @ccc.edu.ph institutional email addresses only.", mode="signup")
        if selected_role == "MISD":
            return render_template('auth.html', error="MISD Admin accounts must be securely provisioned by the server.", mode="signup")

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            if not existing_user.is_verified:
                session['pending_verification_email'] = existing_user.email
                existing_user.privacy_consent_at = datetime.utcnow()
                flash("An uncompleted registration exists. Enter your new verification code below.")
                code = issue_otp(existing_user)
                db.session.commit()
                _mail_pool.submit(send_verification_email, existing_user.email, code, existing_user.username)
                return render_template('auth.html', mode="verify", email=existing_user.email, dev_code=None)
            err = "Username taken." if existing_user.username == username else "Email already registered."
            return render_template('auth.html', error=err, mode="signup")

        assigned_program_str = ", ".join(cleaned_programs) if cleaned_programs else "General"
        new_user = User(
            username=username, email=email, department=department,
            program=assigned_program_str, role=selected_role,
            is_verified=False, privacy_consent_at=datetime.utcnow()
        )
        new_user.set_password(password)
        code = issue_otp(new_user)
        db.session.add(new_user)
        try: db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_template('auth.html', error="Username or email already registered.", mode="signup")

        _mail_pool.submit(send_verification_email, email, code, username)
        print(f"[DEVELOPER NOTICE] Secure OTP for {email}: {code}")

        session['pending_verification_email'] = email
        return render_template('auth.html', mode="verify", email=email, dev_code=None)

    return render_template('auth.html', mode="signup")

@app.route('/resend-code', methods=['POST'])
@limiter.limit("3 per hour")
def resend_code():
    email = request.form.get('email', '').strip().lower() or session.get('pending_verification_email')
    user = User.query.filter_by(email=email).first()

    if not user: return render_template('auth.html', error="No pending account found.", mode="signup")
    if user.is_verified: flash("Your account is already verified! Please sign in."); return redirect(url_for('login'))

    code = issue_otp(user)
    db.session.commit()
    _mail_pool.submit(send_verification_email, user.email, code, user.username)
    print(f"[DEVELOPER NOTICE] Resent Secure OTP for {user.email}: {code}")
    flash("A fresh verification code has been dispatched to your inbox.")
    return render_template('auth.html', mode="verify", email=user.email, dev_code=None)

@app.route('/verify-code', methods=['POST'])
@limiter.limit("10 per 10 minutes")
def verify_code():
    email = request.form.get('email', '').strip().lower() or session.get('pending_verification_email')
    code = request.form.get('code', '').strip()

    user = User.query.filter_by(email=email).first()
    if not user: return render_template('auth.html', error="User record not found.", mode="verify", email=email)

    if verify_hashed_otp(user, code):
        user.is_verified = True; user.verification_hash = None
        db.session.commit(); session.pop('pending_verification_email', None)
        flash("Email confirmed successfully! You may now sign in.")
        return redirect(url_for('login'))
    else:
        db.session.commit()
        return render_template('auth.html', error="Invalid or expired code.", mode="verify", email=email)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 10

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute", exempt_when=_session_active)
def login():
    if current_user.is_authenticated: return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))

    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        password_input = request.form.get('password', '')
        user = User.query.filter((User.username == login_id) | (User.email == login_id.lower())).first()

        if user:
            now = datetime.utcnow()
            if user.locked_until and now < user.locked_until:
                wait_mins = max(1, math.ceil((user.locked_until - now).total_seconds() / 60))
                return render_template(
                    'auth.html',
                    error=f"Account temporarily locked after {MAX_LOGIN_ATTEMPTS} failed attempts. Try again in {wait_mins} minute(s) or use 'Forgot password?'.",
                    mode="login"
                )

            if user.check_password(password_input):
                user.failed_login_attempts = 0
                user.locked_until = None

                if not user.is_verified:
                    session['pending_verification_email'] = user.email
                    flash("Account unverified. Confirm your 6-digit email code.")
                    code = issue_otp(user); db.session.commit()
                    _mail_pool.submit(send_verification_email, user.email, code, user.username)
                    print(f"[DEVELOPER NOTICE] Secure OTP for {user.email}: {code}")
                    return render_template('auth.html', mode="verify", email=user.email, dev_code=None)

                db.session.commit()
                pending_share = session.get('pending_share')   # a shared survey link opened while signed out
                session.clear(); session.permanent = True; login_user(user, remember=True)

                try:
                    db.session.add(UserLoginLog(user_id=user.id, username=user.username, role=user.role, department=user.department, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent', '')[:250]))
                    db.session.commit()
                except Exception as e:
                    db.session.rollback(); app.logger.warning(f"Failed to log login: {e}")

                if pending_share and SHARE_TOKEN_RE.match(str(pending_share)):
                    return redirect(url_for('open_shared_form', token=pending_share))
                return redirect(url_for('student_portal') if user.role.startswith("Student") else url_for('dashboard'))
            else:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                    user.failed_login_attempts = 0
                    db.session.commit()
                    return render_template(
                        'auth.html',
                        error=f"Too many failed login attempts. This account is locked for {LOCKOUT_MINUTES} minutes. You may also reset your password via email.",
                        mode="login"
                    )
                remaining = MAX_LOGIN_ATTEMPTS - user.failed_login_attempts
                db.session.commit()
                return render_template(
                    'auth.html',
                    error=f"Invalid credentials provided. ({remaining} attempt{'s' if remaining != 1 else ''} remaining before a {LOCKOUT_MINUTES}-minute lockout.)",
                    mode="login"
                )

        return render_template('auth.html', error="Invalid credentials provided.", mode="login")
    return render_template('auth.html', mode="login")

@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        if not identifier:
            return render_template('auth.html', error="Please enter your institutional email or username.", mode="forgot")

        user = User.query.filter((User.username == identifier) | (User.email == identifier.lower())).first()
        if not user:
            return render_template('auth.html', error="No account matched that username or email address.", mode="forgot")

        code = issue_otp(user)
        db.session.commit()
        session['pending_reset_email'] = user.email
        _mail_pool.submit(send_verification_email, user.email, code, user.username, "reset")
        print(f"[DEVELOPER NOTICE] Password Reset OTP for {user.email}: {code}")
        flash("A 6-digit password reset code has been sent to your institutional email.")
        return render_template('auth.html', mode="reset_verify", email=user.email)

    return render_template('auth.html', mode="forgot")

@app.route('/reset-password', methods=['POST'])
@limiter.limit("10 per 10 minutes")
def reset_password():
    email = request.form.get('email', '').strip().lower() or session.get('pending_reset_email')
    code = request.form.get('code', '').strip()
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not email:
        return render_template('auth.html', error="Reset session expired. Please request a new code.", mode="forgot")

    user = User.query.filter_by(email=email).first()
    if not user:
        return render_template('auth.html', error="Account not found.", mode="forgot")

    if len(new_password) < 6 or len(new_password) > 128:
        return render_template('auth.html', error="New password must be between 6 and 128 characters.", mode="reset_verify", email=email)
    if new_password != confirm_password:
        return render_template('auth.html', error="Passwords do not match.", mode="reset_verify", email=email)

    if verify_hashed_otp(user, code):
        user.set_password(new_password)
        user.verification_hash = None
        user.is_verified = True
        user.failed_login_attempts = 0
        user.locked_until = None
        db.session.commit()
        session.pop('pending_reset_email', None)
        flash("Password updated and account unlocked! You may now sign in.")
        return redirect(url_for('login'))
    else:
        db.session.commit()
        return render_template('auth.html', error="Invalid or expired 6-digit reset code.", mode="reset_verify", email=email)

GUEST_ONLY_ENDPOINTS = {"signup", "resend_code", "verify_code", "forgot_password", "reset_password"}

@app.before_request
def keep_signed_in_users_inside():
    if request.endpoint in GUEST_ONLY_ENDPOINTS and current_user.is_authenticated:
        return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))

_AUTH_PAGE_BOUNCE = (b"<script>(function(){var go=function(){fetch('/api/session_ping',{cache:'no-store',credentials:'same-origin',redirect:'manual'})"
    b".then(function(r){if(r.status===204)location.replace('/');}).catch(function(){});};"
    b"window.addEventListener('pageshow',function(e){var n=performance.getEntriesByType&&performance.getEntriesByType('navigation')[0];"
    b"if(e.persisted||(n&&n.type==='back_forward'))go();});})();</script>")

@app.after_request
def bounce_signed_in_users_from_auth_pages(response):
    """If the browser restores an old sign-in / sign-up page from its back-forward cache while the session is still alive,
    send the person straight back to their portal instead of leaving them on a form with no Sign Out button."""
    try:
        if request.endpoint in ("login", "signup") and response.mimetype == "text/html" and not response.direct_passthrough:
            body = response.get_data()
            i = body.rfind(b"</body>")
            if i != -1: response.set_data(body[:i] + _AUTH_PAGE_BOUNCE + body[i:])
    except Exception:
        app.logger.warning("Could not attach the signed-in bounce script.", exc_info=True)
    return response

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    resp = redirect(url_for('login'))
    # Aggressively wipe the browser's Back-Forward Cache (BFCache)
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "-1"
    return resp

@app.route('/s/<token>')
def open_shared_form(token):
    """Shareable survey link (like a Google Forms link). Sign-in is still required so each student can answer only once."""
    if not SHARE_TOKEN_RE.match(token or ""): return redirect(url_for('index'))
    if not current_user.is_authenticated:
        session['pending_share'] = token
        flash("Please sign in to open the survey you were sent.")
        return redirect(url_for('login'))
    if not current_user.role.startswith("Student"): return redirect(url_for('dashboard'))
    form = EvaluationForm.query.filter_by(share_token=token, is_active=True).first()
    return redirect(url_for('student_portal', survey=(form.id if form else 'unavailable')))

@app.route('/api/tutorial/seen', methods=['POST'])
@login_required
@api_guard
def mark_tour_seen():
    """Remembered on the account (not the browser), because signing out clears browser storage."""
    if not current_user.tour_seen:
        current_user.tour_seen = True
        db.session.commit()
    return jsonify({"success": True})

@app.route('/healthz')
@limiter.exempt
def healthz():
    """Plain 'the server is up' check for uptime monitors and Docker. It does not touch the database or the model."""
    return Response("ok", mimetype="text/plain")

@app.route('/api/session_ping', methods=['GET'])
@login_required
def session_ping(): return ("", 204)

# =========================================================
# COMMUNITY TOWN HALL APIS
# =========================================================
@app.route('/student-portal')
@login_required
def student_portal():
    available_years = [y.year for y in AcademicYear.query.order_by(AcademicYear.year.desc()).all()]
    return render_template('student_portal.html', username=current_user.username, role=current_user.role, department=current_user.department, program=current_user.program or "General", available_years=available_years, tour_seen=bool(current_user.tour_seen))

@app.route('/api/community_pulse', methods=['GET'])
@login_required
@api_guard
def get_community_pulse():
    q = Feedback.query.filter_by(department='DCI')
    by_sent = dict(q.with_entities(func.lower(Feedback.sentiment), func.count()).group_by(func.lower(Feedback.sentiment)).all())
    
    pos = by_sent.get('positive', 0); neg = by_sent.get('negative', 0); neu = by_sent.get('neutral', 0)
    total_voices = pos + neg + neu
    pos_pct = round((pos / total_voices) * 100, 1) if total_voices > 0 else 0
    neg_pct = round((neg / total_voices) * 100, 1) if total_voices > 0 else 0
    neu_pct = round((neu / total_voices) * 100, 1) if total_voices > 0 else 0

    return jsonify({"total_voices": total_voices, "positive_count": pos, "negative_count": neg, "neutral_count": neu, "positive_percent": pos_pct, "negative_percent": neg_pct, "neutral_percent": neu_pct, "active_initiatives": EvaluationForm.query.filter_by(is_active=True).count(), "department": "DCI"})

@app.route('/api/community_feed', methods=['GET'])
@login_required
@api_guard
def get_community_feed():
    channel = request.args.get('channel', 'ALL').strip().upper()
    posts_query = CommunityPost.query
    if channel == 'ANNOUNCEMENTS': posts_query = posts_query.filter((CommunityPost.target_channel == 'ANNOUNCEMENTS') | (CommunityPost.is_announcement == True))
    elif channel != 'ALL': posts_query = posts_query.filter(CommunityPost.target_channel == channel)

    posts = posts_query.order_by(CommunityPost.is_announcement.desc(), CommunityPost.score.desc(), CommunityPost.id.desc()).limit(50).all()
    if not posts: return jsonify([])

    post_ids = [p.id for p in posts]
    user_votes = {v.post_id: v.vote_type for v in CommunityPostVote.query.filter_by(user_id=current_user.id).filter(CommunityPostVote.post_id.in_(post_ids)).all()}
    user_res_votes = {rv.post_id: rv.reaction_type for rv in CommunityResolutionVote.query.filter_by(user_id=current_user.id).filter(CommunityResolutionVote.post_id.in_(post_ids)).all()}
    comment_counts = dict(db.session.query(CommunityComment.post_id, func.count()).filter(CommunityComment.post_id.in_(post_ids)).group_by(CommunityComment.post_id).all())
    
    res_counts = {}
    for pid, rtype, n in db.session.query(CommunityResolutionVote.post_id, CommunityResolutionVote.reaction_type, func.count()).filter(CommunityResolutionVote.post_id.in_(post_ids)).group_by(CommunityResolutionVote.post_id, CommunityResolutionVote.reaction_type).all():
        res_counts[(pid, rtype)] = n

    out = []
    for p in posts:
        try: aspects = json.loads(p.aspect_breakdown)
        except Exception: aspects = []

        out.append({
            "id": p.id, "target_channel": p.target_channel or "ALL", "author_department": p.author_department or "DCI",
            "author_role": p.author_role or "Student - Regular", "author_name": p.author_name if p.is_announcement else None,
            "is_announcement": bool(p.is_announcement), "program": p.program or "General", "category": p.category or "Campus Facilities & Infrastructure",
            "content": safe_out(p.content or ""), "image_url": p.image_url, "link_url": p.link_url, "is_edited": bool(p.is_edited),
            "can_edit": bool(p.author_id == current_user.id or current_user.role == 'MISD'), "sentiment": p.sentiment or "Neutral", "confidence": p.confidence or 0.0,
            "aspects": aspects, "score": p.score or 0, "user_vote": user_votes.get(p.id, 0), "comment_count": comment_counts.get(p.id, 0),
            "status": p.status or "Open", "action_note": p.action_note, "action_by": p.action_by,
            "resolution_upvotes": res_counts.get((p.id, 1), 0), "resolution_downvotes": res_counts.get((p.id, -1), 0),
            "user_resolution_vote": user_res_votes.get(p.id, 0), "created_at": p.created_at.strftime("%b %d, %Y • %I:%M %p") if p.created_at else ""
        })
    return jsonify(out)

DATA_IMG_RE = re.compile(r'^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=]+$')
def clean_url(value, allow_data_image=False):
    value = (value or "").strip()
    if not value: return None
    if allow_data_image and value.startswith("data:"):
        if len(value) > 7_000_000 or not DATA_IMG_RE.fullmatch(value): raise ClientError("Invalid image data.")
        return value
    p = urlparse(value)
    if len(value) > 2048 or p.scheme not in ("http", "https") or not p.netloc: raise ClientError("Only valid http(s) links are allowed.")
    return value

@app.route('/api/community_post', methods=['POST'])
@login_required
@api_guard
def create_community_post():
    data = json_body()
    content = scrub_pii(sfield(data, "content", max_len=5000))
    category = sfield(data, "category", "Campus Facilities & Infrastructure", max_len=100)
    target_channel = sfield(data, "target_channel", "ALL", max_len=50).upper()
    is_announcement = bool(data.get("is_announcement", False))
    if not content or len(content) < 4: return jsonify({"error": "Post must be at least 4 characters long."}), 400

    is_authorized = any(k in (current_user.role or "").lower() for k in ['officer', 'representative', 'rep', 'faculty', 'misd'])
    if is_announcement or target_channel == 'ANNOUNCEMENTS':
        if not is_authorized: return jsonify({"error": "Permission Denied: Only Officers, Reps, and Faculty can broadcast."}), 403
        is_announcement = True

    expiry_tag = clean_expiry_tag(data.get("action_note")) if is_announcement else None

    if is_announcement:
        cleaned, sentiment, score, breakdown = content, "Neutral", 0.0, []
    else:
        cleaned, sentiment, score, breakdown = run_absa_pipeline(content, get_active_lexicon())

    had_profanity = has_profanity(content)   # the AI has already read the original; from here on only the masked version is kept
    content, cleaned, breakdown = mask_profanity(content), mask_profanity(cleaned), mask_any(breakdown)

    post = CommunityPost(
        author_id=current_user.id, author_name=current_user.username if is_announcement else None,
        target_channel=target_channel, author_department="DCI",
        author_role=current_user.role, is_announcement=is_announcement,
        program=(current_user.program or "General")[:150], category=category, content=content,
        image_url=clean_url(data.get("image_url"), allow_data_image=True), link_url=clean_url(data.get("link_url")), sentiment=sentiment,
        confidence=score, aspect_breakdown=json.dumps(breakdown), score=1, status="Open",
        action_note=expiry_tag
    )
    db.session.add(post); db.session.flush()
    db.session.add(CommunityPostVote(post_id=post.id, user_id=current_user.id, vote_type=1))

    if not is_announcement:
        active_yr, active_sem = get_active_term()
        db.session.add(Feedback(
            form_id=None, department="DCI",
            program=(current_user.program or "General")[:150], academic_year=active_yr, semester=active_sem,
            raw_text=content, cleaned_text=cleaned, sentiment=sentiment, ai_sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(breakdown), source="Portal", has_profanity=had_profanity
        ))
    db.session.commit()
    return jsonify({"success": True, "message": "Voice or announcement posted successfully.", "masked": had_profanity})

@app.route('/api/community_post/<int:post_id>/edit', methods=['POST'])
@login_required
@api_guard
def edit_community_post(post_id):
    post = CommunityPost.query.get(post_id)
    if not post: return jsonify({"error": "Post not found."}), 404
    if post.author_id != current_user.id and current_user.role != 'MISD': return jsonify({"error": "Unauthorized to edit this post."}), 403

    data = json_body()
    new_content = scrub_pii(sfield(data, "content", max_len=5000))
    if not new_content or len(new_content) < 4: return jsonify({"error": "Content must be at least 4 characters long."}), 400

    if post.is_announcement:
        cleaned, sentiment, score, breakdown = new_content, "Neutral", 0.0, []
    else:
        cleaned, sentiment, score, breakdown = run_absa_pipeline(new_content, get_active_lexicon())

    had_profanity = has_profanity(new_content)
    new_content, cleaned, breakdown = mask_profanity(new_content), mask_profanity(cleaned), mask_any(breakdown)
    post.content = new_content; post.category = sfield(data, "category", post.category, max_len=100) or post.category
    post.image_url = clean_url(data.get("image_url"), allow_data_image=True); post.link_url = clean_url(data.get("link_url"))
    if post.is_announcement and "action_note" in data:
        new_tag = clean_expiry_tag(data.get("action_note")) or ""
        old_note = post.action_note or ""
        suffix = (old_note.split("|", 1)[1] if "|" in old_note else "") if old_note.startswith("EXP:") else old_note
        post.action_note = (new_tag + suffix) or None
    post.sentiment = sentiment; post.confidence = score; post.aspect_breakdown = json.dumps(breakdown)
    post.is_edited = True; post.edited_at = datetime.utcnow()

    db.session.commit()
    return jsonify({"success": True, "message": "Post updated successfully.", "masked": had_profanity})

@app.route('/api/community_post/vote', methods=['POST'])
@login_required
@api_guard
def vote_post():
    data = json_body()
    post_id = ifield(data, "post_id")
    direction = ifield(data, "direction", 1)
    if direction not in [1, -1]: return jsonify({"error": "Invalid vote."}), 400

    post = CommunityPost.query.filter_by(id=post_id).with_for_update().first()
    if not post: return jsonify({"error": "Post not found."}), 404

    vote = CommunityPostVote.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if vote and vote.vote_type == direction: db.session.delete(vote); user_state = 0
    elif vote: vote.vote_type = direction; user_state = direction
    else: db.session.add(CommunityPostVote(post_id=post.id, user_id=current_user.id, vote_type=direction)); user_state = direction
    db.session.flush()

    post.score = db.session.query(func.coalesce(func.sum(CommunityPostVote.vote_type), 0)).filter_by(post_id=post.id).scalar()
    db.session.commit()
    return jsonify({"success": True, "score": post.score, "user_vote": user_state})

@app.route('/api/community_post/resolution_vote', methods=['POST'])
@login_required
@api_guard
def vote_resolution():
    data = json_body()
    post_id = ifield(data, "post_id")
    direction = ifield(data, "direction", 1)
    if direction not in [1, -1]: return jsonify({"error": "Invalid reaction."}), 400

    post = CommunityPost.query.filter_by(id=post_id).with_for_update().first()
    if not post or not post.action_note: return jsonify({"error": "No administrative action note available."}), 404

    vote = CommunityResolutionVote.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if vote and vote.reaction_type == direction: db.session.delete(vote); user_state = 0
    elif vote: vote.reaction_type = direction; user_state = direction
    else: db.session.add(CommunityResolutionVote(post_id=post.id, user_id=current_user.id, reaction_type=direction)); user_state = direction
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/community_post/<int:post_id>/comments', methods=['GET', 'POST'])
@login_required
@api_guard
def handle_post_comments(post_id):
    post = CommunityPost.query.get(post_id)
    if not post: return jsonify({"error": "Post not found."}), 404

    if request.method == 'POST':
        content = mask_profanity(scrub_pii(sfield(json_body(), "content", max_len=2000)))
        if not content or len(content) < 2: return jsonify({"error": "Comment too short."}), 400
        db.session.add(CommunityComment(post_id=post.id, author_department="DCI", author_role=current_user.role, content=content))
        db.session.commit()
        return jsonify({"success": True})

    comments = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).all()
    return jsonify([{"id": c.id, "author_department": c.author_department, "content": safe_out(c.content), "created_at": c.created_at.strftime("%b %d, %Y • %I:%M %p")} for c in comments])

POST_STATUSES = {"Open", "Under Review", "Action Taken"}

@app.route('/api/community_post/status', methods=['POST'])
@login_required
@api_guard
def update_post_status():
    if not any(k in (current_user.role or "").lower() for k in ['officer', 'faculty', 'misd']): return jsonify({"error": "Unauthorized."}), 403

    data = json_body()
    post = CommunityPost.query.get(ifield(data, "post_id"))
    if not post: return jsonify({"error": "Post not found."}), 404

    status = sfield(data, "status", "Under Review", max_len=50)
    if status not in POST_STATUSES: return jsonify({"error": "Invalid status."}), 400

    post.status = status; post.action_note = sfield(data, "action_note", max_len=2000); post.action_by = f"{current_user.username} ({current_user.role})"
    db.session.commit()
    return jsonify({"success": True})

# =========================================================
# EVALUATION FORMS, TARGETING, QUOTAS & AUTHOR ANALYTICS
# =========================================================
@app.route('/api/forms', methods=['GET'])
@login_required
@api_guard
def get_forms_api():
    query = EvaluationForm.query.filter_by(is_active=True, department="DCI")

    forms = query.order_by(EvaluationForm.id.desc()).all()
    form_ids = [f.id for f in forms]
    with_header = _forms_with_header(form_ids)
    counts = dict(db.session.query(FormAnonymousSubmission.form_id, func.count()).filter(FormAnonymousSubmission.form_id.in_(form_ids)).group_by(FormAnonymousSubmission.form_id).all())
    submitted = set(r.form_id for r in FormResponseRecord.query.filter_by(student_id=current_user.id).all())

    out = []
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")

    for f in forms:
        try: q_list = json.loads(f.questions_json)
        except Exception: q_list = []

        total = counts.get(f.id, 0)
        is_expired = f.deadline_date and f.deadline_date not in ["No Expiry", "None", ""] and (f.deadline_date < now_iso if "T" in f.deadline_date else f.deadline_date < now_iso[:10])
        is_quota_full = bool(f.max_responses and f.max_responses > 0 and total >= f.max_responses)

        out.append({
            "id": f.id, "title": f.title, "description": f.description, "form_category": f.form_category,
            "department": f.department, "program": f.program, "subject_code": f.subject_code or "N/A",
            "section_target": f.section_target or "ALL", "deadline_date": f.deadline_date or "No Expiry",
            "max_responses": f.max_responses or 0, "total_submissions": total,
            "is_closed": is_expired or is_quota_full,
            "close_reason": "Deadline Passed" if is_expired else ("Quota Reached" if is_quota_full else None),
            "academic_year": f.academic_year, "semester": f.semester,
            "created_by_name": f.created_by_name, "created_by_role": f.created_by_role,
            "questions": q_list, "already_submitted": (f.id in submitted),
            "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else "",
            "theme": _theme_of(f), "has_header_image": f.id in with_header
        })
    return jsonify(out)

@app.route('/api/forms/create', methods=['POST'])
@login_required
@api_guard
def create_form_api():
    if not any(k in (current_user.role or "").lower() for k in ['officer', 'representative', 'rep', 'faculty', 'misd']): return jsonify({"error": "Unauthorized."}), 403

    data = json_body()
    title = sfield(data, "title", max_len=250)
    questions = data.get("questions", [])
    if not title or not questions: return jsonify({"error": "Title and questions required."}), 400
    if not isinstance(questions, list) or len(questions) > 100 or not all(isinstance(q, dict) for q in questions): return jsonify({"error": "Questions must be a list of up to 100 question objects."}), 400

    deadline_date = sfield(data, "deadline_date", max_len=50) or None
    if deadline_date and deadline_date not in ["No Expiry", "None", ""]:
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")
        is_past = (deadline_date < now_iso) if "T" in deadline_date else (deadline_date < now_iso[:10])
        if is_past: return jsonify({"error": "Due date must be present or future."}), 400

    new_form = EvaluationForm(
        title=title, description=sfield(data, "description", max_len=5000),
        form_category=sfield(data, "form_category", "Community Initiative", max_len=100) or "Community Initiative",
        department="DCI",
        program=sfield(data, "program", (current_user.program or "ALL")[:150], max_len=150) or "ALL",
        subject_code=sfield(data, "subject_code", max_len=50) or None,
        section_target=sfield(data, "section_target", "ALL", max_len=50) or "ALL",
        deadline_date=deadline_date,
        max_responses=max(0, min(ifield(data, "max_responses", 0), 100000)),
        academic_year=sfield(data, "academic_year", "2026-2027", max_len=20) or "2026-2027",
        semester=sfield(data, "semester", "1st Semester", max_len=30) or "1st Semester",
        created_by_id=current_user.id, created_by_name=current_user.username,
        created_by_role=current_user.role, questions_json=json.dumps(questions)
    )
    theme = clean_theme(data.get("theme"))
    header_image = clean_header_image(data.get("header_image"))
    theme["hv"] = int(time.time()) if header_image else 0
    new_form.theme_json = json.dumps(theme)
    new_form.header_image = header_image
    db.session.add(new_form); db.session.commit()
    return jsonify({"success": True, "form_id": new_form.id})

@app.route('/api/forms/submit', methods=['POST'])
@login_required
@api_guard
def submit_form_api():
    data = json_body()
    form = EvaluationForm.query.filter_by(id=ifield(data, "form_id")).with_for_update().first()
    if not form or not form.is_active: return jsonify({"error": "Form closed."}), 404

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")
    if form.deadline_date and form.deadline_date not in ["No Expiry", "None", ""]:
        if (form.deadline_date < now_iso if "T" in form.deadline_date else form.deadline_date < now_iso[:10]): return jsonify({"error": "Deadline passed."}), 400

    total = FormAnonymousSubmission.query.filter_by(form_id=form.id).count()
    if (form.max_responses or 0) > 0 and total >= form.max_responses: return jsonify({"error": "Quota reached."}), 400
    if FormResponseRecord.query.filter_by(form_id=form.id, student_id=current_user.id).first(): return jsonify({"error": "Already submitted."}), 400

    answers = data.get("answers", [])
    if not isinstance(answers, list) or len(answers) > 200 or not all(isinstance(a, dict) for a in answers): return jsonify({"error": "Answers must be a list of up to 200 answer objects."}), 400

    answers = scrub_answers(answers)
    lexicon = get_active_lexicon()
    for ans in answers:
        comment_text = text_of(ans.get("narrative_text")) or text_of(ans.get("answer"))
        if not comment_text and ans.get("type") in ["narrative", "text"]: comment_text = text_of(ans.get("value"))
        comment_text = comment_text[:5000]
        if not comment_text or len(comment_text) < 3: continue

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment_text, lexicon)
        had_profanity = has_profanity(comment_text)
        db.session.add(Feedback(
            form_id=form.id, department="DCI",
            program=form.program if form.program != "ALL" else (current_user.program or "General")[:150],
            academic_year=form.academic_year, semester=form.semester, raw_text=mask_profanity(comment_text),
            cleaned_text=mask_profanity(cleaned), sentiment=sentiment, ai_sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(mask_any(breakdown)), source="Portal", has_profanity=had_profanity,
            timestamp=datetime.utcnow().replace(minute=0, second=0, microsecond=0)   # rounded to the hour so it cannot be matched to the exact moment a student submitted
        ))

    db.session.add(FormAnonymousSubmission(form_id=form.id, answers_json=json.dumps(mask_any(answers))))
    db.session.add(FormResponseRecord(form_id=form.id, student_id=current_user.id, submitted_at=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)))   # day only, for the same reason
    db.session.commit()
    return jsonify({"success": True})

SHARE_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{6,32}$')

# ---- survey look & feel (Google-Forms-style customisation) ----
THEME_FONTS = {"sans", "serif", "rounded"}
THEME_HEADERS = {"none", "ocean", "sunset", "forest", "violet", "slate", "rose"}
_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}\Z')
_HEADER_IMG_RE = re.compile(r'^data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}\Z')
MAX_HEADER_CHARS = 450_000   # about 330 KB of picture once base64-encoded

def clean_theme(raw):
    """Only known keys and strictly validated values are ever stored, because they are written into styles on other people's screens."""
    raw = raw if isinstance(raw, dict) else {}
    def colour(v): return v.lower() if isinstance(v, str) and _HEX_RE.match(v) else None
    font = raw.get("font"); header = raw.get("header")
    return {"accent": colour(raw.get("accent")), "background": colour(raw.get("background")),
            "font": font if font in THEME_FONTS else "sans", "header": header if header in THEME_HEADERS else "none"}

def clean_header_image(v):
    if v is None or v == "": return None
    if not isinstance(v, str) or len(v) > MAX_HEADER_CHARS or not _HEADER_IMG_RE.match(v):
        raise ClientError("The header image must be a PNG, JPEG or WebP picture of about 330 KB or less.")
    return v

def _theme_of(form):
    try: raw = json.loads(form.theme_json) if form.theme_json else {}
    except Exception: raw = {}
    theme = clean_theme(raw)
    hv = raw.get("hv") if isinstance(raw, dict) else 0
    theme["hv"] = int(hv) if isinstance(hv, (int, float)) and not isinstance(hv, bool) else 0
    return theme

def _forms_with_header(form_ids):
    if not form_ids: return set()
    rows = db.session.query(EvaluationForm.id).filter(EvaluationForm.id.in_(form_ids), EvaluationForm.header_image.isnot(None)).all()
    return {r[0] for r in rows}

def _norm_deadline(d):
    return None if d in (None, "", "No Expiry", "None") else d

def _deadline_passed(d):
    d = _norm_deadline(d)
    if not d: return False
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return d < now_iso if "T" in d else d < now_iso[:10]

def _form_share_token(form):
    """Every survey gets an unguessable share token the first time it is needed (also back-fills surveys made before this feature)."""
    if not form.share_token:
        for _ in range(5):
            tok = secrets.token_urlsafe(9)
            if not EvaluationForm.query.filter_by(share_token=tok).first():
                form.share_token = tok
                break
        db.session.commit()
    return form.share_token

def _manageable_form(form_id):
    """Creator (or MISD) only. Removed surveys behave as if they no longer exist."""
    form = db.session.get(EvaluationForm, form_id)
    if not form or not form.is_active: return None, (jsonify({"error": "That survey no longer exists."}), 404)
    if form.created_by_id != current_user.id and current_user.role != 'MISD':
        return None, (jsonify({"error": "Only the person who created this survey can do that."}), 403)
    return form, None

def _clean_questions(questions):
    if not isinstance(questions, list) or not questions or len(questions) > 100 or not all(isinstance(q, dict) for q in questions):
        raise ClientError("Questions must be a list of 1 to 100 question objects.")
    return questions

@app.route('/api/forms/my_forms', methods=['GET'])
@login_required
@api_guard
def my_forms_api():
    forms = EvaluationForm.query.filter_by(created_by_id=current_user.id, is_active=True).order_by(EvaluationForm.id.desc()).all()
    counts = {}
    if forms:
        counts = dict(db.session.query(FormAnonymousSubmission.form_id, func.count()).filter(FormAnonymousSubmission.form_id.in_([f.id for f in forms])).group_by(FormAnonymousSubmission.form_id).all())
    with_header = _forms_with_header([f.id for f in forms])
    out = []
    for f in forms:
        n = counts.get(f.id, 0)
        expired = _deadline_passed(f.deadline_date)
        full = bool(f.max_responses and f.max_responses > 0 and n >= f.max_responses)
        out.append({
            "id": f.id, "title": f.title, "description": f.description or "", "form_category": f.form_category,
            "subject_code": f.subject_code or "N/A", "section_target": f.section_target or "ALL",
            "academic_year": f.academic_year, "semester": f.semester, "response_count": n,
            "max_responses": f.max_responses or 0, "deadline_date": f.deadline_date, "is_active": f.is_active,
            "is_closed": expired or full, "close_reason": "Deadline Passed" if expired else ("Quota Reached" if full else None),
            "share_url": "/s/" + _form_share_token(f), "questions_locked": n > 0,
            "theme": _theme_of(f), "has_header_image": f.id in with_header,
            "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else ""
        })
    return jsonify(out)

@app.route('/api/forms/<int:form_id>/header', methods=['GET'])
@login_required
def form_header_image(form_id):
    form = db.session.get(EvaluationForm, form_id)
    img = form.header_image if form and form.is_active else None
    if not img: return Response(status=404)
    try:
        head, b64 = img.split(",", 1)
        mime = head[5:head.index(";")]
        raw = base64.b64decode(b64)
    except Exception:
        return Response(status=404)
    resp = Response(raw, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=86400"   # the ?v=<version> in the URL changes whenever the picture does
    return resp

@app.route('/api/forms/<int:form_id>/manage', methods=['GET'])
@login_required
@api_guard
def get_form_for_edit(form_id):
    form, err = _manageable_form(form_id)
    if err: return err
    n = FormAnonymousSubmission.query.filter_by(form_id=form.id).count()
    try: q_list = json.loads(form.questions_json)
    except Exception: q_list = []
    return jsonify({
        "id": form.id, "title": form.title, "description": form.description or "", "form_category": form.form_category,
        "subject_code": form.subject_code or "", "section_target": form.section_target or "ALL",
        "deadline_date": _norm_deadline(form.deadline_date) or "", "max_responses": form.max_responses or 0,
        "academic_year": form.academic_year, "semester": form.semester, "questions": q_list,
        "response_count": n, "questions_locked": n > 0,
        "theme": _theme_of(form), "has_header_image": bool(form.id in _forms_with_header([form.id]))
    })

@app.route('/api/forms/<int:form_id>/update', methods=['POST'])
@login_required
@api_guard
def update_form_api(form_id):
    form, err = _manageable_form(form_id)
    if err: return err
    data = json_body()
    title = sfield(data, "title", max_len=250)
    if not title: return jsonify({"error": "A survey needs a title."}), 400

    new_deadline = _norm_deadline(sfield(data, "deadline_date", max_len=50) or None)
    if new_deadline and new_deadline != _norm_deadline(form.deadline_date) and _deadline_passed(new_deadline):
        return jsonify({"error": "Due date must be present or future."}), 400

    total = FormAnonymousSubmission.query.filter_by(form_id=form.id).count()
    if data.get("questions") is not None:
        questions = _clean_questions(data.get("questions"))
        try: current_questions = json.loads(form.questions_json)
        except Exception: current_questions = None
        if questions != current_questions:
            if total > 0:
                return jsonify({"error": "The questions are locked because people have already responded. You can still change the title, description, deadline and response limit."}), 409
            form.questions_json = json.dumps(questions)

    form.title = title
    form.description = sfield(data, "description", max_len=5000)
    form.form_category = sfield(data, "form_category", form.form_category, max_len=100) or form.form_category
    form.subject_code = sfield(data, "subject_code", max_len=50) or None
    form.section_target = sfield(data, "section_target", "ALL", max_len=50) or "ALL"
    form.deadline_date = new_deadline
    form.max_responses = max(0, min(ifield(data, "max_responses", 0), 100000))
    form.academic_year = sfield(data, "academic_year", form.academic_year, max_len=20) or form.academic_year
    form.semester = sfield(data, "semester", form.semester, max_len=30) or form.semester

    theme = clean_theme(data.get("theme")) if "theme" in data else _theme_of(form)
    theme["hv"] = _theme_of(form).get("hv", 0)
    if "header_image" in data:                      # absent = keep, "" = remove, data URL = replace
        header_image = clean_header_image(data.get("header_image"))
        form.header_image = header_image
        theme["hv"] = int(time.time()) if header_image else 0
    form.theme_json = json.dumps(theme)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/forms/<int:form_id>/delete', methods=['POST'])
@login_required
@api_guard
def delete_form_api(form_id):
    form, err = _manageable_form(form_id)
    if err: return err
    body = request.get_json(silent=True) or {}
    purge = body.get("purge") is True
    if purge:
        # The creator chose to erase everything collected through this survey.
        Feedback.query.filter_by(form_id=form.id).delete(synchronize_session=False)
        FormAnonymousSubmission.query.filter_by(form_id=form.id).delete(synchronize_session=False)
        FormResponseRecord.query.filter_by(form_id=form.id).delete(synchronize_session=False)
        db.session.delete(form)
    else:
        form.is_active = False   # hidden from everyone; the sentiment data already collected stays in the analytics
    db.session.commit()
    return jsonify({"success": True, "purged": purge})

@app.route('/api/forms/<int:form_id>/analytics', methods=['GET'])
@login_required
@api_guard
def get_form_analytics(form_id):
    form, err = _manageable_form(form_id)          # creator or MISD only; removed surveys count as gone
    if err: return err

    subs = FormAnonymousSubmission.query.filter_by(form_id=form.id).all()
    base = {"form_id": form.id, "title": form.title, "section_target": form.section_target or "ALL", "subject_code": form.subject_code or "N/A", "total_responses": len(subs), "min_required": MIN_ANON_GROUP}
    if not _privacy_exempt() and 0 < len(subs) < MIN_ANON_GROUP:
        base.update({"suppressed": True, "questions_analytics": [], "privacy_note": f"Results stay hidden until at least {MIN_ANON_GROUP} people have responded, so nobody can be picked out from a handful of answers. {len(subs)} so far."})
        return jsonify(base)

    try: questions = json.loads(form.questions_json)
    except Exception: questions = []

    q_stats = {str(q.get("id")): {"id": q.get("id"), "prompt": q.get("prompt"), "type": q.get("type", "narrative"), "total_answers": 0, "likert_sum": 0, "likert_counts": {1:0,2:0,3:0,4:0,5:0}, "choice_counts": {}, "narratives": []} for q in questions}

    for sub in subs:
        try:
            for ans in json.loads(sub.answers_json):
                qid = str(ans.get("question_id"))
                if qid in q_stats:
                    st = q_stats[qid]; st["total_answers"] += 1
                    val = ans.get("value"); score = ans.get("score")
                    if st["type"] == "likert":
                        try:
                            n = int(score if score is not None else val)
                            if 1 <= n <= 5: st["likert_sum"] += n; st["likert_counts"][n] += 1
                        except Exception: pass
                        if ans.get("narrative_text"): st["narratives"].append(ans.get("narrative_text"))
                    elif st["type"] in ["radio", "single_choice"] and val:
                        st["choice_counts"][str(val).strip()] = st["choice_counts"].get(str(val).strip(), 0) + 1
                    elif st["type"] in ["checkbox", "multiple_choice"] and isinstance(val, list):
                        for item in val:
                            if str(item).strip(): st["choice_counts"][str(item).strip()] = st["choice_counts"].get(str(item).strip(), 0) + 1
                    else:
                        n_val = ans.get("answer") or val or ans.get("narrative_text")
                        if n_val: st["narratives"].append(str(n_val))
        except Exception: pass

    for st in q_stats.values():
        st["narratives"] = [safe_out(n) for n in st["narratives"]]
        random.shuffle(st["narratives"])             # the order of answers would reveal who answered first
        if st["type"] == "likert": st["average_rating"] = round(st["likert_sum"] / st["total_answers"], 2) if st["total_answers"] > 0 else 0
        if not _privacy_exempt() and 0 < st["total_answers"] < MIN_ANON_GROUP:   # an optional question that only a few people answered
            st.update({"hidden": True, "narratives": [], "choice_counts": {}, "likert_counts": {1:0,2:0,3:0,4:0,5:0}, "average_rating": 0})

    base["questions_analytics"] = list(q_stats.values())
    return jsonify(base)

@app.route('/api/forms/<int:form_id>/export_csv', methods=['GET'])
@login_required
@api_guard
def export_form_csv(form_id):
    form, err = _manageable_form(form_id)
    if err: return err

    try: questions = json.loads(form.questions_json)
    except Exception: questions = []
    submissions = FormAnonymousSubmission.query.filter_by(form_id=form.id).all()
    if not _privacy_exempt() and 0 < len(submissions) < MIN_ANON_GROUP:
        return jsonify({"error": f"The export unlocks once at least {MIN_ANON_GROUP} people have responded, to protect their anonymity ({len(submissions)} so far)."}), 403
    random.shuffle(submissions)                      # row order would reveal who answered first

    parsed = []
    answered = {}
    for sub in submissions:
        ans_map = {}
        try:
            for it in json.loads(sub.answers_json): ans_map[str(it.get("question_id"))] = it
        except Exception: pass
        parsed.append(ans_map)
        for qid, it in ans_map.items():
            if it.get("value") not in (None, "", []) or it.get("narrative_text") or it.get("answer") or it.get("score") is not None: answered[qid] = answered.get(qid, 0) + 1

    def hidden(q): return (not _privacy_exempt()) and 0 < answered.get(str(q.get("id")), 0) < MIN_ANON_GROUP

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["Response #"]
    for q in questions:
        headers.append(f"Q{q.get('id')}: {q.get('prompt')}")
        if q.get("type") == "likert" and (q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]):
            headers.append(f"Q{q.get('id')} Elaboration")
    writer.writerow(headers)

    for n, ans_map in enumerate(parsed, 1):
        row = [n]
        for q in questions:
            entry = ans_map.get(str(q.get("id")), {})
            val = entry.get("value")
            if val is None: val = entry.get("score") or entry.get("answer")
            if isinstance(val, list): val = "; ".join(str(v) for v in val)
            row.append("(hidden: too few answers)" if hidden(q) else csv_safe(safe_out(val) if isinstance(val, str) else val))
            if q.get("type") == "likert" and (q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]):
                row.append("(hidden: too few answers)" if hidden(q) else csv_safe(safe_out(entry.get("narrative_text", ""))))
        writer.writerow(row)

    safe_title = re.sub(r'[^\w\-_\.]', '_', form.title)[:25]
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=survey_export_{form.id}_{safe_title}.csv"})

# ==========================================
# PRIVACY: small-group suppression + personal-detail masking
# ==========================================
# Results about fewer than this many people are not shown to anyone but MISD, because a handful of answers can point at one person.
# Set MIN_ANON_GROUP=1 in the environment to switch it off (for example during a demo with test data).
try: MIN_ANON_GROUP = max(1, int(os.getenv("MIN_ANON_GROUP", "5")))
except ValueError: MIN_ANON_GROUP = 5

def _is_student(): return str(getattr(current_user, "role", "") or "").startswith("Student")
def _privacy_exempt(): return getattr(current_user, "role", "") == "MISD"

_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_PH_MOBILE_RE = re.compile(r'(?<!\d)(?:\+?63|0)\s?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)')
_LONG_NUMBER_RE = re.compile(r'(?<!\d)(?:\d[\s.-]?){9,}\d(?!\d)')
_STUDENT_ID_RE = re.compile(r'(?<![\w-])(\d{2,4})-(\d{3,6})(?![\w-])')
_HANDLE_RE = re.compile(r'(?<![\w@])@[A-Za-z0-9_.]{3,30}')
_SELF_ID_RE = re.compile(r"(?i:\b(?:my name is|my name's|ako po si|ako si|ako po ay si|ako ay si|ang pangalan ko ay|pangalan ko po ay|name ko po ay|name ko ay)\s+(?:si\s+)?)[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2}")
_SELF_ID_FROM_RE = re.compile(r"(?i:\b(?:i am|i'm|this is)\s+)[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2}(?=\s+(?i:from|of|in|taking|a student|section|bsit|bscs)\b)")

def _keep_id_lookalike(m):
    a, b = m.group(1), m.group(2)
    if len(a) == 4 and len(b) == 4 and a[:2] in ("19", "20") and b[:2] in ("19", "20"): return m.group(0)       # academic year such as 2026-2027
    if len(a) == 2 and len(b) == 4 and 1 <= int(a) <= 12 and b[:2] in ("19", "20"): return m.group(0)           # month-year such as 03-2026
    return "[ID hidden]"

def scrub_pii(value):
    """Masks contact details, student numbers, @handles and 'my name is ...' style self-introductions, so a comment cannot reveal who wrote it.
    It cannot recognise every possible name, so it is a safety net and not a guarantee."""
    if not isinstance(value, str) or not value: return value
    out = _EMAIL_RE.sub("[email hidden]", value)
    out = _PH_MOBILE_RE.sub("[number hidden]", out)
    out = _LONG_NUMBER_RE.sub("[number hidden]", out)
    out = _STUDENT_ID_RE.sub(_keep_id_lookalike, out)
    out = _HANDLE_RE.sub("[handle hidden]", out)
    out = _SELF_ID_RE.sub("[self-introduction hidden]", out)
    out = _SELF_ID_FROM_RE.sub("[self-introduction hidden]", out)
    return out

def scrub_answers(answers):
    """Applies scrub_pii to every text-like value inside a list of survey answers."""
    cleaned = []
    for a in answers:
        a = dict(a)
        for k in ("narrative_text", "answer", "value"):
            if isinstance(a.get(k), str): a[k] = scrub_pii(a[k])
        cleaned.append(a)
    return cleaned


# ==========================================
# PROFANITY FILTER: the AI reads the original words (they carry intensity), but nothing profane is stored or shown
# ==========================================
# A starting list of strong profanity and insults in Tagalog, Cebuano and English. MISD can add more from the Slang Manager
# (category "profanity"). Spellings such as p.u.t.a, put@ngina or fuuuck, and endings such as -ng / -ing / -s, are caught automatically.
DEFAULT_PROFANITY = [
    "putangina", "putang ina", "tangina", "tang ina", "tanginamo", "pota", "potah", "puta", "putragis", "punyeta", "pakyu", "pakshet", "pakingshet", "amputa", "ampota",
    "gago", "gaga", "gagu", "ulol", "tarantado", "tarantada", "hinayupak", "kupal", "lintik", "siraulo", "sira ulo", "bobo", "tanga", "engot", "gunggong",
    "kantot", "kantutan", "jakol", "jabol", "puke", "pekpek", "tite", "burat", "pokpok", "bayag", "salsal", "yawa", "piste", "pisting yawa",
    "fuck", "fck", "motherfucker", "shit", "bullshit", "bitch", "bastard", "asshole", "dick", "dickhead", "pussy", "cunt", "slut", "whore", "douchebag",
    "nigger", "nigga", "faggot", "retard",
]
_LEET = {"a": "a@4", "e": "e3", "i": "i1!|", "o": "o0", "s": "s$5", "t": "t7"}
_LEET_CHARS = "@$!|"
_profanity_cache = {"regex": None, "words": (), "loaded_at": 0.0}

def _word_pattern(word):
    """One word or phrase as a pattern that tolerates repeated letters, look-alike symbols and a separator between letters."""
    pieces = []
    for ch in word.lower().strip():
        if ch == " ": pieces.append((r"[\s._\-]{0,2}", True))
        elif ch.isalnum(): pieces.append(("[" + re.escape(_LEET.get(ch, ch)) + "]+", False))
    out, prev_gap = "", True
    for pat, gap in pieces:
        if out and not gap and not prev_gap: out += r"[.\-_*]?"
        out += pat; prev_gap = gap
    return out

def _build_profanity_regex(words):
    words = sorted({w for w in words if w}, key=len, reverse=True)       # longest first, so a phrase is masked whole
    if not words: return None
    body = "|".join(_word_pattern(w) for w in words)
    return re.compile(r"(?<![A-Za-z])(?:" + body + r")(?:ng|s|es|ed|er|ers|ing|in|y)?(?![A-Za-z])", re.IGNORECASE)

def _db_profanity_words():
    try: return [t.word for t in LexiconTerm.query.filter_by(category="profanity").all()]
    except Exception: return []

def invalidate_profanity_cache(): _profanity_cache["loaded_at"] = 0.0

def profanity_words():
    extra = [w.strip().lower() for w in _db_profanity_words() if w and w.strip()]
    return sorted({w.lower() for w in DEFAULT_PROFANITY} | set(extra))

def _profanity_regex():
    now = time.time()
    if _profanity_cache["regex"] is None or now - _profanity_cache["loaded_at"] > 60:
        words = tuple(profanity_words())
        if words != _profanity_cache["words"] or _profanity_cache["regex"] is None:
            _profanity_cache["regex"], _profanity_cache["words"] = _build_profanity_regex(words), words
        _profanity_cache["loaded_at"] = now
    return _profanity_cache["regex"]

def _mask_span(m):
    s = m.group(0)
    idx = [i for i, c in enumerate(s) if c.isalnum() or c in _LEET_CHARS]
    if len(idx) <= 2: return "*" * len(s)
    keep = {idx[0], idx[-1]}
    return "".join(c if (i in keep or i not in idx) else "*" for i, c in enumerate(s))

def has_profanity(text):
    rx = _profanity_regex() if isinstance(text, str) and text else None
    return bool(rx and rx.search(text))

def mask_profanity(text):
    """'putangina' -> 'p*******a'. First and last letters stay so the comment still reads naturally."""
    rx = _profanity_regex() if isinstance(text, str) and text else None
    return rx.sub(_mask_span, text) if rx else text

def mask_any(obj):
    """mask_profanity applied to every string inside nested lists and dictionaries (analysis breakdowns, stored answers)."""
    if isinstance(obj, str): return mask_profanity(obj)
    if isinstance(obj, list): return [mask_any(x) for x in obj]
    if isinstance(obj, dict): return {k: mask_any(v) for k, v in obj.items()}
    return obj

def safe_out(text):
    """Everything shown to people or exported goes through this: personal details and profanity are hidden, including in older stored rows."""
    return mask_profanity(scrub_pii(text))

# ==========================================
# CSV IMPORT HELPERS (pure functions: parse, map columns, validate, de-duplicate)
# ==========================================
IMPORT_MAX_BYTES = 2 * 1024 * 1024
IMPORT_MAX_ROWS = 2000
IMPORT_CHUNK = 40            # rows scored per request, so a big file never hits a server time-out
IMPORT_SEMESTERS = {"1st semester": "1st Semester", "first semester": "1st Semester", "1st sem": "1st Semester", "1": "1st Semester", "1st": "1st Semester",
                    "2nd semester": "2nd Semester", "second semester": "2nd Semester", "2nd sem": "2nd Semester", "2": "2nd Semester", "2nd": "2nd Semester",
                    "summer": "Summer", "midyear": "Summer", "mid-year": "Summer"}
_AY_VALUE_RE = re.compile(r'^\s*((?:19|20)\d{2})\s*[-/]\s*((?:19|20)\d{2})\s*$')
_TEXT_KEYS = ("comment", "comments", "feedback", "feedbacks", "narrative", "narratives", "text", "review", "reviews", "response", "responses", "remark", "remarks")
_PROG_KEYS = ("program", "programs", "prog", "course", "courses")
_YEAR_KEYS = ("academicyear", "acadyear", "schoolyear", "ay", "sy", "year")
_SEM_KEYS = ("semester", "sem", "term")

def decode_csv_bytes(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try: return raw.decode(enc), enc.replace("utf-8-sig", "UTF-8")
        except UnicodeDecodeError: continue
    return raw.decode("utf-8-sig", errors="replace"), "UTF-8 (some characters could not be read)"

def _col_norm(c): return re.sub(r'[^a-z0-9]', '', str(c).lower())

def suggest_columns(fieldnames, rows_sample):
    """Whole-word / exact-name matching (the old 'contains' matching mistook words like 'payment' for the year column), plus a value check for year and semester."""
    def pick(keys, validator=None):
        for key in keys:                                  # earlier keys win
            for c in fieldnames:
                if _col_norm(c) == key:
                    if validator is None or validator(c): return c
        for c in fieldnames:
            if any(t in keys for t in re.split(r'[^a-z0-9]+', str(c).lower()) if t):
                if validator is None or validator(c): return c
        return None
    def values(c): return [str(r.get(c) or "").strip() for r in rows_sample if str(r.get(c) or "").strip()]
    def looks_like_year(c):
        v = values(c); return bool(v) and sum(1 for x in v if _AY_VALUE_RE.match(x)) / len(v) >= 0.6
    def looks_like_sem(c):
        v = values(c); return bool(v) and sum(1 for x in v if x.lower() in IMPORT_SEMESTERS) / len(v) >= 0.6
    text_hits = [c for c in fieldnames if any(t in _TEXT_KEYS for t in re.split(r'[^a-z0-9]+', str(c).lower()) if t) or _col_norm(c) in _TEXT_KEYS]
    mapping = {"text": pick(_TEXT_KEYS) or (fieldnames[0] if fieldnames else None), "program": pick(_PROG_KEYS),
               "year": pick(_YEAR_KEYS, looks_like_year), "semester": pick(_SEM_KEYS, looks_like_sem)}
    return mapping, len(text_hits) > 1

def parse_import_csv(raw_bytes, mapping, defaults):
    """Reads a CSV and returns every row's fate. Nothing is dropped silently: each skipped row has a reason."""
    text, encoding = decode_csv_bytes(raw_bytes)
    reader = csv.DictReader(io.StringIO(text))
    fields = [str(f).strip() for f in (reader.fieldnames or []) if f is not None and str(f).strip()]
    if not fields: raise ClientError("The file has no header row. The first line must contain the column names.")
    sample, all_rows = [], []
    for i, row in enumerate(reader):
        if i < 50: sample.append(row)
        all_rows.append(row)
        if len(all_rows) > IMPORT_MAX_ROWS + 5000: break
    suggested, ambiguous = suggest_columns(fields, sample)
    m = {k: (mapping.get(k) if mapping.get(k) in fields else None) for k in ("text", "program", "year", "semester")}
    if not m["text"]: m["text"] = suggested["text"]
    if not mapping:                                       # first look: use suggestions for the optional columns too
        for k in ("program", "year", "semester"): m[k] = suggested[k]

    valid, skipped, seen = [], [], set()
    stats = {"total_rows": len(all_rows), "truncated_text": 0, "defaulted_fields": 0, "over_limit": 0, "dup_in_file": 0}
    for idx, row in enumerate(all_rows):
        row_no = idx + 2                                  # +1 header, +1 for 1-based numbering (matches what Excel shows)
        if len(valid) >= IMPORT_MAX_ROWS:
            stats["over_limit"] += 1; continue
        txt = re.sub(r'\s+', ' ', str(row.get(m["text"]) or "")).strip()
        if not txt: skipped.append({"row": row_no, "reason": "Empty comment"}); continue
        if len(txt) < 3: skipped.append({"row": row_no, "reason": "Comment too short"}); continue
        if len(txt) > 5000: txt = txt[:5000]; stats["truncated_text"] += 1
        prog_raw = str(row.get(m["program"]) or "").strip()[:150] if m["program"] else ""
        if prog_raw: prog = prog_raw.upper()
        else:
            prog = (defaults.get("program") or "General").strip()[:150] or "General"
            if prog.lower() != "general": prog = prog.upper()
            if m["program"]: stats["defaulted_fields"] += 1
        yr_raw = str(row.get(m["year"]) or "").strip() if m["year"] else ""
        ym = _AY_VALUE_RE.match(yr_raw)
        year = f"{ym.group(1)}-{ym.group(2)}" if ym else (defaults.get("academic_year") or "2026-2027")
        if m["year"] and not ym: stats["defaulted_fields"] += 1
        sem_raw = str(row.get(m["semester"]) or "").strip().lower() if m["semester"] else ""
        sem = IMPORT_SEMESTERS.get(sem_raw) or (defaults.get("semester") or "1st Semester")
        if m["semester"] and sem_raw not in IMPORT_SEMESTERS: stats["defaulted_fields"] += 1
        key = (txt.lower(), prog, year, sem)
        if key in seen: stats["dup_in_file"] += 1; skipped.append({"row": row_no, "reason": "Duplicate of an earlier row in this file"}); continue
        seen.add(key)
        valid.append({"row": row_no, "text": txt, "program": prog, "academic_year": year, "semester": sem, "key": key})
    return {"encoding": encoding, "columns": fields, "mapping": m, "ambiguous": ambiguous, "valid": valid, "skipped": skipped, "stats": stats}


# ==========================================
# ACADEMIC YEARS MANAGEMENT API
# ==========================================
@app.route('/api/academic_years', methods=['GET', 'POST'])
@login_required
@api_guard
def handle_academic_years():
    if request.method == 'GET':
        return jsonify([y.year for y in AcademicYear.query.order_by(AcademicYear.year.desc()).all()])

    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403

    year_val = sfield(json_body(), 'year', max_len=20)
    if not year_val or not re.match(r'^\d{4}-\d{4}$', year_val): return jsonify({"error": "Format must be YYYY-YYYY."}), 400

    if AcademicYear.query.filter_by(year=year_val).first(): return jsonify({"error": "Already exists."}), 400
    db.session.add(AcademicYear(year=year_val))
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/settings/active_term', methods=['GET', 'POST'])
@login_required
@api_guard
def handle_active_term():
    if request.method == 'GET':
        yr, sem = get_active_term()
        return jsonify({"academic_year": yr, "semester": sem})

    if current_user.role != "MISD":
        return jsonify({"error": "Only MISD administrators can change the active institutional term."}), 403

    data = json_body()
    year_val = sfield(data, 'academic_year', max_len=20)
    sem_val = sfield(data, 'semester', max_len=30)

    if not year_val or not re.match(r'^\d{4}-\d{4}$', year_val):
        raise ClientError("Academic Year must follow YYYY-YYYY format.")
    if sem_val not in ("1st Semester", "2nd Semester", "Summer"):
        raise ClientError("Semester must be '1st Semester', '2nd Semester', or 'Summer'.")

    if not AcademicYear.query.filter_by(year=year_val).first():
        db.session.add(AcademicYear(year=year_val))

    set_active_term(year_val, sem_val)
    return jsonify({"success": True, "academic_year": year_val, "semester": sem_val})

# ==========================================
# DASHBOARD & ANALYTICS API
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role.startswith("Student"): return redirect(url_for('student_portal'))
    return render_template('dashboard.html', username=current_user.username, role=current_user.role, user_dept=current_user.department, user_program=current_user.program, tour_seen=bool(current_user.tour_seen))

@app.route('/api/analytics', methods=['GET'])
@login_required
@api_guard
def get_analytics():
    if _is_student(): return jsonify({"error": "Unauthorized."}), 403     # this endpoint used to answer any signed-in student
    selected_program = request.args.get('program', 'ALL').strip().upper()
    selected_sentiment = request.args.get('sentiment', 'ALL').strip().capitalize()
    
    selected_year = request.args.get('year', 'ALL').strip()
    selected_sem = request.args.get('semester', 'ALL').strip()
    search_query = request.args.get('search', '').strip()[:100]
    theme = "light" if request.args.get('theme') == "light" else "dark"
    page = request.args.get('page', 1, type=int)
    per_page = min(max(request.args.get('per_page', 10, type=int), 1), 100)
    source_filter = request.args.get('source', 'Portal').strip()

    query = Feedback.query.filter_by(department="DCI")
    
    if selected_program != 'ALL': query = query.filter(Feedback.program.ilike(f"%{selected_program}%"))
    if selected_sentiment != 'All': query = query.filter(func.lower(Feedback.sentiment) == selected_sentiment.lower())
    if selected_year != 'ALL': query = query.filter_by(academic_year=selected_year)
    if selected_sem != 'ALL': query = query.filter_by(semester=selected_sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)
    if search_query: query = query.filter((Feedback.raw_text.ilike(f"%{search_query}%")))

    all_matching = query.all()
    suppressed = (not _privacy_exempt()) and 0 < len(all_matching) < MIN_ANON_GROUP
    privacy_note = None
    if suppressed:
        privacy_note = f"Only {len(all_matching)} response(s) match these filters, so the details are hidden to protect the people who wrote them (minimum {MIN_ANON_GROUP})."
        all_matching = []
    total_items = len(all_matching)
    total_pages = max(1, math.ceil(total_items / per_page)) if total_items > 0 else 1
    page = min(max(1, page), total_pages)

    pos = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'positive')
    neg = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'negative')
    neu = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'neutral')

    aspect_counts = {
        "Instructional Delivery": {"pos": 0, "neg": 0, "neu": 0},
        "Faculty Demeanor": {"pos": 0, "neg": 0, "neu": 0},
        "Facilities": {"pos": 0, "neg": 0, "neu": 0}
    }

    for r in all_matching:
        try:
            for item in json.loads(r.aspect_breakdown):
                asp, pol = item.get("aspect", ""), str(item.get("polarity", "")).capitalize()
                key = "Instructional Delivery" if "Instructional" in asp else "Faculty Demeanor" if "Demeanor" in asp else "Facilities" if "Facilities" in asp else None
                if key and pol in ["Positive", "Negative", "Neutral"]:
                    aspect_counts[key]["pos" if pol == "Positive" else "neg" if pol == "Negative" else "neu"] += 1
        except: pass

    paged_records = [] if suppressed else query.order_by(Feedback.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    recent_logs = []
    for entry in paged_records:
        try: parsed = json.loads(entry.aspect_breakdown)
        except: parsed = []
        
        has_sarcasm = any(
            item.get("has_sarcasm", False) or
            any(t.get("role") == "Sarcasm Invalidator" for t in item.get("token_scores", [])) or
            "sarcasm" in str(item.get("explanation", "")).lower()
            for item in parsed
        )

        recent_logs.append({
            "id": entry.id, "form_id": entry.form_id, "department": entry.department,
            "program": entry.program or "General", "academic_year": entry.academic_year or "2026-2027",
            "semester": entry.semester or "1st Semester", "raw_text": safe_out(entry.raw_text),
            "sentiment": entry.sentiment,
            "ai_sentiment": entry.ai_sentiment or entry.sentiment,
            "human_sentiment": entry.human_sentiment,
            "verified_by": entry.verified_by,
            "verified_at": entry.verified_at.strftime("%Y-%m-%d %H:%M") if entry.verified_at else None,
            "confidence": entry.confidence, "aspects": parsed,
            "has_sarcasm": has_sarcasm,
            "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M") if entry.timestamp else ""
        })

    active_yr, active_sem = get_active_term()
    return jsonify({
        "program": selected_program, "sentiment": selected_sentiment, "year": selected_year, "semester": selected_sem,
        "active_term": {"academic_year": active_yr, "semester": active_sem},
        "available_years": [y.year for y in AcademicYear.query.order_by(AcademicYear.year.desc()).all()],
        "kpis": {"total": total_items, "pos": pos, "neg": neg, "neu": neu},
        "pie_chart": generate_matplotlib_pie(pos, neg, neu, theme),
        "aspect_chart": generate_matplotlib_bar(aspect_counts, theme),
        "insights": compute_prescriptive_insights(all_matching),
        "logs": recent_logs, "suppressed": suppressed, "privacy_note": privacy_note,
        "profanity_count": sum(1 for r in all_matching if r.has_profanity),
        "verified_count": sum(1 for r in all_matching if r.human_sentiment),
        "pagination": {"page": page, "per_page": per_page, "total_items": total_items, "total_pages": total_pages}
    })

@app.route('/api/analytics/keywords', methods=['GET'])
@login_required
@api_guard
def get_analytics_keywords():
    if _is_student(): return jsonify({"error": "Unauthorized."}), 403
    prog = request.args.get('program', 'ALL').strip().upper()
    sent = request.args.get('sentiment', 'ALL').strip().capitalize()
    yr = request.args.get('year', 'ALL').strip()
    sem = request.args.get('semester', 'ALL').strip()
    source_filter = request.args.get('source', 'Portal').strip()

    query = Feedback.query.filter_by(department="DCI")
    if prog != 'ALL': query = query.filter(Feedback.program.ilike(f"%{prog}%"))
    if sent != 'All': query = query.filter(func.lower(Feedback.sentiment) == sent.lower())
    if yr != 'ALL': query = query.filter_by(academic_year=yr)
    if sem != 'ALL': query = query.filter_by(semester=sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)

    stop_words = {"ang", "mga", "ng", "sa", "na", "ay", "at", "ito", "pa", "ko", "mo", "nya", "ni", "pero", "kaso", "din", "rin", "ba", "lang", "naman", "ka", "kaya", "kasi", "mismo", "the", "and", "to", "a", "of", "in", "for", "is", "on", "that", "by", "this", "with", "i", "you", "it", "not", "or", "be", "are", "from", "at", "as", "your", "all", "have", "more", "was", "we", "they", "an", "so", "up", "out", "if", "about", "who", "get", "which", "para", "kung", "dahil", "kaming", "kami", "sila", "nila", "namin", "kanila", "aking", "ung", "yung", "nong", "nung", "may", "meron", "lahat", "naging", "mas", "wag", "daw", "raw"}

    word_counts = {}
    for r in query.all():
        for token in re.findall(r'\b[a-z]{3,}\b', f"{scrub_pii(r.raw_text)} {scrub_pii(r.cleaned_text)}".lower()):
            if token not in stop_words and not token.isdigit():
                word_counts[token] = word_counts.get(token, 0) + 1

    min_count = 2 if _privacy_exempt() else max(2, MIN_ANON_GROUP)   # a word used once or twice can point at one person (for example a name)
    ranked = [w for w in sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:80] if w[1] >= min_count and not has_profanity(w[0])]
    return jsonify({"keywords": [{"word": w[0], "count": w[1]} for w in ranked[:30]]})

# ==========================================
# PRE-FLIGHT AI SENTIMENT INSPECTION
# ==========================================
@app.route('/api/inspect_preview', methods=['POST'])
@limiter.limit("40 per minute")
@login_required
@api_guard
def inspect_preview():
    comment = sfield(json_body(), "comment", max_len=5000)
    if not comment: return jsonify({"error": "No text provided."}), 400
    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, get_active_lexicon())
    has_sarcasm = any(item.get("has_sarcasm", False) for item in breakdown)
    return jsonify({
        "raw": mask_profanity(comment),
        "cleaned": mask_profanity(cleaned),
        "sentiment": sentiment,
        "confidence_score": score,
        "aspect_breakdown": mask_any(breakdown),
        "has_sarcasm": has_sarcasm
    })

@app.route('/api/analyze', methods=['POST'])
@login_required
@api_guard
def analyze_api():
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    data = json_body()
    comment = sfield(data, "comment", max_len=5000)
    if not comment: return jsonify({"error": "No comment provided."}), 400

    expected = sfield(data, "expected_sentiment", "", max_len=20).capitalize()
    human_label = expected if expected in ("Positive", "Neutral", "Negative") else None

    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, get_active_lexicon())
    entry = Feedback(
        department="DCI", program=sfield(data, "program", "Institutional Testing", max_len=150) or "Institutional Testing",
        academic_year=sfield(data, "academic_year", "2026-2027", max_len=20) or "2026-2027", semester=sfield(data, "semester", "1st Semester", max_len=30) or "1st Semester",
        raw_text=mask_profanity(comment), cleaned_text=mask_profanity(cleaned),
        sentiment=human_label or sentiment,
        ai_sentiment=sentiment,
        human_sentiment=human_label,
        verified_by=current_user.username if human_label else None,
        verified_at=datetime.utcnow() if human_label else None,
        confidence=score, aspect_breakdown=json.dumps(mask_any(breakdown)), source="Testing",
        has_profanity=has_profanity(comment)
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({"success": True, "ai_sentiment": sentiment, "human_sentiment": human_label})

# ==========================================
# MISD SENTIMENT OVERRIDE & AI EVALUATION (CONFUSION MATRIX / F1-SCORE)
# ==========================================
EVAL_CLASSES = ("Positive", "Neutral", "Negative")

TAGLISH_BENCHMARK_SUITE = [
    {"program": "BSCS", "expected": "Positive", "text": "Sobrang husay at malinaw magturo ni sir sa Data Structures, solid ang discussion."},
    {"program": "BSIT", "expected": "Positive", "text": "Maayos na yung mga computer at solid na ulit ang internet connection sa networking laboratory."},
    {"program": "BSCS", "expected": "Positive", "text": "Napakabait at very approachable ng faculty pag may tanong kami sa programming."},
    {"program": "BSCS", "expected": "Positive", "text": "Goods na goods ang pacing ng lecture, madali maintindihan kahit mahirap yung topic."},
    {"program": "BSIT", "expected": "Positive", "text": "Masipag mag-explain si maam at helpful yung mga lab exercises na binibigay niya."},
    {"program": "BSCS", "expected": "Positive", "text": "Hindi mahirap sundan yung lesson kasi step by step at clear ang paliwanag."},
    {"program": "BSIT", "expected": "Positive", "text": "Maganda at malamig na sa computer lab, maayos na rin ang projector."},
    {"program": "BSIT", "expected": "Positive", "text": "Super galing ng instructor namin sa Web Development, sulit ang bawat session."},
    {"program": "BSCS", "expected": "Positive", "text": "Hindi masungit si prof, chill lang pero marami kaming natututunan sa klase."},
    {"program": "BSIT", "expected": "Positive", "text": "Best department event so far, maayos ang organization at masaya ang lahat."},
    {"program": "BSIT", "expected": "Negative", "text": "Sobrang init sa classroom at sira pa yung dalawang electric fan sa likod."},
    {"program": "BSCS", "expected": "Negative", "text": "Ang galing magturo ni sir sobrang linaw talaga eme, wala kaming naintindihan."},
    {"program": "BSCS", "expected": "Negative", "text": "Mabilis masyado ang pacing ng discussion at magulo yung instructions sa laboratory."},
    {"program": "BSIT", "expected": "Negative", "text": "Mabagal ang wifi sa lab at laging naghahang yung mga lumang computer units."},
    {"program": "BSCS", "expected": "Negative", "text": "Hindi maayos ang paliwanag sa algorithm, nakakalito at sobrang hirap ng quiz."},
    {"program": "BSIT", "expected": "Negative", "text": "Masungit sumagot kapag nagtatanong kami tungkol sa project requirements."},
    {"program": "BSIT", "expected": "Negative", "text": "Ang ganda ng laboratory facilities namin charot, sira naman ang aircon at projector."},
    {"program": "BSCS", "expected": "Negative", "text": "Laging late magsimula ang klase tapos sobrang boring at sabaw ng lecture."},
    {"program": "BSIT", "expected": "Negative", "text": "Hindi malinaw ang grading rubric at walang feedback sa mga pinasa naming activity."},
    {"program": "BSCS", "expected": "Negative", "text": "Mainit at masikip sa room, mahirap mag-focus habang nagko-code."},
    {"program": "BSCS", "expected": "Neutral",  "text": "Our departmental examination for Computer Science is scheduled next Monday morning."},
    {"program": "BSIT", "expected": "Neutral",  "text": "The laboratory class was moved from Room 301 to the second floor computer room."},
    {"program": "BSIT", "expected": "Neutral",  "text": "We submitted the printed documentation and source code repository link yesterday."},
    {"program": "BSCS", "expected": "Neutral",  "text": "Magkakaroon ng general orientation para sa lahat ng first year students bukas."},
    {"program": "BSIT", "expected": "Neutral",  "text": "The syllabus covers database normalization during the midterm period."},
    {"program": "BSIT", "expected": "Neutral",  "text": "Three sections attended the seminar held at the campus auditorium."},
    {"program": "BSCS", "expected": "Neutral",  "text": "Nag-upload na ng bagong module at reading materials sa portal."},
    {"program": "BSIT", "expected": "Neutral",  "text": "Class representatives will attend the regular department meeting this afternoon."},
    {"program": "BSCS", "expected": "Neutral",  "text": "Our group used Python and PostgreSQL for the capstone prototype."},
    {"program": "BSCS", "expected": "Neutral",  "text": "Midterm grades will be encoded in the system after the consultation week."}
]

def compute_classification_metrics(items):
    matrix = {a: {p: 0 for p in EVAL_CLASSES} for a in EVAL_CLASSES}
    disagreements = []
    valid_items = []

    for it in items:
        act = str(it.get("actual") or "").strip().capitalize()
        pred = str(it.get("predicted") or "").strip().capitalize()
        if act in EVAL_CLASSES and pred in EVAL_CLASSES:
            matrix[act][pred] += 1
            valid_items.append(it)
            if act != pred:
                disagreements.append(it)

    total = len(valid_items)
    if total == 0:
        return {
            "total": 0, "correct": 0, "accuracy": 0.0,
            "macro_precision": 0.0, "macro_recall": 0.0, "macro_f1": 0.0, "weighted_f1": 0.0,
            "matrix": matrix,
            "per_class": {c: {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0, "tp": 0, "fp": 0, "fn": 0} for c in EVAL_CLASSES},
            "disagreements": []
        }

    correct = sum(matrix[c][c] for c in EVAL_CLASSES)
    accuracy = round((correct / total) * 100, 2)

    per_class = {}
    active_classes = []
    for c in EVAL_CLASSES:
        tp = matrix[c][c]
        fp = sum(matrix[a][c] for a in EVAL_CLASSES if a != c)
        fn = sum(matrix[c][p] for p in EVAL_CLASSES if p != c)
        support = tp + fn

        prec = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        per_class[c] = {
            "precision": round(prec * 100, 2),
            "recall": round(rec * 100, 2),
            "f1": round(f1 * 100, 2),
            "support": support,
            "tp": tp, "fp": fp, "fn": fn
        }
        if support > 0 or (tp + fp) > 0:
            active_classes.append(c)

    denom = len(active_classes) if active_classes else 3
    macro_prec = round(sum(per_class[c]["precision"] for c in active_classes) / denom, 2)
    macro_rec = round(sum(per_class[c]["recall"] for c in active_classes) / denom, 2)
    macro_f1 = round(sum(per_class[c]["f1"] for c in active_classes) / denom, 2)
    weighted_f1 = round(sum(per_class[c]["f1"] * per_class[c]["support"] for c in EVAL_CLASSES) / total, 2)

    return {
        "total": total, "correct": correct, "accuracy": accuracy,
        "macro_precision": macro_prec, "macro_recall": macro_rec,
        "macro_f1": macro_f1, "weighted_f1": weighted_f1,
        "matrix": matrix, "per_class": per_class,
        "disagreements": disagreements[:35]
    }

@app.route('/api/feedback/<int:feedback_id>/override', methods=['POST'])
@login_required
@api_guard
def override_feedback_sentiment(feedback_id):
    if current_user.role != "MISD":
        return jsonify({"error": "Only MISD administrators can verify or override sentiment classifications."}), 403

    entry = db.session.get(Feedback, feedback_id)
    if not entry:
        return jsonify({"error": "Feedback record not found."}), 404

    data = json_body()
    if not entry.ai_sentiment:
        entry.ai_sentiment = entry.sentiment

    if data.get("reset") is True:
        entry.sentiment = entry.ai_sentiment
        entry.human_sentiment = None
        entry.verified_by = None
        entry.verified_at = None
        db.session.commit()
        _chart_cache.clear()
        return jsonify({
            "success": True, "id": entry.id,
            "sentiment": entry.sentiment, "ai_sentiment": entry.ai_sentiment,
            "human_sentiment": None, "verified_by": None, "verified_at": None
        })

    new_sent = sfield(data, "sentiment", max_len=20).capitalize()
    if new_sent not in EVAL_CLASSES:
        raise ClientError("Sentiment must be 'Positive', 'Neutral', or 'Negative'.")

    entry.human_sentiment = new_sent
    entry.sentiment = new_sent
    entry.verified_by = current_user.username
    entry.verified_at = datetime.utcnow()
    db.session.commit()
    _chart_cache.clear()

    return jsonify({
        "success": True, "id": entry.id,
        "sentiment": entry.sentiment, "ai_sentiment": entry.ai_sentiment,
        "human_sentiment": entry.human_sentiment,
        "verified_by": entry.verified_by,
        "verified_at": entry.verified_at.strftime("%Y-%m-%d %H:%M")
    })

@app.route('/api/model_evaluation', methods=['GET'])
@login_required
@api_guard
def get_model_evaluation():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized."}), 403

    mode = request.args.get("mode", "verified").strip().lower()
    total_db_records = Feedback.query.filter_by(department="DCI").count()
    verified_rows = Feedback.query.filter(Feedback.department == "DCI", Feedback.human_sentiment.isnot(None)).order_by(Feedback.id.desc()).all()

    if mode == "benchmark":
        lexicon = get_active_lexicon()
        items = []
        for idx, b in enumerate(TAGLISH_BENCHMARK_SUITE, 1):
            _, pred_sent, conf, _ = run_absa_pipeline(b["text"], lexicon)
            items.append({
                "id": idx,
                "program": b["program"],
                "text": b["text"],
                "actual": b["expected"],
                "predicted": pred_sent,
                "confidence": conf
            })
        metrics = compute_classification_metrics(items)
        metrics["mode"] = "benchmark"
        metrics["total_db_records"] = total_db_records
        metrics["verified_db_count"] = len(verified_rows)
        return jsonify(metrics)

    items = []
    for r in verified_rows:
        items.append({
            "id": r.id,
            "program": r.program or "General",
            "text": safe_out(r.raw_text),
            "actual": r.human_sentiment,
            "predicted": r.ai_sentiment or r.sentiment,
            "confidence": r.confidence,
            "verified_by": r.verified_by or "MISD"
        })
    metrics = compute_classification_metrics(items)
    metrics["mode"] = "verified"
    metrics["total_db_records"] = total_db_records
    metrics["verified_db_count"] = len(verified_rows)
    return jsonify(metrics)

@app.route('/api/model_evaluation/seed_benchmark', methods=['POST'])
@login_required
@api_guard
def seed_benchmark_into_db():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized."}), 403

    active_yr, active_sem = get_active_term()
    lexicon = get_active_lexicon()
    existing_texts = {
        (r.raw_text or "").strip().lower()
        for r in Feedback.query.filter_by(department="DCI", source="Testing").all()
    }

    added = 0
    for b in TAGLISH_BENCHMARK_SUITE:
        masked_raw = mask_profanity(b["text"])
        if masked_raw.strip().lower() in existing_texts:
            continue
        cleaned, pred_sent, score, breakdown = run_absa_pipeline(b["text"], lexicon)
        db.session.add(Feedback(
            department="DCI",
            program=b["program"],
            academic_year=active_yr,
            semester=active_sem,
            raw_text=masked_raw,
            cleaned_text=mask_profanity(cleaned),
            sentiment=b["expected"],
            ai_sentiment=pred_sent,
            human_sentiment=b["expected"],
            verified_by=current_user.username,
            verified_at=datetime.utcnow(),
            confidence=score,
            aspect_breakdown=json.dumps(mask_any(breakdown)),
            source="Testing",
            has_profanity=has_profanity(b["text"])
        ))
        existing_texts.add(masked_raw.strip().lower())
        added += 1

    db.session.commit()
    _chart_cache.clear()
    return jsonify({"success": True, "added": added})

# ==========================================
# CSV IMPORT (MISD): preview first, then import in small chunks, with undo
# ==========================================
def _read_import_upload():
    if 'file' not in request.files: raise ClientError("No file uploaded.")
    f = request.files['file']
    name = (f.filename or "").strip()
    if not name.lower().endswith('.csv'): raise ClientError("Must be a valid .csv file.")
    raw = f.stream.read(IMPORT_MAX_BYTES + 1)
    if len(raw) > IMPORT_MAX_BYTES: raise ClientError("CSV file is too large. Max allowed is 2MB. Split it into smaller files.")
    if not raw.strip(): raise ClientError("The file is empty.")
    return raw, name[:255]

def _import_defaults():
    ay = (request.form.get('academic_year') or '').strip()
    sem = (request.form.get('semester') or '').strip()
    return {"program": (request.form.get('program') or 'General').strip()[:150],
            "academic_year": ay if re.match(r'^\d{4}-\d{4}$', ay) else "2026-2027",
            "semester": IMPORT_SEMESTERS.get(sem.lower(), sem if sem in ("1st Semester", "2nd Semester", "Summer") else "1st Semester")}

def _import_mapping():
    try: m = json.loads(request.form.get('mapping') or "{}")
    except ValueError: raise ClientError("The column choices could not be read. Please run the preview again.")
    return {k: (m.get(k) if isinstance(m.get(k), str) else None) for k in ("text", "program", "year", "semester")} if isinstance(m, dict) else {}

def _import_key(v):
    return (re.sub(r'\s+', ' ', mask_profanity(scrub_pii(v["text"]))).strip().lower(), v["program"].lower(), v["academic_year"], v["semester"])

def _split_existing_duplicates(valid, exclude_batch=None):
    """Rows that already exist in the database (same comment, program, year and semester) are not imported twice."""
    if not valid: return [], []
    q = db.session.query(Feedback.raw_text, Feedback.program, Feedback.academic_year, Feedback.semester).filter(
        Feedback.source == "CSV", Feedback.academic_year.in_({v["academic_year"] for v in valid}), Feedback.semester.in_({v["semester"] for v in valid}))
    if exclude_batch: q = q.filter((Feedback.import_batch.is_(None)) | (Feedback.import_batch != exclude_batch))
    have = {(re.sub(r'\s+', ' ', t or '').strip().lower(), (p or 'General').lower(), y, s) for t, p, y, s in q.all()}
    fresh, dupes = [], []
    for v in valid: (dupes if _import_key(v) in have else fresh).append(v)
    return fresh, dupes

@app.route('/api/import/preview', methods=['POST'])
@limiter.limit("40 per hour")
@login_required
@api_guard
def import_preview():
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    raw, name = _read_import_upload()
    parsed = parse_import_csv(raw, _import_mapping(), _import_defaults())
    fresh, dupes = _split_existing_duplicates(parsed["valid"])
    st = parsed["stats"]
    pii_rows = sum(1 for v in fresh if scrub_pii(v["text"]) != v["text"])
    profanity_rows = sum(1 for v in fresh if has_profanity(v["text"]))
    return jsonify({
        "filename": name, "file_sha256": hashlib.sha256(raw).hexdigest(), "encoding": parsed["encoding"],
        "columns": parsed["columns"], "mapping": parsed["mapping"], "ambiguous": parsed["ambiguous"],
        "total_rows": st["total_rows"], "importable": len(fresh), "duplicates_existing": len(dupes), "duplicates_in_file": st["dup_in_file"],
        "skipped_total": len(parsed["skipped"]), "skipped": parsed["skipped"][:40], "over_limit": st["over_limit"], "max_rows": IMPORT_MAX_ROWS,
        "truncated_text": st["truncated_text"], "defaulted_fields": st["defaulted_fields"], "pii_rows": pii_rows, "profanity_rows": profanity_rows,
        "samples": [{"row": v["row"], "text": safe_out(v["text"])[:220], "program": v["program"], "academic_year": v["academic_year"], "semester": v["semester"]} for v in fresh[:5]]
    })

@app.route('/api/import/commit', methods=['POST'])
@limiter.limit("400 per hour")
@login_required
@api_guard
def import_commit():
    """Scores and stores one small chunk, then reports where it stopped. The page keeps calling it until done, so a big file never times out
    and a dropped connection can simply resume (the server counts what the batch already holds)."""
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    raw, name = _read_import_upload()
    sha = hashlib.sha256(raw).hexdigest()
    if request.form.get("file_sha256") and request.form.get("file_sha256") != sha:
        return jsonify({"error": "The file is different from the one you previewed. Please preview it again."}), 409
    batch_id = (request.form.get("batch_id") or "").strip() or str(uuid.uuid4())
    try: uuid.UUID(batch_id)
    except ValueError: return jsonify({"error": "Invalid import id."}), 400

    parsed = parse_import_csv(raw, _import_mapping(), _import_defaults())
    importable, dupes = _split_existing_duplicates(parsed["valid"], exclude_batch=batch_id)
    batch = db.session.get(ImportBatch, batch_id)
    if batch is None:
        batch = ImportBatch(id=batch_id, filename=name, uploaded_by=current_user.username[:150], file_sha256=sha, total_rows=parsed["stats"]["total_rows"],
                            importable=len(importable), imported=0, skipped=len(parsed["skipped"]), duplicates=len(dupes) + parsed["stats"]["dup_in_file"], status="running")
        db.session.add(batch)
    elif batch.status == "rolled_back":
        return jsonify({"error": "This import was already undone."}), 409
    elif batch.file_sha256 != sha:
        return jsonify({"error": "This import id belongs to a different file."}), 409

    start = Feedback.query.filter_by(import_batch=batch_id).count()          # resumes safely if a request is repeated
    chunk = importable[start:start + IMPORT_CHUNK]
    lex = get_active_lexicon()
    for v in chunk:
        text = scrub_pii(v["text"])
        cleaned, sentiment, score, breakdown = run_absa_pipeline(text, lex)
        db.session.add(Feedback(department="DCI", program=v["program"], academic_year=v["academic_year"], semester=v["semester"], raw_text=mask_profanity(text),
                                cleaned_text=mask_profanity(cleaned), sentiment=sentiment, ai_sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(mask_any(breakdown)), source="CSV",
                                import_batch=batch_id, has_profanity=has_profanity(text)))
    imported = start + len(chunk)
    batch.imported = imported
    done = imported >= len(importable)
    if done: batch.status = "completed"
    db.session.commit()
    return jsonify({"success": True, "batch_id": batch_id, "imported": imported, "total": len(importable), "done": done})

@app.route('/api/import/history', methods=['GET'])
@login_required
@api_guard
def import_history():
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    rows = ImportBatch.query.order_by(ImportBatch.created_at.desc()).limit(15).all()
    return jsonify([{"id": b.id, "filename": b.filename, "uploaded_by": b.uploaded_by, "imported": b.imported or 0, "importable": b.importable or 0,
                     "skipped": b.skipped or 0, "duplicates": b.duplicates or 0, "status": b.status,
                     "created_at": b.created_at.strftime("%b %d, %Y • %I:%M %p") if b.created_at else "",
                     "can_undo": b.status != "rolled_back" and (b.imported or 0) > 0} for b in rows])

@app.route('/api/import/<batch_id>/rollback', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
@api_guard
def import_rollback(batch_id):
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    batch = db.session.get(ImportBatch, batch_id)
    if not batch: return jsonify({"error": "Import not found."}), 404
    if batch.status == "rolled_back": return jsonify({"error": "This import was already undone."}), 409
    removed = Feedback.query.filter_by(import_batch=batch_id).delete(synchronize_session=False)
    batch.status = "rolled_back"; batch.rolled_back_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "removed": removed})

@app.route('/api/export_csv', methods=['GET'])
@login_required
@api_guard
def export_csv():
    if _is_student(): return jsonify({"error": "Unauthorized."}), 403     # this export used to be open to every signed-in student
    prog = request.args.get('program', 'ALL').strip().upper()
    sent = request.args.get('sentiment', 'ALL').strip().capitalize()
    yr = request.args.get('year', 'ALL').strip()
    sem = request.args.get('semester', 'ALL').strip()
    source_filter = request.args.get('source', 'Portal').strip()

    query = Feedback.query.filter_by(department="DCI")
    if prog != 'ALL': query = query.filter(Feedback.program.ilike(f"%{prog}%"))
    if sent != 'All': query = query.filter(func.lower(Feedback.sentiment) == sent.lower())
    if yr != 'ALL': query = query.filter_by(academic_year=yr)
    if sem != 'ALL': query = query.filter_by(semester=sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Academic Year", "Semester", "Program", "Data Source", "Raw Feedback", "Sentiment", "Confidence", "Timestamp"])

    records = query.order_by(Feedback.id.asc()).all()
    if not _privacy_exempt() and 0 < len(records) < MIN_ANON_GROUP:
        return jsonify({"error": f"The export unlocks once at least {MIN_ANON_GROUP} responses match these filters ({len(records)} so far), to protect the people who wrote them."}), 403
    for r in records:
        writer.writerow([r.id, csv_safe(r.academic_year), csv_safe(r.semester), csv_safe(r.program), csv_safe(r.source), csv_safe(safe_out(r.raw_text)), r.sentiment, r.confidence, r.timestamp])

    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=dci_sentiment_export.csv"})

@app.route('/api/lexicon', methods=['GET', 'POST', 'DELETE'])
@login_required
@api_guard
def manage_lexicon():
    if request.method == 'GET':
        if _is_student(): return jsonify({"error": "Unauthorized."}), 403
        return jsonify([{"id": t.id, "word": t.word, "category": t.category} for t in LexiconTerm.query.order_by(LexiconTerm.id.desc()).all()])

    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403

    if request.method == 'POST':
        data = json_body()
        word, cat = sfield(data, 'word', max_len=100).lower(), sfield(data, 'category', max_len=50).lower()
        if not word or cat not in ['positive', 'negative', 'intensifiers', 'negations', 'profanity']: return jsonify({"error": "Invalid input."}), 400
        if LexiconTerm.query.filter_by(word=word).first(): return jsonify({"error": "Already exists."}), 400
        db.session.add(LexiconTerm(word=word, category=cat))
        db.session.commit()
        invalidate_profanity_cache()
        return jsonify({"success": True})

    term = LexiconTerm.query.get(ifield(json_body(), 'id'))
    if not term: return jsonify({"error": "Not found."}), 404
    db.session.delete(term)
    db.session.commit()
    invalidate_profanity_cache()
    return jsonify({"success": True})

if os.getenv("PRELOAD_MODEL") == "1":
    def _warm_model():
        try:
            get_classifier()
            app.logger.info("Sentiment model is loaded and ready.")
        except Exception as warm_err:
            app.logger.warning("Model preload failed (it will retry on first use): %s", warm_err)
    threading.Thread(target=_warm_model, daemon=True).start()   # the first visitor should not have to wait for the model to load

if os.getenv("SKIP_DB_INIT") != "1":
    try:
        setup_database()
    except Exception as _db_init_err:
        app.logger.warning("Startup DB init notice: %s", _db_init_err)

if __name__ == '__main__':
    app.run(debug=False, port=int(os.getenv("PORT", "5000"))) 