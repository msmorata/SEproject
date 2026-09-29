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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func
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
from transformers import pipeline

# Headless thread-safe Matplotlib configuration
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

# ==========================================
# APP INITIALIZATION & ENVIRONMENT SECRETS
# ==========================================
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# Secrets moved to environment variables with local fallbacks
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "postgresql://postgres:admin@localhost:5432/ccc_sentiment")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Hardened Cookie Policies
app.config['SESSION_COOKIE_SECURE'] = os.getenv("FLASK_ENV") == "production"
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = "Lax"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# Cap request bodies
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Survive dropped connections and enforce statement timeouts
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgresql"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_timeout": 10,
        "connect_args": {"connect_timeout": 5, "options": "-c statement_timeout=20000"},
    }

db = SQLAlchemy(app)

# CSRF Protection and Rate Limiting
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["2000 per hour"], storage_uri="memory://")

# ==========================================
# LIVE SMTP GMAIL DISPATCH CONFIGURATION
# ==========================================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
MAIL_SENDER = os.getenv("MAIL_SENDER", "sentimentanalysissystem@gmail.com")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "hasvxaybrhbfphxv")

_mail_pool = ThreadPoolExecutor(max_workers=2)

def send_verification_email(recipient_email, code, username):
    try:
        msg = EmailMessage()
        msg['Subject'] = "City College of Calamba — Community Portal Passcode"
        msg['From'] = f"CCC Community Feedback Collective <{MAIL_SENDER}>"
        msg['To'] = recipient_email

        safe_username = html.escape(username)

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
                <p style="color: #cbd5e1; font-size: 14px; text-align: left;">Welcome to the student community voice collective. Use your 6-digit code below to activate your account:</p>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #fbbf24; background: #070d1d; border: 1.5px dashed rgba(245, 158, 11, 0.6); padding: 14px; border-radius: 10px; margin: 24px 0;">
                    {code}
                </div>
                <p style="color: #94a3b8; font-size: 12px; text-align: left;">This passcode confirms your institutional identity. Do not share this code. It will expire in 10 minutes.</p>
            </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype='html')

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(MAIL_SENDER, MAIL_PASSWORD)
            server.send_message(msg)

        print(f"[+] Verification email sent to: {recipient_email}")
    except Exception as e:
        print(f"[-] SMTP Delivery Notice: {e}")

# ==========================================
# ERROR HANDLING & API GUARDS
# ==========================================
class ClientError(ValueError):
    """Client input error mapping to HTTP 400."""

class ModelUnavailable(RuntimeError):
    """Sentiment model offline or uninitialized."""

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

def text_of(v):
    return v.strip() if isinstance(v, str) else ""

def safe_filename(s, n=40):
    return re.sub(r'[^\w\-.]', '_', str(s))[:n]

@app.after_request
def apply_security_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.vary.add("Cookie")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@app.errorhandler(CSRFError)
def csrf_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Session expired or invalid CSRF token. Reload the page."}), 400
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
    if isinstance(e, IntegrityError): return "This action conflicts with existing data (e.g., duplicate submission).", 409, False
    if isinstance(e, DataError): return "One of the submitted values is invalid or too long.", 400, False
    if isinstance(e, (OperationalError, InterfaceError, PoolTimeoutError)): return "The database is busy or temporarily unavailable. Please try again in a moment.", 503, True
    if isinstance(e, ModelUnavailable): return "The AI sentiment engine is still starting up or unavailable. Please try again shortly.", 503, True
    if isinstance(e, (ValueError, TypeError, KeyError)): return "Invalid request payload.", 400, True
    return "Something went wrong processing your request.", 500, True

def _safe_rollback():
    try: db.session.rollback()
    except Exception: app.logger.warning("Session rollback failed.", exc_info=True)

@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    is_api = request.path.startswith("/api/")
    if isinstance(e, HTTPException) and not is_api: return e
    _safe_rollback()
    msg, status, log_it = classify_exception(e)
    if log_it: app.logger.exception("Unhandled error")
    if is_api: return jsonify({"error": msg}), status
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

class EvaluationForm(db.Model):
    __tablename__ = 'evaluation_forms'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, nullable=True)
    form_category = db.Column(db.String(100), nullable=False, default="Community Initiative")
    department = db.Column(db.String(50), nullable=False, default="ALL")
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
    confidence = db.Column(db.Float, nullable=False)
    aspect_breakdown = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(50), nullable=False, default="Portal") # Portal, CSV, Testing
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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
    "negative": ["bad", "worst", "hard", "useless", "hot", "slow", "late", "boring", "sabaw", "lutang", "panget", "mahirap", "hirap", "mainit", "init", "magulo", "gulo", "mabilis", "confusing", "fast", "sungit", "masungit", "kupal", "bagsak", "tamad", "bastos", "walang kwenta"],
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
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'DCI';",
            "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS section_target VARCHAR(50) DEFAULT 'ALL';",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'Portal';"
        ]
        for q in alter_queries:
            try:
                db.session.execute(text(q))
                db.session.commit()
            except Exception:
                db.session.rollback()
        seed_database()

@app.cli.command("init-db")
def init_db_command():
    setup_database()
    print("Database Initialized successfully.")

# =========================================================
# NLP PIPELINE & ABSA CONFIGURATION (THREAD-SAFE)
# =========================================================
ROBERTA_MODEL_IDENTIFIER = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
_init_lock = threading.Lock()
_clf = None
_clf_retry_after = 0.0

def get_classifier():
    global _clf, _clf_retry_after
    if _clf is None:
        if time.time() < _clf_retry_after: raise ModelUnavailable("Model load failed recently; retrying shortly.")
        with _init_lock:
            if _clf is None:
                try: _clf = pipeline("sentiment-analysis", model=ROBERTA_MODEL_IDENTIFIER, model_kwargs={"local_files_only": True})
                except Exception:
                    try: _clf = pipeline("sentiment-analysis", model=ROBERTA_MODEL_IDENTIFIER)
                    except Exception as load_err:
                        _clf_retry_after = time.time() + 60
                        raise ModelUnavailable(str(load_err))
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
    if not user.verification_hash or user.verification_attempts >= 5 or datetime.utcnow() > user.verification_expires: return False
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
        department = request.form.get('department', 'DCI').strip().upper()
        selected_role = request.form.get('role', 'Student - Regular').strip()
        cleaned_programs = [p.strip() for p in request.form.getlist('program') if p.strip()]

        if not username or not email or not password: return render_template('auth.html', error="All fields are required.", mode="signup")
        if len(username) > 150 or len(email) > 180 or len(department) > 50 or len(selected_role) > 50 or len(password) > 128:
            return render_template('auth.html', error="One of the fields is too long.", mode="signup")
        if not (email.endswith('@ccc.edu.ph') or email.endswith('@gmail.com')):
            return render_template('auth.html', error="Use your official institutional email.", mode="signup")
        if department == "MISD" or selected_role == "MISD":
            return render_template('auth.html', error="MISD Admin accounts must be securely provisioned by the server.", mode="signup")

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            if not existing_user.is_verified:
                session['pending_verification_email'] = existing_user.email
                flash("An uncompleted registration exists. Enter your new verification code below.")
                code = issue_otp(existing_user)
                db.session.commit()
                _mail_pool.submit(send_verification_email, existing_user.email, code, existing_user.username)
                return render_template('auth.html', mode="verify", email=existing_user.email, dev_code=None)
            err = "Username taken." if existing_user.username == username else "Email already registered."
            return render_template('auth.html', error=err, mode="signup")

        assigned_program_str = ", ".join(cleaned_programs) if cleaned_programs else "General"
        new_user = User(username=username, email=email, department=department, program=assigned_program_str, role=selected_role, is_verified=False)
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

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def login():
    if current_user.is_authenticated: return redirect(url_for('student_portal') if current_user.role.startswith("Student") else url_for('dashboard'))

    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        user = User.query.filter((User.username == login_id) | (User.email == login_id.lower())).first()

        if user and user.check_password(request.form.get('password', '')):
            if not user.is_verified:
                session['pending_verification_email'] = user.email
                flash("Account unverified. Confirm your 6-digit email code.")
                code = issue_otp(user); db.session.commit()
                _mail_pool.submit(send_verification_email, user.email, code, user.username)
                print(f"[DEVELOPER NOTICE] Secure OTP for {user.email}: {code}")
                return render_template('auth.html', mode="verify", email=user.email, dev_code=None)

            session.clear(); login_user(user)

            try:
                db.session.add(UserLoginLog(user_id=user.id, username=user.username, role=user.role, department=user.department, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent', '')[:250]))
                db.session.commit()
            except Exception as e:
                db.session.rollback(); app.logger.warning(f"Failed to log login: {e}")

            return redirect(url_for('student_portal') if user.role.startswith("Student") else url_for('dashboard'))

        return render_template('auth.html', error="Invalid credentials provided.", mode="login")
    return render_template('auth.html', mode="login")

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user(); session.clear()
    resp = redirect(url_for('login'))
    resp.headers["Clear-Site-Data"] = '"cache"'
    return resp

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
    return render_template('student_portal.html', username=current_user.username, role=current_user.role, department=current_user.department, program=current_user.program or "General", available_years=available_years)

@app.route('/api/community_pulse', methods=['GET'])
@login_required
@api_guard
def get_community_pulse():
    user_dept = current_user.department
    q = Feedback.query if current_user.role == 'MISD' else Feedback.query.filter(Feedback.department.in_([user_dept, 'ALL']))
    by_sent = dict(q.with_entities(func.lower(Feedback.sentiment), func.count()).group_by(func.lower(Feedback.sentiment)).all())
    
    pos = by_sent.get('positive', 0); neg = by_sent.get('negative', 0); neu = by_sent.get('neutral', 0)
    total_voices = pos + neg + neu
    pos_pct = round((pos / total_voices) * 100, 1) if total_voices > 0 else 0
    neg_pct = round((neg / total_voices) * 100, 1) if total_voices > 0 else 0
    neu_pct = round((neu / total_voices) * 100, 1) if total_voices > 0 else 0

    return jsonify({"total_voices": total_voices, "positive_count": pos, "negative_count": neg, "neutral_count": neu, "positive_percent": pos_pct, "negative_percent": neg_pct, "neutral_percent": neu_pct, "active_initiatives": EvaluationForm.query.filter_by(is_active=True).count(), "department": user_dept})

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
            "content": p.content or "", "image_url": p.image_url, "link_url": p.link_url, "is_edited": bool(p.is_edited),
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
    content = sfield(data, "content", max_len=5000)
    category = sfield(data, "category", "Campus Facilities & Infrastructure", max_len=100)
    target_channel = sfield(data, "target_channel", "ALL", max_len=50).upper()
    is_announcement = bool(data.get("is_announcement", False))
    if not content or len(content) < 4: return jsonify({"error": "Post must be at least 4 characters long."}), 400

    is_authorized = any(k in (current_user.role or "").lower() for k in ['officer', 'representative', 'rep', 'faculty', 'misd'])
    if is_announcement or target_channel == 'ANNOUNCEMENTS':
        if not is_authorized: return jsonify({"error": "Permission Denied: Only Officers, Reps, and Faculty can broadcast."}), 403
        is_announcement = True

    cleaned, sentiment, score, breakdown = run_absa_pipeline(content, get_active_lexicon())

    post = CommunityPost(
        author_id=current_user.id, author_name=current_user.username if is_announcement else None,
        target_channel=target_channel, author_department=current_user.department,
        author_role=current_user.role, is_announcement=is_announcement,
        program=(current_user.program or "General")[:150], category=category, content=content,
        image_url=clean_url(data.get("image_url"), allow_data_image=True), link_url=clean_url(data.get("link_url")), sentiment=sentiment,
        confidence=score, aspect_breakdown=json.dumps(breakdown), score=1, status="Open"
    )
    db.session.add(post); db.session.flush()
    db.session.add(CommunityPostVote(post_id=post.id, user_id=current_user.id, vote_type=1))

    db.session.add(Feedback(
        form_id=None, department=target_channel if target_channel not in ["ALL", "ANNOUNCEMENTS"] else current_user.department,
        program=(current_user.program or "General")[:150], academic_year="2026-2027", semester="1st Semester",
        raw_text=content, cleaned_text=cleaned, sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(breakdown), source="Portal"
    ))
    db.session.commit()
    return jsonify({"success": True, "message": "Voice or announcement posted successfully."})

@app.route('/api/community_post/<int:post_id>/edit', methods=['POST'])
@login_required
@api_guard
def edit_community_post(post_id):
    post = CommunityPost.query.get(post_id)
    if not post: return jsonify({"error": "Post not found."}), 404
    if post.author_id != current_user.id and current_user.role != 'MISD': return jsonify({"error": "Unauthorized to edit this post."}), 403

    data = json_body()
    new_content = sfield(data, "content", max_len=5000)
    if not new_content or len(new_content) < 4: return jsonify({"error": "Content must be at least 4 characters long."}), 400

    cleaned, sentiment, score, breakdown = run_absa_pipeline(new_content, get_active_lexicon())

    post.content = new_content; post.category = sfield(data, "category", post.category, max_len=100) or post.category
    post.image_url = clean_url(data.get("image_url"), allow_data_image=True); post.link_url = clean_url(data.get("link_url"))
    post.sentiment = sentiment; post.confidence = score; post.aspect_breakdown = json.dumps(breakdown)
    post.is_edited = True; post.edited_at = datetime.utcnow()

    db.session.commit()
    return jsonify({"success": True, "message": "Post updated successfully."})

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
        content = sfield(json_body(), "content", max_len=2000)
        if not content or len(content) < 2: return jsonify({"error": "Comment too short."}), 400
        db.session.add(CommunityComment(post_id=post.id, author_department=current_user.department, author_role=current_user.role, content=content))
        db.session.commit()
        return jsonify({"success": True})

    comments = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).all()
    return jsonify([{"id": c.id, "author_department": c.author_department, "content": c.content, "created_at": c.created_at.strftime("%b %d, %Y • %I:%M %p")} for c in comments])

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
    query = EvaluationForm.query.filter_by(is_active=True)
    if current_user.role not in ["MISD", "Faculty"]: query = query.filter((EvaluationForm.department == 'ALL') | (EvaluationForm.department == current_user.department))

    forms = query.order_by(EvaluationForm.id.desc()).all()
    form_ids = [f.id for f in forms]
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
            "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else ""
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
        department=current_user.department if current_user.role != 'MISD' else (sfield(data, "department", "ALL", max_len=50).upper() or "ALL"),
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

    lexicon = get_active_lexicon()
    for ans in answers:
        comment_text = text_of(ans.get("narrative_text")) or text_of(ans.get("answer"))
        if not comment_text and ans.get("type") in ["narrative", "text"]: comment_text = text_of(ans.get("value"))
        comment_text = comment_text[:5000]
        if not comment_text or len(comment_text) < 3: continue

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment_text, lexicon)
        db.session.add(Feedback(
            form_id=form.id, department=form.department if form.department != "ALL" else current_user.department,
            program=form.program if form.program != "ALL" else (current_user.program or "General")[:150],
            academic_year=form.academic_year, semester=form.semester, raw_text=comment_text,
            cleaned_text=cleaned, sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(breakdown), source="Portal"
        ))

    db.session.add(FormAnonymousSubmission(form_id=form.id, answers_json=json.dumps(answers)))
    db.session.add(FormResponseRecord(form_id=form.id, student_id=current_user.id))
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/forms/my_forms', methods=['GET'])
@login_required
@api_guard
def my_forms_api():
    forms = EvaluationForm.query.filter_by(created_by_id=current_user.id).order_by(EvaluationForm.id.desc()).all()
    return jsonify([{ "id": f.id, "title": f.title, "form_category": f.form_category, "subject_code": f.subject_code or "N/A", "section_target": f.section_target or "ALL", "academic_year": f.academic_year, "semester": f.semester, "response_count": FormAnonymousSubmission.query.filter_by(form_id=f.id).count(), "max_responses": f.max_responses or 0, "deadline_date": f.deadline_date, "is_active": f.is_active, "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else "" } for f in forms])

@app.route('/api/forms/<int:form_id>/analytics', methods=['GET'])
@login_required
@api_guard
def get_form_analytics(form_id):
    form = EvaluationForm.query.get(form_id)
    if not form or (form.created_by_id != current_user.id and current_user.role != 'MISD'): return jsonify({"error": "Unauthorized."}), 403

    subs = FormAnonymousSubmission.query.filter_by(form_id=form.id).all()
    try: questions = json.loads(form.questions_json)
    except: questions = []

    q_stats = {str(q.get("id")): {"id": q.get("id"), "prompt": q.get("prompt"), "type": q.get("type", "narrative"), "total_answers": 0, "likert_sum": 0, "likert_counts": {1:0,2:0,3:0,4:0,5:0}, "choice_counts": {}, "narratives": []} for q in questions}

    for sub in subs:
        try:
            for ans in json.loads(sub.answers_json):
                qid = str(ans.get("question_id"))
                if qid in q_stats:
                    s = q_stats[qid]; s["total_answers"] += 1
                    val = ans.get("value"); score = ans.get("score")
                    if s["type"] == "likert":
                        try:
                            n = int(score if score is not None else val)
                            if 1 <= n <= 5: s["likert_sum"] += n; s["likert_counts"][n] += 1
                        except: pass
                        if ans.get("narrative_text"): s["narratives"].append(ans.get("narrative_text"))
                    elif s["type"] in ["radio", "single_choice"] and val:
                        s["choice_counts"][str(val).strip()] = s["choice_counts"].get(str(val).strip(), 0) + 1
                    elif s["type"] in ["checkbox", "multiple_choice"] and isinstance(val, list):
                        for item in val:
                            if str(item).strip(): s["choice_counts"][str(item).strip()] = s["choice_counts"].get(str(item).strip(), 0) + 1
                    else:
                        n_val = ans.get("answer") or val or ans.get("narrative_text")
                        if n_val: s["narratives"].append(str(n_val))
        except: pass

    for s in q_stats.values():
        if s["type"] == "likert": s["average_rating"] = round(s["likert_sum"] / s["total_answers"], 2) if s["total_answers"] > 0 else 0

    return jsonify({ "form_id": form.id, "title": form.title, "section_target": form.section_target or "ALL", "subject_code": form.subject_code or "N/A", "total_responses": len(subs), "questions_analytics": list(q_stats.values()) })

@app.route('/api/forms/<int:form_id>/export_csv', methods=['GET'])
@login_required
@api_guard
def export_form_csv(form_id):
    form = EvaluationForm.query.get(form_id)
    if not form or (form.created_by_id != current_user.id and current_user.role != 'MISD'): return "Unauthorized", 403

    try: questions = json.loads(form.questions_json)
    except: questions = []
    submissions = FormAnonymousSubmission.query.filter_by(form_id=form.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = ["Submission ID"] 
    for q in questions:
        headers.append(f"Q{q.get('id')}: {q.get('prompt')}")
        if q.get("type") == "likert" and (q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]):
            headers.append(f"Q{q.get('id')} Elaboration")
    writer.writerow(headers)

    for sub in submissions:
        row = [sub.id]
        ans_map = {}
        try:
            for it in json.loads(sub.answers_json): ans_map[str(it.get("question_id"))] = it
        except: pass

        for q in questions:
            entry = ans_map.get(str(q.get("id")), {})
            val = entry.get("value")
            if val is None: val = entry.get("score") or entry.get("answer")
            if isinstance(val, list): val = "; ".join(str(v) for v in val)
            row.append(csv_safe(val))

            if q.get("type") == "likert" and (q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]):
                row.append(csv_safe(entry.get("narrative_text", "")))
        writer.writerow(row)

    safe_title = re.sub(r'[^\w\-_\.]', '_', form.title)[:25]
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=survey_export_{form.id}_{safe_title}.csv"})

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

# ==========================================
# DASHBOARD & ANALYTICS API
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role.startswith("Student"): return redirect(url_for('student_portal'))
    return render_template('dashboard.html', username=current_user.username, role=current_user.role, user_dept=current_user.department, user_program=current_user.program)

@app.route('/api/analytics', methods=['GET'])
@login_required
@api_guard
def get_analytics():
    requested_dept = request.args.get('department', 'ALL').strip().upper()
    selected_year = request.args.get('year', 'ALL').strip()
    selected_sem = request.args.get('semester', 'ALL').strip()
    search_query = request.args.get('search', '').strip()[:100]
    theme = "light" if request.args.get('theme') == "light" else "dark"
    page = request.args.get('page', 1, type=int)
    per_page = min(max(request.args.get('per_page', 10, type=int), 1), 100)
    source_filter = request.args.get('source', 'Portal').strip()

    effective_dept = current_user.department if current_user.role != "MISD" else requested_dept

    query = Feedback.query
    if effective_dept != 'ALL': query = query.filter_by(department=effective_dept)
    if selected_year != 'ALL': query = query.filter_by(academic_year=selected_year)
    if selected_sem != 'ALL': query = query.filter_by(semester=selected_sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)
    if search_query: query = query.filter((Feedback.raw_text.ilike(f"%{search_query}%")) | (Feedback.program.ilike(f"%{search_query}%")))

    all_matching = query.all()
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

    paged_records = query.order_by(Feedback.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    recent_logs = []
    for entry in paged_records:
        try: parsed = json.loads(entry.aspect_breakdown)
        except: parsed = []
        
        # Check for sarcasm markers across new and existing records
        has_sarcasm = any(
            item.get("has_sarcasm", False) or
            any(t.get("role") == "Sarcasm Invalidator" for t in item.get("token_scores", [])) or
            "sarcasm" in str(item.get("explanation", "")).lower()
            for item in parsed
        )

        recent_logs.append({
            "id": entry.id, "form_id": entry.form_id, "department": entry.department,
            "program": entry.program or "General", "academic_year": entry.academic_year or "2026-2027",
            "semester": entry.semester or "1st Semester", "raw_text": entry.raw_text,
            "sentiment": entry.sentiment, "confidence": entry.confidence, "aspects": parsed,
            "has_sarcasm": has_sarcasm,
            "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M") if entry.timestamp else ""
        })

    return jsonify({
        "department": effective_dept, "year": selected_year, "semester": selected_sem,
        "available_years": [y.year for y in AcademicYear.query.order_by(AcademicYear.year.desc()).all()],
        "kpis": {"total": total_items, "pos": pos, "neg": neg, "neu": neu},
        "pie_chart": generate_matplotlib_pie(pos, neg, neu, theme),
        "aspect_chart": generate_matplotlib_bar(aspect_counts, theme),
        "insights": compute_prescriptive_insights(all_matching),
        "logs": recent_logs,
        "pagination": {"page": page, "per_page": per_page, "total_items": total_items, "total_pages": total_pages}
    })

@app.route('/api/analytics/keywords', methods=['GET'])
@login_required
@api_guard
def get_analytics_keywords():
    dept = current_user.department if current_user.role != "MISD" else request.args.get('department', 'ALL').strip().upper()
    yr = request.args.get('year', 'ALL').strip()
    sem = request.args.get('semester', 'ALL').strip()
    source_filter = request.args.get('source', 'Portal').strip()

    query = Feedback.query
    if dept != 'ALL': query = query.filter_by(department=dept)
    if yr != 'ALL': query = query.filter_by(academic_year=yr)
    if sem != 'ALL': query = query.filter_by(semester=sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)

    stop_words = {"ang", "mga", "ng", "sa", "na", "ay", "at", "ito", "pa", "ko", "mo", "nya", "ni", "pero", "kaso", "din", "rin", "ba", "lang", "naman", "ka", "kaya", "kasi", "mismo", "the", "and", "to", "a", "of", "in", "for", "is", "on", "that", "by", "this", "with", "i", "you", "it", "not", "or", "be", "are", "from", "at", "as", "your", "all", "have", "more", "was", "we", "they", "an", "so", "up", "out", "if", "about", "who", "get", "which", "para", "kung", "dahil", "kaming", "kami", "sila", "nila", "namin", "kanila", "aking", "ung", "yung", "nong", "nung", "may", "meron", "lahat", "naging", "mas", "wag", "daw", "raw"}

    word_counts = {}
    for r in query.all():
        for token in re.findall(r'\b[a-z]{3,}\b', f"{r.raw_text} {r.cleaned_text}".lower()):
            if token not in stop_words and not token.isdigit():
                word_counts[token] = word_counts.get(token, 0) + 1

    return jsonify({"department": dept, "keywords": [{"word": w[0], "count": w[1]} for w in sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:30]]})

# ==========================================
# PRE-FLIGHT AI SENTIMENT INSPECTION
# ==========================================
@app.route('/api/inspect_preview', methods=['POST'])
@login_required
@api_guard
def inspect_preview():
    comment = sfield(json_body(), "comment", max_len=5000)
    if not comment: return jsonify({"error": "No text provided."}), 400
    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, get_active_lexicon())
    has_sarcasm = any(item.get("has_sarcasm", False) for item in breakdown)
    return jsonify({
        "raw": comment, 
        "cleaned": cleaned, 
        "sentiment": sentiment, 
        "confidence_score": score, 
        "aspect_breakdown": breakdown,
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

    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, get_active_lexicon())
    entry = Feedback(
        department=(sfield(data, "department", "DCI", max_len=50).upper() or "DCI"), program=sfield(data, "program", "Institutional Testing", max_len=150) or "Institutional Testing",
        academic_year=sfield(data, "academic_year", "2026-2027", max_len=20) or "2026-2027", semester=sfield(data, "semester", "1st Semester", max_len=30) or "1st Semester",
        raw_text=comment, cleaned_text=cleaned, sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(breakdown), source="Testing"
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/upload_csv', methods=['POST'])
@login_required
@api_guard
def upload_csv():
    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403
    if 'file' not in request.files: return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    if not (file.filename or '').lower().endswith('.csv'): return jsonify({"error": "Must be a valid .csv file."}), 400

    raw_bytes = file.stream.read(2 * 1024 * 1024 + 1)
    if len(raw_bytes) > 2 * 1024 * 1024:
        return jsonify({"error": "CSV file is too large. Max allowed is 2MB."}), 413

    stream = io.StringIO(raw_bytes.decode("utf-8-sig", errors="ignore"))
    reader = csv.DictReader(stream)
    if not reader.fieldnames: return jsonify({"error": "Invalid CSV header."}), 400

    text_col = next((c for c in reader.fieldnames if any(k in c.lower() for k in ["comment", "feedback", "narrative", "text", "review"])), reader.fieldnames[0])
    dept_col = next((c for c in reader.fieldnames if any(k in c.lower() for k in ["dept", "department", "college"])), None)
    prog_col = next((c for c in reader.fieldnames if any(k in c.lower() for k in ["prog", "program", "course"])), None)
    year_col = next((c for c in reader.fieldnames if any(k in c.lower() for k in ["year", "ay", "acad"])), None)
    sem_col = next((c for c in reader.fieldnames if any(k in c.lower() for k in ["sem", "semester"])), None)

    lex = get_active_lexicon()
    processed = 0
    max_rows = 500

    def _cell(row, col, form_key, default, limit, upper=False):
        val = (row.get(col) if col else None) or request.form.get(form_key, default) or default
        val = str(val).strip()[:limit]
        return val.upper() if upper else val

    for idx, row in enumerate(reader):
        if idx >= max_rows: break
        comment = (row.get(text_col) or '').strip()[:5000]
        if not comment: continue

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lex)
        db.session.add(Feedback(
            department=_cell(row, dept_col, 'department', 'DCI', 50, upper=True),
            program=_cell(row, prog_col, 'program', 'General', 150),
            academic_year=_cell(row, year_col, 'academic_year', '2026-2027', 20),
            semester=_cell(row, sem_col, 'semester', '1st Semester', 30),
            raw_text=comment, cleaned_text=cleaned, sentiment=sentiment, confidence=score, aspect_breakdown=json.dumps(breakdown), source="CSV"
        ))
        processed += 1

    db.session.commit()
    return jsonify({"success": True, "processed": processed})

@app.route('/api/export_csv', methods=['GET'])
@login_required
@api_guard
def export_csv():
    dept = current_user.department if current_user.role != "MISD" else request.args.get('department', 'ALL').strip().upper()
    yr = request.args.get('year', 'ALL').strip()
    sem = request.args.get('semester', 'ALL').strip()
    source_filter = request.args.get('source', 'Portal').strip()

    query = Feedback.query
    if dept != 'ALL': query = query.filter_by(department=dept)
    if yr != 'ALL': query = query.filter_by(academic_year=yr)
    if sem != 'ALL': query = query.filter_by(semester=sem)
    if source_filter != 'ALL': query = query.filter_by(source=source_filter)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Academic Year", "Semester", "Department", "Program", "Data Source", "Raw Feedback", "Sentiment", "Confidence", "Timestamp"])

    for r in query.order_by(Feedback.id.asc()).all():
        writer.writerow([r.id, csv_safe(r.academic_year), csv_safe(r.semester), csv_safe(r.department), csv_safe(r.program), csv_safe(r.source), csv_safe(r.raw_text), r.sentiment, r.confidence, r.timestamp])

    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename=ccc_sentiment_export_{safe_filename(dept.lower())}_{safe_filename(yr)}_{safe_filename(sem)}.csv"})

@app.route('/api/lexicon', methods=['GET', 'POST', 'DELETE'])
@login_required
@api_guard
def manage_lexicon():
    if request.method == 'GET':
        return jsonify([{"id": t.id, "word": t.word, "category": t.category} for t in LexiconTerm.query.order_by(LexiconTerm.id.desc()).all()])

    if current_user.role != "MISD": return jsonify({"error": "Unauthorized."}), 403

    if request.method == 'POST':
        data = json_body()
        word, cat = sfield(data, 'word', max_len=100).lower(), sfield(data, 'category', max_len=50).lower()
        if not word or cat not in ['positive', 'negative', 'intensifiers', 'negations']: return jsonify({"error": "Invalid input."}), 400
        if LexiconTerm.query.filter_by(word=word).first(): return jsonify({"error": "Already exists."}), 400
        db.session.add(LexiconTerm(word=word, category=cat))
        db.session.commit()
        return jsonify({"success": True})

    term = LexiconTerm.query.get(ifield(json_body(), 'id'))
    if not term: return jsonify({"error": "Not found."}), 404
    db.session.delete(term)
    db.session.commit()
    return jsonify({"success": True})

if __name__ == '__main__':
    setup_database()
    app.run(debug=False, port=5000)