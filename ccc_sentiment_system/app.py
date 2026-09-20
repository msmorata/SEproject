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
    """
    Sends an automated verification email with the 6-digit passcode.
    Uses a 3-second timeout for fast offline fallbacks.
    """
    try:
        msg = EmailMessage()
        msg['Subject'] = "City College of Calamba — Account Verification Code"
        msg['From'] = f"CCC Sentiment Portal <{MAIL_SENDER}>"
        msg['To'] = recipient_email

        # Plaintext Fallback
        msg.set_content(f"""
Hello {username},

Your 6-digit confirmation passcode for the City College of Calamba Sentiment Evaluation Portal is:

{code}

Enter this code on the activation page to verify your institutional account.

If you did not initiate this registration, please disregard this notification.

Best regards,
Management Information Services Division (MISD)
City College of Calamba
        """)

        # Styled Institutional HTML Template
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #070d1d; color: #f8fafc; padding: 30px; margin: 0;">
            <div style="max-width: 500px; margin: 0 auto; background: #0f1a30; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 28px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                <h2 style="color: #60a5fa; margin: 0 0 6px 0; font-size: 20px;">City College of Calamba</h2>
                <p style="color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 20px 0;">Sentiment Evaluation & ABSA Decision Portal</p>
                <div style="border-top: 1px solid rgba(255,255,255,0.08); margin: 18px 0;"></div>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left; line-height: 1.5;">Hello <strong>{username}</strong>,</p>
                <p style="color: #cbd5e1; font-size: 14px; text-align: left; line-height: 1.5;">Please use the following 6-digit security code to activate your account:</p>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #fbbf24; background: #070d1d; border: 1.5px dashed rgba(245, 158, 11, 0.6); padding: 14px; border-radius: 10px; margin: 24px 0;">
                    {code}
                </div>
                <p style="color: #94a3b8; font-size: 12px; text-align: left; line-height: 1.5;">This passcode confirms your institutional identity. Do not share this code with anyone.</p>
                <div style="border-top: 1px solid rgba(255,255,255,0.08); margin: 20px 0;"></div>
                <p style="color: #64748b; font-size: 11px; margin: 0;">Institutional Quality Assurance &bull; Management Information Services Division (MISD)</p>
            </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype='html')

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=3) as server:
            server.starttls()
            server.login(MAIL_SENDER, MAIL_PASSWORD)
            server.send_message(msg)

        print(f"[+] Verification email successfully sent to: {recipient_email}")
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
    role = db.Column(db.String(50), nullable=False, default="Faculty")
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
    form_category = db.Column(db.String(100), nullable=False, default="Event Evaluation")
    department = db.Column(db.String(50), nullable=False, default="ALL")
    program = db.Column(db.String(150), nullable=False, default="ALL")
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
    form_id = db.Column(db.Integer, db.ForeignKey('evaluation_forms.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
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

with app.app_context():
    db.create_all()
    try:
        alter_queries = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(180) UNIQUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'Faculty';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(50) DEFAULT 'DCI';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS program TEXT;",
            "ALTER TABLE users ALTER COLUMN program TYPE TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(6);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS form_id INTEGER;",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS program VARCHAR(150) DEFAULT 'General';",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS academic_year VARCHAR(20) DEFAULT '2025-2026';",
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS semester VARCHAR(30) DEFAULT '1st Semester';"
        ]
        for q in alter_queries:
            db.session.execute(text(q))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Schema upgrade notice: {e}")
    seed_database()

# ==========================================
# NLP PIPELINE & ABSA CONFIGURATION
# ==========================================
print("Loading BERT Sentiment Engine from local cache...")
try:
    classifier = pipeline(
        "sentiment-analysis",
        model="nlptown/bert-base-multilingual-uncased-sentiment",
        model_kwargs={"local_files_only": True}
    )
except Exception:
    try:
        classifier = pipeline("sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment")
    except Exception as e:
        print(f"Fallback to default pipeline: {e}")
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
    bert_result = classifier(clause[:512])[0]
    bert_label = bert_result['label']
    bert_score = round(bert_result['score'], 4)

    if "star" in bert_label.lower():
        stars = int(bert_label[0])
        if stars >= 4:
            bert_polarity = "Positive"
        elif stars == 3:
            bert_polarity = "Neutral"
        else:
            bert_polarity = "Negative"
    else:
        raw_upper = bert_label.upper()
        if "POS" in raw_upper:
            bert_polarity = "Positive"
        elif "NEG" in raw_upper:
            bert_polarity = "Negative"
        else:
            bert_polarity = "Neutral"

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
            token_info["base_score"] = 0
            token_info["final_score"] = 0.0
        elif word in lexicon["intensifiers"] or root in lexicon["intensifiers"]:
            pending_intensifier = 1.5
            token_info["role"] = "Intensifier (1.5x Multiplier)"
            token_info["base_score"] = 0
            token_info["final_score"] = 0.0
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
        explanation = f"BERT: {bert_score}. Slang sarcasm invalidator ('eme/charot') triggered."
    elif net_lexical_score > 0:
        polarity = "Positive"
        explanation = f"BERT: {bert_score}. Lexical score (+{round(net_lexical_score, 2)}) confirmed Positive sentiment."
    elif net_lexical_score < 0:
        polarity = "Negative"
        explanation = f"BERT: {bert_score}. Lexical score ({round(net_lexical_score, 2)}) confirmed Negative sentiment."
    else:
        polarity = bert_polarity
        explanation = f"BERT Confidence: {bert_score}. Neutral lexical baseline."

    return polarity, bert_score, explanation, token_scores, round(net_lexical_score, 2)

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
# HIGH-DPI MATPLOTLIB VISUALIZATION ENGINE
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
            ax.text(0, 0, '0\nLOGS', ha='center', va='center',
                    color='#64748b', fontsize=8.5, fontweight='bold', linespacing=1.2)
        else:
            counts, colors, labels = [], [], []
            if pos > 0: counts.append(pos); colors.append('#10b981'); labels.append(f'{pos}')
            if neg > 0: counts.append(neg); colors.append('#f43f5e'); labels.append(f'{neg}')
            if neu > 0: counts.append(neu); colors.append('#f59e0b'); labels.append(f'{neu}')

            if not counts:
                counts = [total]
                colors = ['#334155']
                labels = [f'{total}']

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

            ax.text(0, 0, f'{total}\nLOGS', ha='center', va='center',
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

# ==========================================
# PRESCRIPTIVE ANALYTICS ENGINE
# ==========================================
def compute_prescriptive_insights(records):
    if not records:
        return [{
            "level": "Stable Baseline",
            "aspect": "Cross-Departmental Performance",
            "ratio": 0,
            "recommendation": "System initialized. No student evaluation records currently loaded."
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
                        "level": "Critical Alert",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Elevated facility grievances detected. Forward work order to General Services for ventilation, power outlets, and computer equipment checks."
                    })
                elif asp == "Instructional Delivery & Pedagogy":
                    insights.append({
                        "level": "Pedagogical Warning",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Pacing and clarity concerns noted. Department dean should coordinate syllabus alignment and code-switched instructional delivery workshops."
                    })
                elif asp == "Faculty Demeanor & Approachability":
                    insights.append({
                        "level": "Faculty Advisory",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Approachability concerns recorded. Recommend scheduled office consultation hours and active student rapport initiatives."
                    })

    if not insights:
        insights.append({
            "level": "Stable Baseline",
            "aspect": "Departmental Quality Index",
            "ratio": 0,
            "recommendation": "Overall feedback metrics are within compliant pedagogical bounds. No operational grievance triggers activated."
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
        cleaned_programs = []
        for p in programs_list:
            clean_val = p.strip()
            if clean_val and clean_val not in cleaned_programs:
                cleaned_programs.append(clean_val)

        if not username or not email or not password:
            return render_template('auth.html', error="All fields are required.", mode="signup")

        if not (email.endswith('@ccc.edu.ph') or email.endswith('@gmail.com')):
            return render_template(
                'auth.html',
                error="Access restricted: Please register using an official institutional email (@ccc.edu.ph or @gmail.com for testing).",
                mode="signup"
            )

        # FAILSAFE 1: Check if an unverified account already exists for this email/username
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            if not existing_user.is_verified:
                session['pending_verification_email'] = existing_user.email
                flash("An uncompleted registration exists for this account. Please enter your verification code below.")
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

        print("\n" + "="*55)
        print(" [CCC REGISTRATION AUTHENTICATOR STATUS] ")
        print(f" USER: {username} | EMAIL: {email}")
        print(f" ROLE: {role} | DEPT: {department}")
        print(f" 6-DIGIT VERIFICATION CODE: {code}")
        print(f" SMTP EMAIL DISPATCHED: {'SUCCESS' if email_sent else 'FAILED (Fallback to terminal/screen)'}")
        print("="*55 + "\n")

        session['pending_verification_email'] = email
        display_code = None if email_sent else code

        return render_template('auth.html', mode="verify", email=email, dev_code=display_code)

    return render_template('auth.html', mode="signup")

@app.route('/resend-code', methods=['POST'])
def resend_code():
    """
    FAILSAFE 2: Generates and re-dispatches a fresh 6-digit confirmation code.
    """
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

    print("\n" + "="*55)
    print(" [CCC RESEND VERIFICATION CODE] ")
    print(f" USER: {user.username} | EMAIL: {user.email}")
    print(f" NEW 6-DIGIT CODE: {new_code}")
    print(f" SMTP DISPATCH: {'SUCCESS' if email_sent else 'FAILED (Fallback)'}")
    print("="*55 + "\n")

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
            # FAILSAFE 3: Automatically recover unverified users upon signing in
            if not user.is_verified:
                session['pending_verification_email'] = user.email
                flash("Account unverified. Please confirm your 6-digit email code to finish registration.")
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

# ==========================================
# STUDENT PORTAL & NATIVE FORM BUILDER API
# ==========================================
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

@app.route('/api/forms', methods=['GET'])
@login_required
def get_forms_api():
    user_dept = current_user.department
    query = EvaluationForm.query.filter_by(is_active=True)

    if current_user.role != "MISD":
        query = query.filter((EvaluationForm.department == 'ALL') | (EvaluationForm.department == user_dept))

    forms = query.order_by(EvaluationForm.id.desc()).all()
    submitted_form_ids = set(
        r.form_id for r in FormResponseRecord.query.filter_by(student_id=current_user.id).all()
    )

    out = []
    for f in forms:
        try:
            q_list = json.loads(f.questions_json)
        except Exception:
            q_list = []
        out.append({
            "id": f.id,
            "title": f.title,
            "description": f.description,
            "form_category": f.form_category,
            "department": f.department,
            "program": f.program,
            "academic_year": f.academic_year,
            "semester": f.semester,
            "created_by_name": f.created_by_name,
            "created_by_role": f.created_by_role,
            "questions": q_list,
            "already_submitted": (f.id in submitted_form_ids),
            "created_at": f.created_at.strftime("%Y-%m-%d")
        })

    return jsonify(out)

@app.route('/api/forms/create', methods=['POST'])
@login_required
def create_form_api():
    allowed_roles = ["Student - Class Representative", "Student - Officer", "MISD"]
    if current_user.role not in allowed_roles:
        return jsonify({"error": "Unauthorized. Form creation is reserved for Class Representatives, Officers, and MISD."}), 403

    data = request.get_json() or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    category = data.get("form_category", "Event Evaluation").strip()
    target_dept = data.get("department", current_user.department).strip().upper()
    target_prog = data.get("program", current_user.program or "ALL").strip()
    academic_year = data.get("academic_year", "2025-2026").strip()
    semester = data.get("semester", "1st Semester").strip()
    questions = data.get("questions", [])

    if not title:
        return jsonify({"error": "Form title is required."}), 400
    if not questions or not isinstance(questions, list):
        return jsonify({"error": "Please specify at least one evaluation question."}), 400

    new_form = EvaluationForm(
        title=title,
        description=description,
        form_category=category,
        department=target_dept,
        program=target_prog,
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
        return jsonify({"error": "Form is either closed or no longer available."}), 404

    already = FormResponseRecord.query.filter_by(form_id=form.id, student_id=current_user.id).first()
    if already:
        return jsonify({"error": "You have already completed this evaluation form."}), 400

    lexicon = get_active_lexicon()
    processed_clauses = 0

    for ans in answers:
        comment_text = ans.get("answer", "").strip()
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

    submission_record = FormResponseRecord(
        form_id=form.id,
        student_id=current_user.id,
        submitted_at=datetime.utcnow()
    )
    db.session.add(submission_record)
    db.session.commit()

    return jsonify({
        "success": True,
        "processed_clauses": processed_clauses,
        "message": "Evaluation successfully submitted and ingested into analytics engine."
    })

@app.route('/api/forms/my_forms', methods=['GET'])
@login_required
def my_forms_api():
    forms = EvaluationForm.query.filter_by(created_by_id=current_user.id).order_by(EvaluationForm.id.desc()).all()
    out = []
    for f in forms:
        count = FormResponseRecord.query.filter_by(form_id=f.id).count()
        out.append({
            "id": f.id,
            "title": f.title,
            "form_category": f.form_category,
            "academic_year": f.academic_year,
            "semester": f.semester,
            "response_count": count,
            "is_active": f.is_active,
            "created_at": f.created_at.strftime("%Y-%m-%d")
        })
    return jsonify(out)

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
        return jsonify({"error": "Unauthorized. Adding academic years is restricted to MISD clearance."}), 403

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
# DASHBOARD & PAGINATED ANALYTICS API
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

        if current_user.role != "MISD":
            effective_dept = current_user.department
        else:
            effective_dept = requested_dept

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
                "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M")
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
        print(f"Server Error in /api/analytics: {e}")
        return jsonify({
            "department": "ALL",
            "kpis": {"total": 0, "pos": 0, "neg": 0, "neu": 0},
            "pie_chart": "",
            "aspect_chart": "",
            "insights": [{"level": "Ready", "aspect": "System Initialized", "recommendation": "Ready for input."}],
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
        headers={"Content-Disposition": f"attachment;filename=ccc_sentiment_export_{dept.lower()}_{selected_year}_{selected_sem}.csv"}
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