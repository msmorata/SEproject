import os
import re
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
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
# AUTHENTICATION CONFIGURATION
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
    department = db.Column(db.String(120), nullable=False, default="General")
    raw_text = db.Column(db.Text, nullable=False)
    cleaned_text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    aspect_breakdown = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# ==========================================
# NLP PIPELINE & ABSA CONFIGURATION (OFFLINE-READY)
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
        classifier = pipeline(
            "sentiment-analysis", 
            model="nlptown/bert-base-multilingual-uncased-sentiment"
        )
    except Exception as e:
        print(f"Fallback to default pipeline: {e}")
        classifier = pipeline("sentiment-analysis")

TAGLISH_LEXICON = {
    "positive": [
        "good", "great", "best", "clear", "helpful", "perfect", "nice",
        "mabait", "maayos", "magaling", "sulit", "malinaw", "approachable", "easy"
    ],
    "negative": [
        "bad", "worst", "hard", "useless", "hot", "slow", "late", "boring",
        "panget", "mahirap", "mainit", "magulo", "mabilis", "confusing", "fast", "sungit"
    ],
    "intensifiers": ["sobrang", "masyado", "very", "super", "really", "so"],
    "negations": ["not", "hindi", "di", "never", "wala"]
}

ASPECT_CATEGORIES = {
    "Instructional Delivery & Pedagogy": [
        "lecture", "turo", "explain", "speak", "speaks", "discussion", 
        "mabilis", "fast", "slow", "teaching", "lesson", "clear", "malinaw", "confusing"
    ],
    "Faculty Demeanor & Approachability": [
        "talk", "approachable", "mabait", "attitude", "sungit", 
        "easy", "friendly", "accommodating", "strict", "patient"
    ],
    "Campus Facilities & Infrastructure": [
        "room", "classroom", "fan", "electric fan", "aircon", "mainit", 
        "hot", "computer", "wifi", "internet", "projector", "lab", "laboratory"
    ]
}

def preprocess_taglish_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'[^\w\s,\.\-!?]', '', text)
    return text.strip()

def segment_compound_text(text):
    delimiters = r",\s*|\b(?:but|pero|kaso|kaso lang|however|although|while|yet)\b"
    clauses = re.split(delimiters, text, flags=re.IGNORECASE)
    cleaned_clauses = [c.strip() for c in clauses if len(c.strip()) > 3]
    return cleaned_clauses if cleaned_clauses else [text]

def detect_aspect(clause):
    clause_lower = clause.lower()
    for aspect, keywords in ASPECT_CATEGORIES.items():
        if any(k in clause_lower for k in keywords):
            return aspect
    return "General Academic Feedback"

def evaluate_clause(clause):
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

    has_pos = any(w in clause_lower for w in TAGLISH_LEXICON["positive"])
    has_neg = any(w in clause_lower for w in TAGLISH_LEXICON["negative"])
    has_negation = any(w in clause_lower for w in TAGLISH_LEXICON["negations"])
    has_intensifier = any(w in clause_lower for w in TAGLISH_LEXICON["intensifiers"])

    if has_negation:
        if has_pos:
            polarity = "Negative"
        elif has_neg:
            polarity = "Positive"

    explanation = f"BERT Confidence: {bert_score}."
    if has_intensifier:
        explanation += " Lexical intensifier detected."
    if has_negation:
        explanation += " Contextual negation modified polarity."

    return polarity, bert_score, explanation

def run_absa_pipeline(raw_comment):
    cleaned = preprocess_taglish_text(raw_comment)
    clauses = segment_compound_text(cleaned)
    breakdown = []
    polarities = []

    for clause in clauses:
        aspect = detect_aspect(clause)
        polarity, score, explanation = evaluate_clause(clause)
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
# APPLICATION CONTROLLER ROUTES
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
            return render_template('signup.html', error="All fields are required.")

        if User.query.filter_by(username=username).first():
            return render_template('signup.html', error="Username is already taken.")

        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully. Please log in.")
        return redirect(url_for('login'))

    return render_template('signup.html')

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

        return render_template('login.html', error="Invalid username or password.")

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    pos_count = Feedback.query.filter_by(sentiment='Positive').count()
    neg_count = Feedback.query.filter_by(sentiment='Negative').count()
    neu_count = Feedback.query.filter_by(sentiment='Neutral').count()
    total_count = Feedback.query.count()

    raw_logs = Feedback.query.order_by(Feedback.id.desc()).limit(20).all()
    logs = []
    for entry in raw_logs:
        try:
            parsed_breakdown = json.loads(entry.aspect_breakdown)
        except Exception:
            parsed_breakdown = []
        logs.append({
            "id": entry.id,
            "department": entry.department,
            "raw_text": entry.raw_text,
            "sentiment": entry.sentiment,
            "confidence": entry.confidence,
            "aspects": parsed_breakdown,
            "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M")
        })

    return render_template(
        'dashboard.html',
        username=current_user.username,
        pos=pos_count,
        neg=neg_count,
        neu=neu_count,
        total=total_count,
        logs=logs
    )

@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_api():
    data = request.get_json() or {}
    comment = data.get("comment", "").strip()
    department = data.get("department", "Department of Computing and Informatics")

    if not comment:
        return jsonify({"error": "No comment provided."}), 400

    cleaned, sentiment, score, breakdown = run_absa_pipeline(comment)

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)