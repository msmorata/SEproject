import os
import re
import csv
import io
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from transformers import pipeline

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
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Feedback(db.Model):
    __tablename__ = 'feedback_records'
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, default="DCI")
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
    category = db.Column(db.String(50), nullable=False)  # 'positive', 'negative', 'intensifiers', 'negations'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# SEED BASELINE LEXICON
# ==========================================
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
    seed_lexicon()

# ==========================================
# NLP PIPELINE & ABSA CONFIGURATION
# ==========================================
print("Loading BERT Sentiment Engine...")
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
        print(f"Fallback to default model: {e}")
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

    explanation = f"BERT Score: {bert_score}."
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
# PRESCRIPTIVE ANALYTICS ENGINE
# ==========================================
def compute_prescriptive_insights(records):
    if not records:
        return []

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
                        "recommendation": "Elevated facility grievances detected. Forward maintenance work order to General Services for room ventilation, PC lab setups, and electric fan maintenance."
                    })
                elif asp == "Instructional Delivery & Pedagogy":
                    insights.append({
                        "level": "Pedagogical Warning",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "High volume of pace/clarity concerns. Department dean should conduct syllabus pacing alignment and workshop on code-switched delivery."
                    })
                elif asp == "Faculty Demeanor & Approachability":
                    insights.append({
                        "level": "Faculty Advisory",
                        "aspect": asp,
                        "ratio": round(neg_ratio * 100, 1),
                        "recommendation": "Approachability concerns noted. Recommend peer coaching and scheduled consultation hours to improve student rapport."
                    })

    if not insights:
        insights.append({
            "level": "Stable Baseline",
            "aspect": "Cross-Departmental Performance",
            "ratio": 0,
            "recommendation": "Overall feedback metrics are within compliant pedagogical bounds. No critical operational triggers activated."
        })
    return insights

# ==========================================
# AUTHENTICATION ROUTES
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
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('auth.html', error="All fields are required.", mode="signup")
        if User.query.filter_by(username=username).first():
            return render_template('auth.html', error="Username is already taken.", mode="signup")
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully. Please sign in.")
        return redirect(url_for('login'))
    return render_template('auth.html', mode="signup")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        return render_template('auth.html', error="Invalid username or password.", mode="login")
    return render_template('auth.html', mode="login")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==========================================
# DASHBOARD & ANALYTICS CONTROLLER
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=current_user.username)

@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    dept = request.args.get('department', 'ALL').strip().upper()
    query = Feedback.query
    if dept != 'ALL':
        query = query.filter_by(department=dept)

    records = query.order_by(Feedback.id.desc()).all()
    pos = sum(1 for r in records if r.sentiment == 'Positive')
    neg = sum(1 for r in records if r.sentiment == 'Negative')
    neu = sum(1 for r in records if r.sentiment == 'Neutral')
    total = len(records)

    # Calculate aspect breakdowns
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

    return jsonify({
        "department": dept,
        "kpis": {"total": total, "pos": pos, "neg": neg, "neu": neu},
        "aspect_breakdown": aspect_counts,
        "insights": insights,
        "logs": recent_logs
    })

@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_api():
    data = request.get_json() or {}
    comment = data.get("comment", "").strip()
    department = data.get("department", "DCI").upper()

    if not comment:
        return jsonify({"error": "No comment provided."}), 400

    lexicon = get_active_lexicon()
    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)

    entry = Feedback(
        department=department,
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
        "raw": comment,
        "sentiment": sentiment,
        "confidence_score": score,
        "aspect_breakdown": breakdown
    })

# ==========================================
# BATCH CSV PROCESSING & EXPORT
# ==========================================
@app.route('/api/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    default_dept = request.form.get('department', 'DCI').upper()

    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be a valid .csv file."}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"))
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        return jsonify({"error": "Invalid or empty CSV header."}), 400

    # Auto-detect text column
    text_col = None
    for col in reader.fieldnames:
        if any(keyword in col.lower() for keyword in ["comment", "feedback", "narrative", "text", "review"]):
            text_col = col
            break
    if not text_col:
        text_col = reader.fieldnames[0]

    dept_col = None
    for col in reader.fieldnames:
        if any(keyword in col.lower() for keyword in ["dept", "department", "program"]):
            dept_col = col
            break

    lexicon = get_active_lexicon()
    processed_count = 0

    for row in reader:
        comment = row.get(text_col, '').strip()
        if not comment:
            continue

        dept = row.get(dept_col, default_dept).strip().upper() if dept_col else default_dept
        if dept not in ["DCI", "DBA", "DTE", "DAS"]:
            dept = default_dept

        cleaned, sentiment, score, breakdown = run_absa_pipeline(comment, lexicon)
        entry = Feedback(
            department=dept,
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
    dept = request.args.get('department', 'ALL').strip().upper()
    query = Feedback.query
    if dept != 'ALL':
        query = query.filter_by(department=dept)

    records = query.order_by(Feedback.id.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Department", "Raw Feedback", "Sentiment", "Confidence", "Aspect Breakdown", "Timestamp"])

    for r in records:
        writer.writerow([r.id, r.department, r.raw_text, r.sentiment, r.confidence, r.aspect_breakdown, r.timestamp])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=ccc_sentiment_export_{dept.lower()}.csv"}
    )

# ==========================================
# DYNAMIC LEXICON & SLANG MANAGEMENT
# ==========================================
@app.route('/api/lexicon', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_lexicon():
    if request.method == 'GET':
        terms = LexiconTerm.query.order_by(LexiconTerm.id.desc()).all()
        return jsonify([{"id": t.id, "word": t.word, "category": t.category} for t in terms])

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