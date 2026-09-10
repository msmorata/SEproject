import os
import re
import csv
import io
import json
import base64
import random
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
    role = db.Column(db.String(50), nullable=False, default="Faculty")  # "MISD" or "Faculty"
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.Text, nullable=True)
    verification_code = db.Column(db.String(6), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Feedback(db.Model):
    __tablename__ = 'feedback_records'
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, default="DCI")
    program = db.Column(db.String(150), nullable=True, default="General")
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
        "mabait", "maayos", "magaling", "sulit", "malinaw", "approachable", "easy", "petiks", "chill"
    ],
    "negative": [
        "bad", "worst", "hard", "useless", "hot", "slow", "late", "boring", "sabaw", "lutang",
        "panget", "mahirap", "mainit", "magulo", "mabilis", "confusing", "fast", "sungit", "kupal"
    ],
    "intensifiers": ["sobrang", "masyado", "very", "super", "really", "so", "grabe", "napaka"],
    "negations": ["not", "hindi", "di", "never", "wala"]
}

def seed_lexicon():
    if LexiconTerm.query.count() == 0:
        for cat, words in DEFAULT_LEXICON.items():
            for w in words:
                db.session.add(LexiconTerm(word=w.lower(), category=cat))
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
            "ALTER TABLE feedback_records ADD COLUMN IF NOT EXISTS program VARCHAR(150) DEFAULT 'General';"
        ]
        for q in alter_queries:
            db.session.execute(text(q))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Schema upgrade notice: {e}")
    seed_lexicon()

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
        "mabilis", "fast", "slow", "teaching", "lesson", "clear", "malinaw", "confusing", "exam", "quiz", "task"
    ],
    "Faculty Demeanor & Approachability": [
        "talk", "approachable", "mabait", "attitude", "sungit",
        "easy", "friendly", "accommodating", "strict", "patient", "galit", "snob"
    ],
    "Campus Facilities & Infrastructure": [
        "room", "classroom", "fan", "electric fan", "aircon", "mainit",
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
    delimiters = r",\s*|\b(?:but|pero|kaso|kaso lang|however|although|while|yet)\b"
    clauses = re.split(delimiters, text, flags=re.IGNORECASE)
    cleaned = [c.strip() for c in clauses if len(c.strip()) > 3]
    return cleaned if cleaned else [text]

def detect_aspect(clause):
    clause_lower = clause.lower()
    for aspect, keywords in ASPECT_CATEGORIES.items():
        if any(k in clause_lower for k in keywords):
            return aspect
    return "General Academic Feedback"

def evaluate_clause(clause, lexicon):
    clause_lower = clause.lower()
    bert_result = classifier(clause[:512])[0]
    bert_label = bert_result['label']
    bert_score = round(bert_result['score'], 4)

    if "star" in bert_label.lower():
        stars = int(bert_label[0])
        if stars >= 4:
            polarity = "Positive"
        elif stars == 3:
            polarity = "Neutral"
        else:
            polarity = "Negative"
    else:
        raw_upper = bert_label.upper()
        if "POS" in raw_upper:
            polarity = "Positive"
        elif "NEG" in raw_upper:
            polarity = "Negative"
        else:
            polarity = "Neutral"

    tokens = set(re.findall(r'\b\w+\b', clause_lower))
    has_pos = bool(tokens & lexicon["positive"])
    has_neg = bool(tokens & lexicon["negative"])
    has_negation = bool(tokens & lexicon["negations"])
    has_intensifier = bool(tokens & lexicon["intensifiers"])

    if has_negation:
        if has_pos:
            polarity = "Negative"
        elif has_neg:
            polarity = "Positive"

    explanation = f"BERT Confidence: {bert_score}."
    if has_intensifier:
        explanation += " Slang intensifier detected."
    if has_negation:
        explanation += " Lexical negation modified polarity."

    return polarity, bert_score, explanation

def run_absa_pipeline(raw_comment, lexicon=None):
    if lexicon is None:
        lexicon = get_active_lexicon()
    cleaned = preprocess_taglish_text(raw_comment)
    clauses = segment_compound_text(cleaned)
    breakdown = []
    polarities = []

    for clause in clauses:
        aspect = detect_aspect(clause)
        polarity, score, explanation = evaluate_clause(clause, lexicon)
        polarities.append(polarity)
        breakdown.append({
            "aspect": aspect,
            "clause": clause,
            "polarity": polarity,
            "score": score,
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
            ax.pie([1], colors=['#334155'], wedgeprops={'edgecolor': '#0f1a30', 'linewidth': 2, 'width': 0.42})
        else:
            counts, colors, labels = [], [], []
            if pos > 0: counts.append(pos); colors.append('#10b981'); labels.append(f'{pos}')
            if neg > 0: counts.append(neg); colors.append('#f43f5e'); labels.append(f'{neg}')
            if neu > 0: counts.append(neu); colors.append('#f59e0b'); labels.append(f'{neu}')

            pie_out = ax.pie(
                counts,
                labels=labels,
                colors=colors,
                autopct='%1.0f%%',
                pctdistance=0.72,
                labeldistance=1.12,
                startangle=135,
                textprops={'color': '#94a3b8', 'fontsize': 8, 'weight': 'bold'},
                wedgeprops={'edgecolor': '#0f1a30', 'linewidth': 2.5, 'width': 0.42}
            )
            if len(pie_out) == 3:
                for at in pie_out[2]:
                    at.set_color('#ffffff')
                    at.set_fontsize(7.5)
                    at.set_weight('bold')

        ax.text(0, 0, f'{total}\nLOGS', ha='center', va='center',
                color='#f8fafc', fontsize=9, fontweight='800', linespacing=1.2)

        ax.axis('equal')
        fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)

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
                pol = item.get("polarity")
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
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        department = request.form.get('department', 'DCI').strip().upper()
        
        programs_list = request.form.getlist('program')
        cleaned_programs = []
        for p in programs_list:
            clean_val = p.strip()
            if clean_val and clean_val not in cleaned_programs:
                cleaned_programs.append(clean_val)

        if not username or not email or not password:
            return render_template('auth.html', error="All fields are required.", mode="signup")

        if not email.endswith('@ccc.edu.ph'):
            return render_template(
                'auth.html',
                error="Access restricted: Please register using an official institutional email (@ccc.edu.ph).",
                mode="signup"
            )

        if User.query.filter_by(username=username).first():
            return render_template('auth.html', error="Username is already taken.", mode="signup")

        if User.query.filter_by(email=email).first():
            return render_template('auth.html', error="Email address is already registered.", mode="signup")

        code = str(random.randint(100000, 999999))
        role = "MISD" if department == "MISD" else "Faculty"
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

        print("\n" + "="*55)
        print(" [CCC REGISTRATION AUTHENTICATOR CODE] ")
        print(f" USER: {username} | EMAIL: {email}")
        print(f" ROLE: {role} | DEPT: {department}")
        print(f" PROGRAMS: {assigned_program_str}")
        print(f" 6-DIGIT VERIFICATION CODE: {code}")
        print("="*55 + "\n")

        session['pending_verification_email'] = email
        return render_template('auth.html', mode="verify", email=email, dev_code=code)

    return render_template('auth.html', mode="signup")

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
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter((User.username == login_id) | (User.email == login_id.lower())).first()

        if user and user.check_password(password):
            if not user.is_verified:
                session['pending_verification_email'] = user.email
                return render_template(
                    'auth.html', 
                    error="Account unverified. Please confirm your 6-digit email code.", 
                    mode="verify", 
                    email=user.email,
                    dev_code=user.verification_code
                )

            login_user(user)
            return redirect(url_for('dashboard'))

        return render_template('auth.html', error="Invalid credentials provided.", mode="login")

    return render_template('auth.html', mode="login")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==========================================
# DASHBOARD & ANALYTICS CONTROLLERS
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
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

        if current_user.role != "MISD":
            effective_dept = current_user.department
        else:
            effective_dept = requested_dept

        query = Feedback.query
        if effective_dept != 'ALL':
            query = query.filter_by(department=effective_dept)

        records = query.order_by(Feedback.id.desc()).all()
        pos = sum(1 for r in records if r.sentiment == 'Positive')
        neg = sum(1 for r in records if r.sentiment == 'Negative')
        neu = sum(1 for r in records if r.sentiment == 'Neutral')
        total = len(records)

        aspect_counts = {
            "Instructional Delivery": {"pos": 0, "neg": 0, "neu": 0},
            "Faculty Demeanor": {"pos": 0, "neg": 0, "neu": 0},
            "Facilities": {"pos": 0, "neg": 0, "neu": 0}
        }

        recent_logs = []
        for entry in records[:25]:
            try:
                parsed = json.loads(entry.aspect_breakdown)
            except Exception:
                parsed = []
            recent_logs.append({
                "id": entry.id,
                "department": entry.department,
                "program": entry.program or "General",
                "raw_text": entry.raw_text,
                "sentiment": entry.sentiment,
                "confidence": entry.confidence,
                "aspects": parsed,
                "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M")
            })

        for r in records:
            try:
                items = json.loads(r.aspect_breakdown)
                for item in items:
                    asp = item.get("aspect", "")
                    pol = item.get("polarity", "")
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

        insights = compute_prescriptive_insights(records)
        pie_b64 = generate_matplotlib_pie(pos, neg, neu)
        bar_b64 = generate_matplotlib_bar(aspect_counts)

        return jsonify({
            "department": effective_dept,
            "kpis": {"total": total, "pos": pos, "neg": neg, "neu": neu},
            "pie_chart": pie_b64,
            "aspect_chart": bar_b64,
            "insights": insights,
            "logs": recent_logs
        })
    except Exception as e:
        print(f"Server Error in /api/analytics: {e}")
        return jsonify({
            "department": "ALL",
            "kpis": {"total": 0, "pos": 0, "neg": 0, "neu": 0},
            "pie_chart": "",
            "aspect_chart": "",
            "insights": [{"level": "Ready", "aspect": "System Initialized", "recommendation": "Ready for input."}],
            "logs": []
        }), 200

# Restricted strictly to MISD administrators for testing & auditing
@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_api():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized. Narrative diagnostic testing is restricted to MISD clearance."}), 403

    data = request.get_json() or {}
    comment = data.get("comment", "").strip()
    department = data.get("department", "DCI").upper()
    program = data.get("program", "Institutional Testing")

    if not comment:
        return jsonify({"error": "No comment provided."}), 400

    lexicon = get_active_lexicon()
    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)

    entry = Feedback(
        department=department,
        program=program,
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
        "raw": comment,
        "sentiment": sentiment,
        "confidence_score": score,
        "aspect_breakdown": breakdown
    })

# Ingestion restricted strictly to MISD institutional personnel
@app.route('/api/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if current_user.role != "MISD":
        return jsonify({"error": "Unauthorized. Batch survey ingestion is restricted to MISD clearance."}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    default_dept = request.form.get('department', 'DCI').upper()
    default_prog = request.form.get('program', 'General')

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

    dept_col = None
    for col in reader.fieldnames:
        if any(keyword in col.lower() for keyword in ["dept", "department", "college"]):
            dept_col = col
            break

    prog_col = None
    for col in reader.fieldnames:
        if any(keyword in col.lower() for keyword in ["prog", "program", "course"]):
            prog_col = col
            break

    lexicon = get_active_lexicon()
    processed_count = 0

    for row in reader:
        comment = row.get(text_col, '').strip()
        if not comment:
            continue

        assigned_dept = row.get(dept_col, default_dept).strip().upper() if dept_col else default_dept
        assigned_prog = row.get(prog_col, default_prog).strip() if prog_col else default_prog

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)
        entry = Feedback(
            department=assigned_dept,
            program=assigned_prog,
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
    query = Feedback.query
    if dept != 'ALL':
        query = query.filter_by(department=dept)

    records = query.order_by(Feedback.id.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Department", "Program", "Raw Feedback", "Sentiment", "Confidence", "Aspect Breakdown", "Timestamp"])

    for r in records:
        writer.writerow([r.id, r.department, r.program, r.raw_text, r.sentiment, r.confidence, r.aspect_breakdown, r.timestamp])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=ccc_sentiment_export_{dept.lower()}.csv"}
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