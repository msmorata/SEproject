import os
import re
import csv
import io
import json
import math
import base64
import random
import smtplib
from email.message import EmailMessage
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from transformers import pipeline

# Headless thread-safe Matplotlib configuration
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

app = Flask(__name__)
app.secret_key = "ccc_sentiment_secret_key_2026"

# ==========================================
# POSTGRESQL DATABASE CONFIGURATION
# ==========================================
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:admin@localhost:5432/ccc_sentiment'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# LIVE SMTP GMAIL DISPATCH CONFIGURATION
# ==========================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
MAIL_SENDER = "sentimentanalysissystem@gmail.com"
MAIL_PASSWORD = "hasvxaybrhbfphxv"

def send_verification_email(recipient_email, code, username):
    try:
        msg = EmailMessage()
        msg['Subject'] = "City College of Calamba — Community Portal Passcode"
        msg['From'] = f"CCC Community Feedback Collective <{MAIL_SENDER}>"
        msg['To'] = recipient_email

        msg.set_content(f"""
Good day {username},

Your 6-digit confirmation passcode for the CCC Participatory Student Collective is:

{code}

Enter this code on the activation screen to verify your institutional membership.

Best regards,
City College of Calamba Academic Community
        """)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #070d1d; color: #f8fafc; padding: 30px; margin: 0;">
            <div style="max-width: 500px; margin: 0 auto; background: #0f1a30; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 28px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                <h2 style="color: #60a5fa; margin: 0 0 6px 0; font-size: 20px;">City College of Calamba</h2>
                <p style="color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 20px 0;">Participatory Student Feedback Collective</p>
                <div style="border-top: 1px solid rgba(255,255,255,0.08); margin: 18px 0;"></div>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left; line-height: 1.5;">Hello <strong>{username}</strong>,</p>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left; line-height: 1.5;">Welcome to the student community voice collective. Use your 6-digit code below to activate your account:</p>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #fbbf24; background: #070d1d; border: 1.5px dashed rgba(245, 158, 11, 0.6); padding: 14px; border-radius: 10px; margin: 24px 0;">
                    {code}
                </div>
                <p style="color: #94a3b8; font-size: 12px; text-align: left; line-height: 1.5;">This passcode confirms your institutional identity. Do not share this code.</p>
                <div style="border-top: 1px solid rgba(255,255,255,0.08); margin: 20px 0;"></div>
                <p style="color: #64748b; font-size: 11px; margin: 0;">Student Representation &bull; Community-Based Academic Quality Assurance</p>
            </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype='html')

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=3) as server:
            server.starttls()
            server.login(MAIL_SENDER, MAIL_PASSWORD)
            server.send_message(msg)

        print(f"[+] Verification email sent to: {recipient_email}")
        return True
    except Exception as e:
        print(f"[-] SMTP Delivery Notice (Fast Fallback): {e}")
        return False

# ==========================================
# BROWSER BACK-BUTTON & CACHE LOCKOUT
# ==========================================
@app.after_request
def apply_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, post-check=0, pre-check=0, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"
    return response

# ==========================================
# AUTHENTICATION & DATA MODELS
# ==========================================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="Student - Regular")
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.Text, nullable=True)
    verification_code = db.Column(db.String(6), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    academic_year = db.Column(db.String(20), nullable=False, default="2025-2026")
    semester = db.Column(db.String(30), nullable=False, default="1st Semester")
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by_name = db.Column(db.String(150), nullable=False)
    created_by_role = db.Column(db.String(50), nullable=False)
    questions_json = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FormResponseRecord(db.Model):
    __tablename__ = 'form_response_records'
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('evaluation_forms.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class FormAnonymousSubmission(db.Model):
    __tablename__ = 'form_anonymous_submissions'
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('evaluation_forms.id', ondelete='CASCADE'), nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class Feedback(db.Model):
    __tablename__ = 'feedback_records'
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, nullable=True)
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.String(150), nullable=True, default="General")
    academic_year = db.Column(db.String(20), nullable=False, default="2025-2026")
    semester = db.Column(db.String(30), nullable=False, default="1st Semester")
    raw_text = db.Column(db.Text, nullable=False)
    cleaned_text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    aspect_breakdown = db.Column(db.Text, nullable=False)
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
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    vote_type = db.Column(db.Integer, nullable=False, default=1)

class CommunityResolutionVote(db.Model):
    __tablename__ = 'community_resolution_votes'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reaction_type = db.Column(db.Integer, nullable=False)

class CommunityComment(db.Model):
    __tablename__ = 'community_comments'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id', ondelete='CASCADE'), nullable=False)
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
    return User.query.get(int(user_id))

DEFAULT_LEXICON = {
    "positive": [
        "good", "great", "best", "clear", "helpful", "perfect", "nice", "solid", "goods",
        "mabait", "bait", "maayos", "ayos", "magaling", "galing", "sulit", "malinaw", "linaw",
        "approachable", "easy", "petiks", "chill", "husay", "mahusay", "sipag", "masipag", "ganda"
    ],
    "negative": [
        "bad", "worst", "hard", "useless", "hot", "slow", "late", "boring", "sabaw", "lutang",
        "panget", "mahirap", "hirap", "mainit", "init", "magulo", "gulo", "mabilis", "confusing",
        "fast", "sungit", "masungit", "kupal", "bagsak", "tamad", "bastos", "walang kwenta"
    ],
    "intensifiers": [
        "sobrang", "sobra", "masyado", "very", "super", "really", "so", "grabe", "napaka",
        "ubod", "saksakan", "talaga", "tunay", "lubos"
    ],
    "negations": [
        "not", "hindi", "di", "never", "wala", "eme", "charot", "charing", "joke"
    ]
}

def seed_database():
    for cat, words in DEFAULT_LEXICON.items():
        for w in words:
            if not LexiconTerm.query.filter_by(word=w.lower()).first():
                db.session.add(LexiconTerm(word=w.lower(), category=cat))

    default_years = ["2024-2025", "2025-2026", "2026-2027"]
    for yr in default_years:
        if not AcademicYear.query.filter_by(year=yr).first():
            db.session.add(AcademicYear(year=yr))

    db.session.commit()

# =========================================================
# SAFE ISOLATED SCHEMA SYNCHRONIZATION
# =========================================================
with app.app_context():
    db.create_all()

    alter_queries = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(180);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'Student - Regular';",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'DCI';",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS program TEXT;",
        "ALTER TABLE users ALTER COLUMN program TYPE TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(6);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS form_id INTEGER;",
        "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'DCI';",
        "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS program VARCHAR(150) DEFAULT 'General';",
        "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS academic_year VARCHAR(20) DEFAULT '2025-2026';",
        "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS semester VARCHAR(30) DEFAULT '1st Semester';",
        "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS subject_code VARCHAR(50);",
        "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS section_target VARCHAR(50) DEFAULT 'ALL';",
        "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS deadline_date VARCHAR(50);",
        "ALTER TABLE evaluation_forms ADD COLUMN IF NOT EXISTS max_responses INTEGER DEFAULT 0;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS author_id INTEGER;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS author_name VARCHAR(150);",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS image_url TEXT;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS link_url TEXT;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS is_edited BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS target_channel VARCHAR(50) DEFAULT 'ALL';",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS author_department VARCHAR(50) DEFAULT 'DCI';",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS author_role VARCHAR(100) DEFAULT 'Student - Regular';",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS is_announcement BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS score INTEGER DEFAULT 1;",
        "ALTER TABLE community_post_votes ADD COLUMN IF NOT EXISTS vote_type INTEGER DEFAULT 1;"
    ]

    for q in alter_queries:
        try:
            db.session.execute(text(q))
            db.session.commit()
        except Exception:
            db.session.rollback()

    seed_database()

# =========================================================
# NLP PIPELINE & ABSA CONFIGURATION (MULTILINGUAL ROBERTA)
# =========================================================
ROBERTA_MODEL_IDENTIFIER = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
print(f"Initializing RoBERTa Sentiment Engine ({ROBERTA_MODEL_IDENTIFIER})...")

try:
    classifier = pipeline(
        "sentiment-analysis",
        model=ROBERTA_MODEL_IDENTIFIER,
        model_kwargs={"local_files_only": True}
    )
    print("RoBERTa weights loaded directly from local cache.")
except Exception:
    try:
        classifier = pipeline("sentiment-analysis", model=ROBERTA_MODEL_IDENTIFIER)
        print("RoBERTa weights downloaded and cached successfully.")
    except Exception as e:
        print(f"Fallback pipeline: {e}")
        classifier = pipeline("sentiment-analysis")

ASPECT_CATEGORIES = {
    "Instructional Delivery & Pedagogy": [
        "lecture", "turo", "explain", "speak", "speaks", "discussion",
        "mabilis", "fast", "slow", "teaching", "lesson", "clear", "malinaw", "linaw",
        "confusing", "exam", "quiz", "task", "activity", "galing", "magaling"
    ],
    "Faculty Demeanor & Approachability": [
        "talk", "approachable", "mabait", "bait", "attitude", "sungit", "masungit",
        "easy", "friendly", "accommodating", "strict", "patient", "galit", "snob",
        "ugali", "pakikitungo", "demeanor", "prof", "maam", "sir"
    ],
    "Campus Facilities & Infrastructure": [
        "room", "classroom", "fan", "electric fan", "aircon", "mainit", "init",
        "hot", "computer", "wifi", "internet", "projector", "lab", "laboratory", "chair", "upuan"
    ]
}

def get_active_lexicon():
    terms = LexiconTerm.query.all()
    lex = {"positive": set(), "negative": set(), "intensifiers": set(), "negations": set()}
    for t in terms:
        if t.category in lex:
            lex[t.category].add(t.word.lower())
    return lex

def preprocess_taglish_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'[^\w\s,\.\-!?]', '', text)
    return text.strip()

def segment_compound_text(text):
    delimiters = r"(?<=[.!?])\s+|\b(?:but|pero|kaso|kaso lang|however|although|while|yet)\b"
    clauses = re.split(delimiters, text, flags=re.IGNORECASE)
    cleaned = [c.strip() for c in clauses if len(c.strip()) > 2]
    return cleaned if cleaned else [text]

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
    roberta_result = classifier(clause[:512])[0]
    raw_label = str(roberta_result['label']).strip().lower()
    roberta_score = round(roberta_result['score'], 4)

    if "pos" in raw_label or raw_label == "label_2":
        roberta_polarity = "Positive"
    elif "neg" in raw_label or raw_label == "label_0":
        roberta_polarity = "Negative"
    elif "star" in raw_label:
        stars = int(raw_label[0])
        roberta_polarity = "Positive" if stars >= 4 else "Neutral" if stars == 3 else "Negative"
    else:
        roberta_polarity = "Neutral"

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
            pending_negation = False
            pending_intensifier = 1.0
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
            pending_negation = False
            pending_intensifier = 1.0
        else:
            token_info["base_score"] = 0
            token_info["final_score"] = 0.0
            token_info["role"] = "Neutral (0)"

        token_scores.append(token_info)

    has_sarcasm = bool(set(words) & sarcasm_markers)

    if has_sarcasm:
        polarity = "Negative"
        explanation = f"RoBERTa: {roberta_score}. Slang sarcasm invalidator ('eme/charot') triggered."
    elif net_lexical_score > 0:
        polarity = "Positive"
        explanation = f"RoBERTa: {roberta_score}. Lexical score (+{round(net_lexical_score, 2)}) confirmed Positive sentiment."
    elif net_lexical_score < 0:
        polarity = "Negative"
        explanation = f"RoBERTa: {roberta_score}. Lexical score ({round(net_lexical_score, 2)}) confirmed Negative sentiment."
    else:
        polarity = roberta_polarity
        explanation = f"RoBERTa Confidence: {roberta_score}. Neutral lexical baseline."

    return polarity, roberta_score, explanation, token_scores, round(net_lexical_score, 2)

def run_absa_pipeline(raw_comment, lexicon=None):
    if lexicon is None:
        lexicon = get_active_lexicon()
    cleaned = preprocess_taglish_text(raw_comment)
    clauses = segment_compound_text(cleaned)
    breakdown = []
    polarities = []

    for clause in clauses:
        aspect = detect_aspect(clause)
        polarity, score, explanation, token_scores, lexical_score = evaluate_clause(clause, lexicon)
        polarities.append(polarity)
        breakdown.append({
            "aspect": aspect,
            "clause": clause,
            "polarity": polarity,
            "score": score,
            "lexical_score": lexical_score,
            "token_scores": token_scores,
            "explanation": explanation
        })

    pos_count = polarities.count("Positive")
    neg_count = polarities.count("Negative")
    if pos_count > neg_count:
        overall = "Positive"
    elif neg_count > pos_count:
        overall = "Negative"
    else:
        overall = "Neutral"

    avg_confidence = round(sum(item["score"] for item in breakdown) / len(breakdown), 4)
    return cleaned, overall, avg_confidence, breakdown

# ==========================================
# HIGH-DPI MATPLOTLIB ENGINE
# ==========================================
def generate_matplotlib_pie(pos, neg, neu):
    try:
        fig = Figure(figsize=(3.0, 3.0), dpi=200, facecolor='none')
        FigureCanvas(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor('none')

        total = pos + neg + neu
        if total == 0:
            ax.pie([1], colors=['#1e293b'], wedgeprops={'edgecolor': '#0f1a30', 'linewidth': 2, 'width': 0.42})
            ax.text(0, 0, '0\nVOICES', ha='center', va='center',
                    color='#64748b', fontsize=8.5, fontweight='bold', linespacing=1.2)
        else:
            counts, colors, labels = [], [], []
            if pos > 0: counts.append(pos); colors.append('#10b981'); labels.append(f'{pos}')
            if neg > 0: counts.append(neg); colors.append('#f43f5e'); labels.append(f'{neg}')
            if neu > 0: counts.append(neu); colors.append('#f59e0b'); labels.append(f'{neu}')

            wedges, texts, autotexts = ax.pie(
                counts,
                labels=labels,
                colors=colors,
                autopct='%1.0f%%',
                pctdistance=0.72,
                labeldistance=1.14,
                startangle=135,
                textprops={'color': '#94a3b8', 'fontsize': 8, 'weight': 'bold'},
                wedgeprops={'edgecolor': '#0f1a30', 'linewidth': 2.5, 'width': 0.42}
            )
            for at in autotexts:
                at.set_color('#ffffff')
                at.set_fontsize(7.5)
                at.set_weight('bold')

            ax.text(0, 0, f'{total}\nVOICES', ha='center', va='center',
                    color='#f8fafc', fontsize=9, fontweight='800', linespacing=1.2)

        ax.axis('equal')
        fig.subplots_adjust(left=0.06, right=0.94, top=0.94, bottom=0.06)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', transparent=True, dpi=200)
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Error generating pie chart: {e}")
        return ""

def generate_matplotlib_bar(aspects):
    try:
        fig = Figure(figsize=(3.4, 3.0), dpi=200, facecolor='none')
        FigureCanvas(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor('none')

        categories = ['Pedagogy', 'Demeanor', 'Facilities']
        pos_vals = [
            aspects.get('Instructional Delivery', {}).get('pos', 0),
            aspects.get('Faculty Demeanor', {}).get('pos', 0),
            aspects.get('Facilities', {}).get('pos', 0)
        ]
        neg_vals = [
            aspects.get('Instructional Delivery', {}).get('neg', 0),
            aspects.get('Faculty Demeanor', {}).get('neg', 0),
            aspects.get('Facilities', {}).get('neg', 0)
        ]

        x = [0, 1, 2]
        width = 0.38

        ax.bar(x, pos_vals, width, label='Positive', color='#10b981', zorder=3)
        ax.bar(x, neg_vals, width, bottom=pos_vals, label='Negative', color='#f43f5e', zorder=3)

        ax.set_xticks(x)
        ax.set_xticklabels(categories, color='#94a3b8', fontsize=8, fontweight='600')
        ax.tick_params(axis='y', colors='#64748b', labelsize=7.5, length=0)
        ax.tick_params(axis='x', length=0)

        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(axis='y', color='#334155', linestyle=':', linewidth=0.8, alpha=0.5, zorder=1)

        fig.subplots_adjust(left=0.15, right=0.95, top=0.92, bottom=0.14)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', transparent=True, dpi=200)
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Error generating bar chart: {e}")
        return ""

def compute_prescriptive_insights(records):
    if not records:
        return [{
            "level": "Community Baseline",
            "aspect": "Academic Community Pulse",
            "ratio": 0,
            "recommendation": "Community listening portal active. Awaiting student submissions."
        }]

    aspect_stats = {
        "Instructional Delivery & Pedagogy": {"pos": 0, "neg": 0, "neu": 0},
        "Faculty Demeanor & Approachability": {"pos": 0, "neg": 0, "neu": 0},
        "Campus Facilities & Infrastructure": {"pos": 0, "neg": 0, "neu": 0}
    }

    for r in records:
        try:
            items = json.loads(r.aspect_breakdown)
            for item in items:
                asp = item.get("aspect")
                pol = str(item.get("polarity")).strip().capitalize()
                if asp in aspect_stats and pol in ["Positive", "Negative", "Neutral"]:
                    pol_key = "pos" if pol == "Positive" else "neg" if pol == "Negative" else "neu"
                    aspect_stats[asp][pol_key] += 1
        except Exception:
            continue

    insights = []
    for asp, stats in aspect_stats.items():
        total_mentions = stats["pos"] + stats["neg"] + stats["neu"]
        if total_mentions >= 3:
            neg_ratio = stats["neg"] / total_mentions
            if neg_ratio >= 0.40:
                if asp == "Campus Facilities & Infrastructure":
                    insights.append({
                        "level": "Community Action Alert",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Elevated student concerns regarding campus facilities. Student Council and Class Representatives should submit an actionable report to General Services."
                    })
                elif asp == "Instructional Delivery & Pedagogy":
                    insights.append({
                        "level": "Pedagogical Dialogue Request",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Pacing concerns noted by student body. Department chair is requested to facilitate a faculty-student consultative forum on syllabus pacing."
                    })
                elif asp == "Faculty Demeanor & Approachability":
                    insights.append({
                        "level": "Student Welfare Advisory",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Approachability concerns recorded. Recommend active student-faculty rapport initiatives and established consultation hours."
                    })

    if not insights:
        insights.append({
            "level": "Community Baseline",
            "aspect": "Student Body Sentiment Index",
            "ratio": 0,
            "recommendation": "Student feedback is within positive academic bounds. Collective satisfaction is sustained."
        })
    return insights

# ==========================================
# AUTHENTICATION & REGISTRATION
# ==========================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role.startswith("Student"):
            return redirect(url_for('student_portal'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        if current_user.role.startswith("Student"):
            return redirect(url_for('student_portal'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        department = request.form.get('department', 'DCI').strip().upper()
        selected_role = request.form.get('role', 'Student - Regular').strip()

        programs_list = request.form.getlist('program')
        cleaned_programs = [p.strip() for p in programs_list if p.strip()]

        if not username or not email or not password:
            return render_template('auth.html', error="All fields are required.", mode="signup")

        if not (email.endswith('@ccc.edu.ph') or email.endswith('@gmail.com')):
            return render_template(
                'auth.html',
                error="Access restricted: Register using an official institutional email (@ccc.edu.ph or @gmail.com for testing).",
                mode="signup"
            )

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            if not existing_user.is_verified:
                session['pending_verification_email'] = existing_user.email
                flash("An uncompleted registration exists for this account. Enter your verification code below.")
                return render_template(
                    'auth.html',
                    mode="verify",
                    email=existing_user.email,
                    dev_code=existing_user.verification_code
                )
            if existing_user.username == username:
                return render_template('auth.html', error="Username is already taken.", mode="signup")
            return render_template('auth.html', error="Email address is already registered.", mode="signup")

        code = str(random.randint(100000, 999999))
        role = "MISD" if department == "MISD" else selected_role
        assigned_program_str = ", ".join(cleaned_programs) if (cleaned_programs and department != "MISD") else ("Institutional Oversight" if department == "MISD" else "General")

        new_user = User(
            username=username,
            email=email,
            department=department,
            program=assigned_program_str,
            role=role,
            verification_code=code,
            is_verified=False
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        email_sent = send_verification_email(email, code, username)

        session['pending_verification_email'] = email
        display_code = None if email_sent else code

        return render_template('auth.html', mode="verify", email=email, dev_code=display_code)

    return render_template('auth.html', mode="signup")

@app.route('/resend-code', methods=['POST'])
def resend_code():
    email = request.form.get('email', '').strip().lower() or session.get('pending_verification_email')
    user = User.query.filter_by(email=email).first()

    if not user:
        return render_template('auth.html', error="No pending account found for that email address.", mode="signup")

    if user.is_verified:
        flash("Your account is already verified! Please sign in.")
        return redirect(url_for('login'))

    new_code = str(random.randint(100000, 999999))
    user.verification_code = new_code
    db.session.commit()

    email_sent = send_verification_email(user.email, new_code, user.username)

    display_code = None if email_sent else new_code
    flash("A fresh verification code has been dispatched to your inbox.")
    return render_template('auth.html', mode="verify", email=user.email, dev_code=display_code)

@app.route('/verify-code', methods=['POST'])
def verify_code():
    email = request.form.get('email', '').strip().lower() or session.get('pending_verification_email')
    code = request.form.get('code', '').strip()

    user = User.query.filter_by(email=email).first()
    if not user:
        return render_template('auth.html', error="User record not found.", mode="verify", email=email)

    if user.verification_code == code:
        user.is_verified = True
        user.verification_code = None
        db.session.commit()
        session.pop('pending_verification_email', None)
        flash("Email confirmed successfully! You may now sign in.")
        return redirect(url_for('login'))
    else:
        return render_template('auth.html', error="Invalid 6-digit confirmation code.", mode="verify", email=email, dev_code=user.verification_code)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role.startswith("Student"):
            return redirect(url_for('student_portal'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter((User.username == login_id) | (User.email == login_id.lower())).first()

        if user and user.check_password(password):
            if not user.is_verified:
                session['pending_verification_email'] = user.email
                flash("Account unverified. Confirm your 6-digit email code.")
                return render_template(
                    'auth.html',
                    mode="verify",
                    email=user.email,
                    dev_code=user.verification_code
                )

            login_user(user)

            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip and ',' in client_ip:
                client_ip = client_ip.split(',')[0].strip()
            user_agent = request.headers.get('User-Agent', '')[:250]

            log_entry = UserLoginLog(
                user_id=user.id,
                username=user.username,
                role=user.role,
                department=user.department,
                ip_address=client_ip,
                user_agent=user_agent,
                login_time=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()

            if user.role.startswith("Student"):
                return redirect(url_for('student_portal'))
            return redirect(url_for('dashboard'))

        return render_template('auth.html', error="Invalid credentials provided.", mode="login")

    return render_template('auth.html', mode="login")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('login'))

# =========================================================
# COMMUNITY TOWN HALL APIS
# =========================================================
@app.route('/student-portal')
@login_required
def student_portal():
    available_years = [y.year for y in AcademicYear.query.order_by(AcademicYear.year.asc()).all()]
    return render_template(
        'student_portal.html',
        username=current_user.username,
        role=current_user.role,
        department=current_user.department,
        program=current_user.program or "General",
        available_years=available_years
    )

@app.route('/api/community_pulse', methods=['GET'])
@login_required
def get_community_pulse():
    try:
        user_dept = current_user.department
        all_feedback = Feedback.query.filter(
            (Feedback.department == user_dept) | (Feedback.department == 'ALL')
        ).all() if current_user.role != 'MISD' else Feedback.query.all()

        total_voices = len(all_feedback)
        pos = sum(1 for r in all_feedback if str(r.sentiment).strip().lower() == 'positive')
        neg = sum(1 for r in all_feedback if str(r.sentiment).strip().lower() == 'negative')
        neu = sum(1 for r in all_feedback if str(r.sentiment).strip().lower() == 'neutral')

        pos_pct = round((pos / total_voices) * 100, 1) if total_voices > 0 else 0
        neg_pct = round((neg / total_voices) * 100, 1) if total_voices > 0 else 0
        neu_pct = round((neu / total_voices) * 100, 1) if total_voices > 0 else 0

        total_active_forms = EvaluationForm.query.filter_by(is_active=True).count()

        return jsonify({
            "total_voices": total_voices,
            "positive_count": pos,
            "negative_count": neg,
            "neutral_count": neu,
            "positive_percent": pos_pct,
            "negative_percent": neg_pct,
            "neutral_percent": neu_pct,
            "active_initiatives": total_active_forms,
            "department": user_dept
        })
    except Exception as e:
        print(f"[!] Error in /api/community_pulse: {e}")
        return jsonify({
            "total_voices": 0, "positive_count": 0, "negative_count": 0, "neutral_count": 0,
            "positive_percent": 0, "negative_percent": 0, "neutral_percent": 0,
            "active_initiatives": 0, "department": current_user.department
        }), 200

@app.route('/api/community_feed', methods=['GET'])
@login_required
def get_community_feed():
    try:
        channel = request.args.get('channel', 'ALL').strip().upper()
        posts_query = CommunityPost.query

        if channel == 'ANNOUNCEMENTS':
            posts_query = posts_query.filter((CommunityPost.target_channel == 'ANNOUNCEMENTS') | (CommunityPost.is_announcement == True))
        elif channel != 'ALL':
            posts_query = posts_query.filter(CommunityPost.target_channel == channel)

        posts = posts_query.order_by(
            CommunityPost.is_announcement.desc(),
            CommunityPost.score.desc(),
            CommunityPost.id.desc()
        ).all()

        user_votes_dict = {
            v.post_id: v.vote_type for v in CommunityPostVote.query.filter_by(user_id=current_user.id).all()
        }
        user_res_votes_dict = {
            rv.post_id: rv.reaction_type for rv in CommunityResolutionVote.query.filter_by(user_id=current_user.id).all()
        }

        out = []
        for p in posts:
            try:
                aspects = json.loads(p.aspect_breakdown)
            except Exception:
                aspects = []

            comment_count = CommunityComment.query.filter_by(post_id=p.id).count()
            res_upvotes = CommunityResolutionVote.query.filter_by(post_id=p.id, reaction_type=1).count()
            res_downvotes = CommunityResolutionVote.query.filter_by(post_id=p.id, reaction_type=-1).count()

            can_edit = bool(p.author_id == current_user.id or current_user.role == 'MISD')

            out.append({
                "id": p.id,
                "target_channel": p.target_channel or "ALL",
                "author_department": p.author_department or "DCI",
                "author_role": p.author_role or "Student - Regular",
                "author_name": p.author_name if p.is_announcement else None,
                "is_announcement": bool(p.is_announcement),
                "program": p.program or "General",
                "category": p.category or "Campus Facilities & Infrastructure",
                "content": p.content or "",
                "image_url": p.image_url,
                "link_url": p.link_url,
                "is_edited": bool(p.is_edited),
                "can_edit": can_edit,
                "sentiment": p.sentiment or "Neutral",
                "confidence": p.confidence or 0.0,
                "aspects": aspects,
                "score": p.score or 0,
                "user_vote": user_votes_dict.get(p.id, 0),
                "comment_count": comment_count,
                "status": p.status or "Open",
                "action_note": p.action_note,
                "action_by": p.action_by,
                "resolution_upvotes": res_upvotes,
                "resolution_downvotes": res_downvotes,
                "user_resolution_vote": user_res_votes_dict.get(p.id, 0),
                "created_at": p.created_at.strftime("%b %d, %Y • %I:%M %p") if p.created_at else ""
            })

        return jsonify(out)
    except Exception as e:
        print(f"[!] Error in /api/community_feed: {e}")
        return jsonify([]), 200

@app.route('/api/community_post', methods=['POST'])
@login_required
def create_community_post():
    try:
        data = request.get_json() or {}
        content = data.get("content", "").strip()
        category = data.get("category", "Campus Facilities & Infrastructure").strip()
        target_channel = data.get("target_channel", "ALL").strip().upper()
        is_announcement = bool(data.get("is_announcement", False))
        image_url = data.get("image_url", "").strip() or None
        link_url = data.get("link_url", "").strip() or None

        if not content or len(content) < 4:
            return jsonify({"error": "Post must be at least 4 characters long."}), 400

        user_role_lower = (current_user.role or "").lower()
        is_authorized = any(k in user_role_lower for k in ['officer', 'representative', 'rep', 'faculty', 'misd'])

        if is_announcement or target_channel == 'ANNOUNCEMENTS':
            if not is_authorized:
                return jsonify({
                    "error": "Permission Denied: Only Student Officers, Class Representatives, and Faculty are authorized to broadcast official campus announcements."
                }), 403
            is_announcement = True

        lexicon = get_active_lexicon()
        cleaned, sentiment, score, breakdown = run_absa_pipeline(content, lexicon)

        post = CommunityPost(
            author_id=current_user.id,
            author_name=current_user.username if is_announcement else None,
            target_channel=target_channel,
            author_department=current_user.department,
            author_role=current_user.role,
            is_announcement=is_announcement,
            program=current_user.program or "General",
            category=category,
            content=content,
            image_url=image_url,
            link_url=link_url,
            sentiment=sentiment,
            confidence=score,
            aspect_breakdown=json.dumps(breakdown),
            score=1,
            status="Open"
        )
        db.session.add(post)
        db.session.flush()

        initial_vote = CommunityPostVote(post_id=post.id, user_id=current_user.id, vote_type=1)
        db.session.add(initial_vote)

        analytics_record = Feedback(
            form_id=None,
            department=target_channel if target_channel not in ["ALL", "ANNOUNCEMENTS"] else current_user.department,
            program=current_user.program or "General",
            academic_year="2025-2026",
            semester="1st Semester",
            raw_text=content,
            cleaned_text=cleaned,
            sentiment=sentiment,
            confidence=score,
            aspect_breakdown=json.dumps(breakdown)
        )
        db.session.add(analytics_record)
        db.session.commit()

        return jsonify({"success": True, "message": "Voice or announcement posted successfully."})
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error creating post: {e}")
        return jsonify({"error": f"Internal error creating post: {e}"}), 500

@app.route('/api/community_post/<int:post_id>/edit', methods=['POST'])
@login_required
def edit_community_post(post_id):
    try:
        post = CommunityPost.query.get(post_id)
        if not post:
            return jsonify({"error": "Post not found."}), 404

        if post.author_id != current_user.id and current_user.role != 'MISD':
            return jsonify({"error": "Unauthorized: You may only edit your own posts."}), 403

        data = request.get_json() or {}
        new_content = data.get("content", "").strip()
        new_category = data.get("category", post.category).strip()
        new_image_url = data.get("image_url", "").strip() or None
        new_link_url = data.get("link_url", "").strip() or None

        if not new_content or len(new_content) < 4:
            return jsonify({"error": "Content must be at least 4 characters long."}), 400

        lexicon = get_active_lexicon()
        cleaned, sentiment, score, breakdown = run_absa_pipeline(new_content, lexicon)

        post.content = new_content
        post.category = new_category
        post.image_url = new_image_url
        post.link_url = new_link_url
        post.sentiment = sentiment
        post.confidence = score
        post.aspect_breakdown = json.dumps(breakdown)
        post.is_edited = True
        post.edited_at = datetime.utcnow()

        db.session.commit()
        return jsonify({"success": True, "message": "Post updated successfully."})
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error editing post: {e}")
        return jsonify({"error": "Failed to edit post."}), 500

@app.route('/api/community_post/vote', methods=['POST'])
@login_required
def vote_post():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    direction = int(data.get("direction", 1))

    if direction not in [1, -1]:
        return jsonify({"error": "Invalid vote direction."}), 400

    post = CommunityPost.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    existing_vote = CommunityPostVote.query.filter_by(post_id=post.id, user_id=current_user.id).first()

    if existing_vote:
        if existing_vote.vote_type == direction:
            db.session.delete(existing_vote)
            user_state = 0
        else:
            existing_vote.vote_type = direction
            user_state = direction
    else:
        new_vote = CommunityPostVote(post_id=post.id, user_id=current_user.id, vote_type=direction)
        db.session.add(new_vote)
        user_state = direction

    db.session.commit()

    total_score = db.session.query(db.func.sum(CommunityPostVote.vote_type)).filter_by(post_id=post.id).scalar() or 0
    post.score = total_score
    db.session.commit()

    return jsonify({"success": True, "score": post.score, "user_vote": user_state})

@app.route('/api/community_post/resolution_vote', methods=['POST'])
@login_required
def vote_resolution():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    direction = int(data.get("direction", 1))

    if direction not in [1, -1]:
        return jsonify({"error": "Invalid reaction direction."}), 400

    post = CommunityPost.query.get(post_id)
    if not post or not post.action_note:
        return jsonify({"error": "No administrative action note available to react to."}), 404

    existing_res_vote = CommunityResolutionVote.query.filter_by(post_id=post.id, user_id=current_user.id).first()

    if existing_res_vote:
        if existing_res_vote.reaction_type == direction:
            db.session.delete(existing_res_vote)
            user_state = 0
        else:
            existing_res_vote.reaction_type = direction
            user_state = direction
    else:
        new_res_vote = CommunityResolutionVote(post_id=post.id, user_id=current_user.id, reaction_type=direction)
        db.session.add(new_res_vote)
        user_state = direction

    db.session.commit()

    upvotes = CommunityResolutionVote.query.filter_by(post_id=post.id, reaction_type=1).count()
    downvotes = CommunityResolutionVote.query.filter_by(post_id=post.id, reaction_type=-1).count()

    return jsonify({
        "success": True,
        "resolution_upvotes": upvotes,
        "resolution_downvotes": downvotes,
        "user_resolution_vote": user_state
    })

@app.route('/api/community_post/<int:post_id>/comments', methods=['GET', 'POST'])
@login_required
def handle_post_comments(post_id):
    post = CommunityPost.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    if request.method == 'POST':
        data = request.get_json() or {}
        content = data.get("content", "").strip()
        if not content or len(content) < 2:
            return jsonify({"error": "Comment must be at least 2 characters."}), 400

        comment = CommunityComment(
            post_id=post.id,
            author_department=current_user.department,
            author_role=current_user.role,
            content=content,
            created_at=datetime.utcnow()
        )
        db.session.add(comment)
        db.session.commit()

        return jsonify({
            "success": True,
            "comment": {
                "id": comment.id,
                "author_department": comment.author_department,
                "author_role": comment.author_role,
                "content": comment.content,
                "created_at": comment.created_at.strftime("%b %d, %Y • %I:%M %p")
            }
        })

    comments = CommunityComment.query.filter_by(post_id=post.id).order_by(CommunityComment.created_at.asc()).all()
    return jsonify([
        {
            "id": c.id,
            "author_department": c.author_department,
            "author_role": c.author_role or "Student - Regular",
            "content": c.content,
            "created_at": c.created_at.strftime("%b %d, %Y • %I:%M %p")
        } for c in comments
    ])

@app.route('/api/community_post/status', methods=['POST'])
@login_required
def update_post_status():
    user_role_lower = (current_user.role or "").lower()
    is_duty_bearer = any(k in user_role_lower for k in ['officer', 'faculty', 'misd'])
    if not is_duty_bearer:
        return jsonify({"error": "Unauthorized. Only verified duty-bearers can post action updates."}), 403

    data = request.get_json() or {}
    post_id = data.get("post_id")
    status = data.get("status", "Under Review")
    action_note = data.get("action_note", "").strip()

    post = CommunityPost.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    post.status = status
    post.action_note = action_note
    post.action_by = f"{current_user.username} ({current_user.role})"
    db.session.commit()

    return jsonify({"success": True, "status": post.status, "action_note": post.action_note})

# =========================================================
# EVALUATION FORMS, TARGETING, QUOTAS & AUTHOR ANALYTICS
# =========================================================
@app.route('/api/forms', methods=['GET'])
@login_required
def get_forms_api():
    try:
        user_dept = current_user.department
        query = EvaluationForm.query.filter_by(is_active=True)

        if current_user.role not in ["MISD", "Faculty"]:
            query = query.filter((EvaluationForm.department == 'ALL') | (EvaluationForm.department == user_dept))

        forms = query.order_by(EvaluationForm.id.desc()).all()
        submitted_form_ids = set(
            r.form_id for r in FormResponseRecord.query.filter_by(student_id=current_user.id).all()
        )

        out = []
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")

        for f in forms:
            try:
                q_list = json.loads(f.questions_json)
            except Exception:
                q_list = []

            total_submissions = FormAnonymousSubmission.query.filter_by(form_id=f.id).count()

            # Exact date & minute deadline evaluation
            is_expired = False
            if f.deadline_date and f.deadline_date not in ["No Expiry", "None", ""]:
                if "T" in f.deadline_date:
                    is_expired = bool(f.deadline_date < now_iso)
                else:
                    is_expired = bool(f.deadline_date < now_iso[:10])

            is_quota_full = bool(f.max_responses and f.max_responses > 0 and total_submissions >= f.max_responses)

            out.append({
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "form_category": f.form_category,
                "department": f.department,
                "program": f.program,
                "subject_code": f.subject_code or "N/A",
                "section_target": f.section_target or "ALL",
                "deadline_date": f.deadline_date or "No Expiry",
                "max_responses": f.max_responses or 0,
                "total_submissions": total_submissions,
                "is_closed": is_expired or is_quota_full,
                "close_reason": "Deadline Passed" if is_expired else ("Quota Reached" if is_quota_full else None),
                "academic_year": f.academic_year,
                "semester": f.semester,
                "created_by_name": f.created_by_name,
                "created_by_role": f.created_by_role,
                "questions": q_list,
                "already_submitted": (f.id in submitted_form_ids),
                "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else ""
            })

        return jsonify(out)
    except Exception as e:
        print(f"[!] Error in /api/forms: {e}")
        return jsonify([]), 200

@app.route('/api/forms/create', methods=['POST'])
@login_required
def create_form_api():
    user_role_lower = (current_user.role or "").lower()
    is_authorized = any(k in user_role_lower for k in ['officer', 'representative', 'rep', 'faculty', 'misd'])
    if not is_authorized:
        return jsonify({"error": "Unauthorized. Form creation is reserved for community advocates."}), 403

    data = request.get_json() or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    category = data.get("form_category", "Community Initiative").strip()
    target_dept = data.get("department", current_user.department).strip().upper()
    target_prog = data.get("program", current_user.program or "ALL").strip()
    subject_code = data.get("subject_code", "").strip() or None
    section_target = data.get("section_target", "ALL").strip() or "ALL"
    deadline_date = data.get("deadline_date", "").strip() or None
    max_responses = int(data.get("max_responses", 0) or 0)
    academic_year = data.get("academic_year", "2025-2026").strip()
    semester = data.get("semester", "1st Semester").strip()
    questions = data.get("questions", [])

    if not title:
        return jsonify({"error": "Form title is required."}), 400
    if not questions or not isinstance(questions, list):
        return jsonify({"error": "Please specify at least one inquiry item."}), 400

    # Methodology Guardrail: Enforce qualitative text for XLM-RoBERTa
    has_text_prompt = any(
        q.get("type") in ["narrative", "text"] or 
        q.get("allow_explanation") is True or 
        q.get("elaboration_logic") in ["low", "low_mid", "always"]
        for q in questions
    )
    if not has_text_prompt:
        return jsonify({
            "error": "Thesis Methodology Requirement: Every survey must include at least one open-ended narrative inquiry or Likert explanation box for NLP sentiment evaluation."
        }), 400

    new_form = EvaluationForm(
        title=title,
        description=description,
        form_category=category,
        department=target_dept,
        program=target_prog,
        subject_code=subject_code,
        section_target=section_target,
        deadline_date=deadline_date,
        max_responses=max_responses,
        academic_year=academic_year,
        semester=semester,
        created_by_id=current_user.id,
        created_by_name=current_user.username,
        created_by_role=current_user.role,
        questions_json=json.dumps(questions),
        is_active=True
    )
    db.session.add(new_form)
    db.session.commit()

    return jsonify({"success": True, "form_id": new_form.id, "title": new_form.title})

@app.route('/api/forms/submit', methods=['POST'])
@login_required
def submit_form_api():
    data = request.get_json() or {}
    form_id = data.get("form_id")
    answers = data.get("answers", [])

    if not form_id or not answers:
        return jsonify({"error": "Invalid form submission payload."}), 400

    form = EvaluationForm.query.get(form_id)
    if not form or not form.is_active:
        return jsonify({"error": "This evaluation is currently closed or unavailable."}), 404

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M")
    if form.deadline_date and form.deadline_date not in ["No Expiry", "None", ""]:
        expired = (form.deadline_date < now_iso) if "T" in form.deadline_date else (form.deadline_date < now_iso[:10])
        if expired:
            return jsonify({"error": f"Submission closed: The deadline has passed."}), 400

    total_submissions = FormAnonymousSubmission.query.filter_by(form_id=form.id).count()
    if form.max_responses and form.max_responses > 0 and total_submissions >= form.max_responses:
        return jsonify({"error": "Submission closed: The participant quota has been reached."}), 400

    already = FormResponseRecord.query.filter_by(form_id=form.id, student_id=current_user.id).first()
    if already:
        return jsonify({"error": "You have already completed this evaluation form."}), 400

    lexicon = get_active_lexicon()
    processed_clauses = 0

    for ans in answers:
        comment_text = ans.get("narrative_text", "").strip() or ans.get("answer", "").strip()
        if not comment_text and ans.get("type") in ["narrative", "text"] and isinstance(ans.get("value"), str):
            comment_text = ans.get("value", "").strip()

        if not comment_text or len(comment_text) < 3:
            continue

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment_text, lexicon)

        entry = Feedback(
            form_id=form.id,
            department=form.department if form.department != "ALL" else current_user.department,
            program=form.program if form.program != "ALL" else (current_user.program or "General"),
            academic_year=form.academic_year,
            semester=form.semester,
            raw_text=comment_text,
            cleaned_text=cleaned,
            sentiment=sentiment,
            confidence=score,
            aspect_breakdown=json.dumps(breakdown)
        )
        db.session.add(entry)
        processed_clauses += 1

    anon_submission = FormAnonymousSubmission(
        form_id=form.id,
        answers_json=json.dumps(answers),
        submitted_at=datetime.utcnow()
    )
    db.session.add(anon_submission)

    submission_receipt = FormResponseRecord(
        form_id=form.id,
        student_id=current_user.id,
        submitted_at=datetime.utcnow()
    )
    db.session.add(submission_receipt)
    db.session.commit()

    return jsonify({
        "success": True,
        "processed_clauses": processed_clauses,
        "message": "Evaluation recorded anonymously and analyzed by local ABSA model."
    })

@app.route('/api/forms/my_forms', methods=['GET'])
@login_required
def my_forms_api():
    try:
        forms = EvaluationForm.query.filter_by(created_by_id=current_user.id).order_by(EvaluationForm.id.desc()).all()
        out = []
        for f in forms:
            count = FormAnonymousSubmission.query.filter_by(form_id=f.id).count()
            out.append({
                "id": f.id,
                "title": f.title,
                "form_category": f.form_category,
                "subject_code": f.subject_code or "N/A",
                "section_target": f.section_target or "ALL",
                "academic_year": f.academic_year,
                "semester": f.semester,
                "response_count": count,
                "max_responses": f.max_responses or 0,
                "deadline_date": f.deadline_date,
                "is_active": f.is_active,
                "created_at": f.created_at.strftime("%Y-%m-%d") if f.created_at else ""
            })
        return jsonify(out)
    except Exception as e:
        print(f"[!] Error in /api/forms/my_forms: {e}")
        return jsonify([]), 200

# =========================================================
# AUTHOR RESPONSE ANALYTICS & ISOLATED CSV EXPORT
# =========================================================
@app.route('/api/forms/<int:form_id>/analytics', methods=['GET'])
@login_required
def get_form_analytics(form_id):
    form = EvaluationForm.query.get(form_id)
    if not form:
        return jsonify({"error": "Form not found."}), 404

    if form.created_by_id != current_user.id and current_user.role != 'MISD':
        return jsonify({"error": "Unauthorized to view private survey analytics."}), 403

    submissions = FormAnonymousSubmission.query.filter_by(form_id=form.id).all()
    total_responses = len(submissions)

    try:
        questions = json.loads(form.questions_json)
    except Exception:
        questions = []

    q_stats = {}
    for q in questions:
        q_id = str(q.get("id"))
        q_type = q.get("type", "narrative")
        q_stats[q_id] = {
            "id": q.get("id"),
            "prompt": q.get("prompt"),
            "type": q_type,
            "total_answers": 0,
            "likert_sum": 0,
            "likert_counts": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            "choice_counts": {},
            "narratives": []
        }

    for sub in submissions:
        try:
            answers = json.loads(sub.answers_json)
            for ans in answers:
                qid = str(ans.get("question_id"))
                if qid in q_stats:
                    stat = q_stats[qid]
                    stat["total_answers"] += 1
                    val = ans.get("value")
                    score = ans.get("score")
                    text_ans = ans.get("answer")
                    narrative_exp = ans.get("narrative_text")

                    if stat["type"] == "likert":
                        l_val = score if score is not None else val
                        try:
                            num = int(l_val)
                            if 1 <= num <= 5:
                                stat["likert_sum"] += num
                                stat["likert_counts"][num] += 1
                        except Exception:
                            pass

                        if narrative_exp:
                            stat["narratives"].append(narrative_exp)

                    elif stat["type"] in ["radio", "single_choice"]:
                        choice_str = str(val).strip() if val is not None else ""
                        if choice_str:
                            stat["choice_counts"][choice_str] = stat["choice_counts"].get(choice_str, 0) + 1

                    elif stat["type"] in ["checkbox", "multiple_choice"]:
                        if isinstance(val, list):
                            for item in val:
                                item_str = str(item).strip()
                                if item_str:
                                    stat["choice_counts"][item_str] = stat["choice_counts"].get(item_str, 0) + 1

                    elif stat["type"] in ["narrative", "text"]:
                        n_val = text_ans or val or narrative_exp
                        if n_val:
                            stat["narratives"].append(str(n_val))
        except Exception:
            continue

    for qid, stat in q_stats.items():
        if stat["type"] == "likert":
            stat["average_rating"] = round(stat["likert_sum"] / stat["total_answers"], 2) if stat["total_answers"] > 0 else 0

    return jsonify({
        "form_id": form.id,
        "title": form.title,
        "description": form.description,
        "section_target": form.section_target or "ALL",
        "subject_code": form.subject_code or "N/A",
        "total_responses": total_responses,
        "questions_analytics": list(q_stats.values())
    })

@app.route('/api/forms/<int:form_id>/export_csv', methods=['GET'])
@login_required
def export_form_csv(form_id):
    form = EvaluationForm.query.get(form_id)
    if not form:
        return jsonify({"error": "Form not found."}), 404

    if form.created_by_id != current_user.id and current_user.role != 'MISD':
        return jsonify({"error": "Unauthorized to export private survey."}), 403

    try:
        questions = json.loads(form.questions_json)
    except Exception:
        questions = []

    submissions = FormAnonymousSubmission.query.filter_by(form_id=form.id).order_by(FormAnonymousSubmission.id.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = ["Submission ID", "Timestamp"]
    for q in questions:
        headers.append(f"Q{q.get('id')}: {q.get('prompt')}")
        has_elaboration = q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]
        if q.get("type") == "likert" and has_elaboration:
            headers.append(f"Q{q.get('id')} Elaboration")

    writer.writerow(headers)

    for sub in submissions:
        row = [sub.id, sub.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if sub.submitted_at else ""]
        ans_map = {}
        try:
            items = json.loads(sub.answers_json)
            for it in items:
                ans_map[str(it.get("question_id"))] = it
        except Exception:
            pass

        for q in questions:
            qid = str(q.get("id"))
            entry = ans_map.get(qid, {})
            val = entry.get("value")
            if val is None and entry.get("score") is not None:
                val = entry.get("score")
            if val is None and entry.get("answer") is not None:
                val = entry.get("answer")
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val)
            row.append(val if val is not None else "")

            has_elaboration = q.get("allow_explanation") or q.get("elaboration_logic") in ["low", "low_mid", "always"]
            if q.get("type") == "likert" and has_elaboration:
                row.append(entry.get("narrative_text", ""))

        writer.writerow(row)

    output.seek(0)
    safe_title = re.sub(r'[^\w\-_\.]', '_', form.title)[:25]
    filename = f"survey_export_{form.id}_{safe_title}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

# ==========================================
# ACADEMIC YEARS MANAGEMENT API
# ==========================================
@app.route('/api/academic_years', methods=['GET', 'POST'])
@login_required
def handle_academic_years():
    if request.method == 'GET':
        years = [y.year for y in AcademicYear.query.order_by(AcademicYear.year.asc()).all()]
        return jsonify(years)

    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized. Registering academic years is restricted to MISD."}), 403

    data = request.get_json() or {}
    year_val = data.get('year', '').strip()

    if not year_val or not re.match(r'^\d{4}-\d{4}$', year_val):
        return jsonify({"error": "Academic Year must follow the format 'YYYY-YYYY' (e.g., 2026-2027)."}), 400

    if AcademicYear.query.filter_by(year=year_val).first():
        return jsonify({"error": f"Academic Year '{year_val}' already exists."}), 400

    new_yr = AcademicYear(year=year_val)
    db.session.add(new_yr)
    db.session.commit()
    return jsonify({"success": True, "year": year_val})

# ==========================================
# DASHBOARD & ANALYTICS API (RESTORED)
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role.startswith("Student"):
        return redirect(url_for('student_portal'))

    return render_template(
        'dashboard.html',
        username=current_user.username,
        role=current_user.role,
        user_dept=current_user.department,
        user_program=current_user.program
    )

@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    try:
        requested_dept = request.args.get('department', 'ALL').strip().upper()
        selected_year = request.args.get('year', 'ALL').strip()
        selected_sem = request.args.get('semester', 'ALL').strip()
        search_query = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        effective_dept = current_user.department if current_user.role != "MISD" else requested_dept

        query = Feedback.query
        if effective_dept != 'ALL':
            query = query.filter_by(department=effective_dept)
        if selected_year != 'ALL':
            query = query.filter_by(academic_year=selected_year)
        if selected_sem != 'ALL':
            query = query.filter_by(semester=selected_sem)
        if search_query:
            query = query.filter(
                (Feedback.raw_text.ilike(f"%{search_query}%")) |
                (Feedback.program.ilike(f"%{search_query}%"))
            )

        all_matching = query.all()
        total_items = len(all_matching)
        total_pages = max(1, math.ceil(total_items / per_page)) if total_items > 0 else 1
        page = min(max(1, page), total_pages)

        pos = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'positive')
        neg = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'negative')
        neu = sum(1 for r in all_matching if str(r.sentiment).strip().lower() == 'neutral')
        total = total_items

        aspect_counts = {
            "Instructional Delivery": {"pos": 0, "neg": 0, "neu": 0},
            "Faculty Demeanor": {"pos": 0, "neg": 0, "neu": 0},
            "Facilities": {"pos": 0, "neg": 0, "neu": 0}
        }

        for r in all_matching:
            try:
                items = json.loads(r.aspect_breakdown)
                for item in items:
                    asp = item.get("aspect", "")
                    pol = str(item.get("polarity", "")).strip().capitalize()
                    key = None
                    if "Instructional" in asp:
                        key = "Instructional Delivery"
                    elif "Demeanor" in asp:
                        key = "Faculty Demeanor"
                    elif "Facilities" in asp:
                        key = "Facilities"

                    if key and pol in ["Positive", "Negative", "Neutral"]:
                        pol_key = "pos" if pol == "Positive" else "neg" if pol == "Negative" else "neu"
                        aspect_counts[key][pol_key] += 1
            except Exception:
                continue

        paged_records = query.order_by(Feedback.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

        recent_logs = []
        for entry in paged_records:
            try:
                parsed = json.loads(entry.aspect_breakdown)
            except Exception:
                parsed = []
            recent_logs.append({
                "id": entry.id,
                "form_id": entry.form_id,
                "department": entry.department,
                "program": entry.program or "General",
                "academic_year": entry.academic_year or "2025-2026",
                "semester": entry.semester or "1st Semester",
                "raw_text": entry.raw_text,
                "sentiment": entry.sentiment,
                "confidence": entry.confidence,
                "aspects": parsed,
                "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M") if entry.timestamp else ""
            })

        insights = compute_prescriptive_insights(all_matching)
        pie_b64 = generate_matplotlib_pie(pos, neg, neu)
        bar_b64 = generate_matplotlib_bar(aspect_counts)
        available_years = [y.year for y in AcademicYear.query.order_by(AcademicYear.year.asc()).all()]

        return jsonify({
            "department": effective_dept,
            "year": selected_year,
            "semester": selected_sem,
            "available_years": available_years,
            "kpis": {"total": total, "pos": pos, "neg": neg, "neu": neu},
            "pie_chart": pie_b64,
            "aspect_chart": bar_b64,
            "insights": insights,
            "logs": recent_logs,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages
            }
        })
    except Exception as e:
        print(f"[!] Error in /api/analytics: {e}")
        return jsonify({
            "department": "ALL",
            "kpis": {"total": 0, "pos": 0, "neg": 0, "neu": 0},
            "pie_chart": "",
            "aspect_chart": "",
            "insights": [{"level": "Community Baseline", "aspect": "Pulse Initialized", "recommendation": "Listening system active."}],
            "logs": [],
            "available_years": ["2024-2025", "2025-2026", "2026-2027"],
            "pagination": {"page": 1, "per_page": 10, "total_items": 0, "total_pages": 1}
        }), 200

@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_api():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized. Diagnostic sandbox restricted to MISD."}), 403

    data = request.get_json() or {}
    comment = data.get("comment", "").strip()
    department = data.get("department", "DCI").upper()
    program = data.get("program", "Institutional Testing")
    academic_year = data.get("academic_year", "2025-2026")
    semester = data.get("semester", "1st Semester")

    if not comment:
        return jsonify({"error": "No comment provided."}), 400

    lexicon = get_active_lexicon()
    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)

    entry = Feedback(
        department=department,
        program=program,
        academic_year=academic_year,
        semester=semester,
        raw_text=comment,
        cleaned_text=cleaned,
        sentiment=sentiment,
        confidence=score,
        aspect_breakdown=json.dumps(breakdown)
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({
        "id": entry.id,
        "department": department,
        "program": program,
        "academic_year": academic_year,
        "semester": semester,
        "raw": comment,
        "sentiment": sentiment,
        "confidence_score": score,
        "aspect_breakdown": breakdown
    })

@app.route('/api/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized. Batch ingestion restricted to MISD."}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    default_dept = request.form.get('department', 'DCI').upper()
    default_prog = request.form.get('program', 'General')
    default_year = request.form.get('academic_year', '2025-2026')
    default_sem = request.form.get('semester', '1st Semester')

    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be a valid .csv file."}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"))
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        return jsonify({"error": "Invalid or empty CSV header."}), 400

    text_col = None
    for col in reader.fieldnames:
        if any(keyword in col.lower() for keyword in ["comment", "feedback", "narrative", "text", "review"]):
            text_col = col
            break
    if not text_col:
        text_col = reader.fieldnames[0]

    dept_col = next((col for col in reader.fieldnames if any(k in col.lower() for k in ["dept", "department", "college"])), None)
    prog_col = next((col for col in reader.fieldnames if any(k in col.lower() for k in ["prog", "program", "course"])), None)
    year_col = next((col for col in reader.fieldnames if any(k in col.lower() for k in ["year", "ay", "acad"])), None)
    sem_col = next((col for col in reader.fieldnames if any(k in col.lower() for k in ["sem", "semester"])), None)

    lexicon = get_active_lexicon()
    processed_count = 0

    for row in reader:
        comment = row.get(text_col, '').strip()
        if not comment:
            continue

        assigned_dept = row.get(dept_col, default_dept).strip().upper() if dept_col else default_dept
        assigned_prog = row.get(prog_col, default_prog).strip() if prog_col else default_prog
        assigned_year = row.get(year_col, default_year).strip() if year_col else default_year
        assigned_sem = row.get(sem_col, default_sem).strip() if sem_col else default_sem

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)
        entry = Feedback(
            department=assigned_dept,
            program=assigned_prog,
            academic_year=assigned_year,
            semester=assigned_sem,
            raw_text=comment,
            cleaned_text=cleaned,
            sentiment=sentiment,
            confidence=score,
            aspect_breakdown=json.dumps(breakdown)
        )
        db.session.add(entry)
        processed_count += 1

    db.session.commit()
    return jsonify({"success": True, "processed": processed_count})

@app.route('/api/export_csv', methods=['GET'])
@login_required
def export_csv():
    dept = current_user.department if current_user.role != "MISD" else request.args.get('department', 'ALL').strip().upper()
    selected_year = request.args.get('year', 'ALL').strip()
    selected_sem = request.args.get('semester', 'ALL').strip()

    query = Feedback.query
    if dept != 'ALL':
        query = query.filter_by(department=dept)
    if selected_year != 'ALL':
        query = query.filter_by(academic_year=selected_year)
    if selected_sem != 'ALL':
        query = query.filter_by(semester=selected_sem)

    records = query.order_by(Feedback.id.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Form ID", "Academic Year", "Semester", "Department", "Program", "Raw Feedback", "Sentiment", "Confidence", "Aspect Breakdown", "Timestamp"])

    for r in records:
        writer.writerow([r.id, r.form_id or "N/A", r.academic_year, r.semester, r.department, r.program, r.raw_text, r.sentiment, r.confidence, r.aspect_breakdown, r.timestamp])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=ccc_community_sentiment_export_{dept.lower()}_{selected_year}_{selected_sem}.csv"}
    )

@app.route('/api/lexicon', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_lexicon():
    if request.method == 'GET':
        terms = LexiconTerm.query.order_by(LexiconTerm.id.desc()).all()
        return jsonify([{"id": t.id, "word": t.word, "category": t.category} for t in terms])

    if current_user.role != "MISD":
        return jsonify({"error": "Administrative clearance (MISD) required."}), 403

    if request.method == 'POST':
        data = request.get_json() or {}
        word = data.get('word', '').strip().lower()
        category = data.get('category', '').strip().lower()

        if not word or category not in ['positive', 'negative', 'intensifiers', 'negations']:
            return jsonify({"error": "Invalid word or category."}), 400

        if LexiconTerm.query.filter_by(word=word).first():
            return jsonify({"error": f"'{word}' already exists in the lexicon."}), 400

        term = LexiconTerm(word=word, category=category)
        db.session.add(term)
        db.session.commit()
        return jsonify({"success": True, "id": term.id, "word": term.word, "category": term.category})

    if request.method == 'DELETE':
        data = request.get_json() or {}
        term_id = data.get('id')
        term = LexiconTerm.query.get(term_id)
        if not term:
            return jsonify({"error": "Term not found."}), 404
        db.session.delete(term)
        db.session.commit()
        return jsonify({"success": True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)