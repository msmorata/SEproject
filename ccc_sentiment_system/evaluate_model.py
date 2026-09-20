import os
import sys
import csv
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Import NLP pipeline and lexicon directly from app.py to ensure 100% logic parity
try:
    from app import app, run_absa_pipeline, get_active_lexicon, DEFAULT_LEXICON
except ImportError as e:
    print(f"Error importing from app.py: {e}")
    print("Ensure evaluate_model.py is placed in the same directory as app.py.")
    sys.exit(1)

try:
    from sklearn.metrics import (
        accuracy_score,
        precision_recall_fscore_support,
        classification_report,
        confusion_matrix
    )
except ImportError:
    print("scikit-learn is required for statistical metrics. Run: pip install scikit-learn")
    sys.exit(1)

# ==========================================================
# BUILT-IN CCC TAGLISH GOLD-STANDARD BENCHMARK DATASET
# (Balanced across Positive, Negative, and Neutral polarities)
# ==========================================================
BENCHMARK_DATASET = [
    # --- POSITIVE SAMPLES ---
    {
        "text": "Sobrang galing magturo at mag-explain ni Sir sa discussion, malinaw ang bawat lesson.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Mabait si Ma'am at approachable tuwing may questions after class.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Faculty Demeanor & Approachability"
    },
    {
        "text": "Ubod ng bait ni prof at napakahusay mag-lecture sa laboratory.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Faculty Demeanor & Approachability"
    },
    {
        "text": "Maayos ang presentation ng slides at solid ang hands-on activities sa programming.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Malinaw magsalita si Sir at laging ready sumagot kapag nagtatanong ang mga estudyante.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Very approachable si Ma'am, chill lang ang discussion at madaling maintindihan.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Faculty Demeanor & Approachability"
    },
    {
        "text": "Goods na goods ang facilities sa bagong computer lab, mabilis ang internet.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Maayos ang ventilation sa room at gumagana lahat ng electric fan.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Petiks at relax ang vibe sa room pero marami kaming natututunan dahil magaling magturo.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Masipag pumasok si Sir at napakalinaw magbigay ng grading rubrics.",
        "ground_truth_sentiment": "Positive",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },

    # --- NEGATIVE SAMPLES ---
    {
        "text": "Masyadong mabilis magturo si Ma'am at sobrang confusing ng lecture presentation.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Masungit si Sir at laging galit kapag may nagtatanong sa lesson.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Faculty Demeanor & Approachability"
    },
    {
        "text": "Napakainit sa loob ng classroom dahil sira ang electric fan at walang hangin.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Laging nagha-hang ang mga computer units sa laboratory at mabagal ang wifi.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Sabaw mag-explain si Sir, hindi malinaw magbigay ng project requirements.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Akala namin chill at mabait si Ma'am, eme lang pala dahil sobrang bagsak magpa-exam.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Mabait daw si Sir, charot lang pala kasi napakasungit kapag consultation.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Faculty Demeanor & Approachability"
    },
    {
        "text": "Hindi maayos magturo at laging late pumasok sa klase.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Magulo ang syllabus at walang maayos na chairs sa laboratory room.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Boring ang klase at puro basa lang sa PowerPoint slides na hindi maipaliwanag nang maayos.",
        "ground_truth_sentiment": "Negative",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },

    # --- NEUTRAL / FACTUAL SAMPLES ---
    {
        "text": "Ang klase ay gaganapin tuwing Martes at Huwebes mula alas-otso ng umaga sa Room 304.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Nagbigay si Sir ng tatlong modules para sa darating na midterm coverage.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Mayroong apatnapung estudyante ang naka-enroll sa kursong ito ngayong semestre.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "General Academic Feedback"
    },
    {
        "text": "Ang submission ng documentation ay nakatakda sa susunod na Lunes bago mag-alas-singko.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Ginamit ang projector sa room para sa reporting ng unang grupo kanina.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Nasa Google Classroom ang syllabus at schedule ng departmental examinations.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Natapos ang meeting para sa curriculum review noong nakaraang Biyernes.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "General Academic Feedback"
    },
    {
        "text": "Ang attendance ay chine-check gamit ang class list bago magsimula ang lecture.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    },
    {
        "text": "Bumalik ang kuryente sa campus kaninang tanghali pagkatapos ng maintenance.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Campus Facilities & Infrastructure"
    },
    {
        "text": "Sinabi ng propesor na dalhin ang textbook sa susunod na sesyon.",
        "ground_truth_sentiment": "Neutral",
        "ground_truth_aspect": "Instructional Delivery & Pedagogy"
    }
]

def load_data(filepath=None):
    if filepath and os.path.exists(filepath):
        print(f"\n[+] Loading external benchmark CSV from: {filepath}")
        dataset = []
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dataset.append({
                    "text": row.get("text") or row.get("raw_text") or row.get("comment"),
                    "ground_truth_sentiment": row.get("ground_truth_sentiment") or row.get("sentiment"),
                    "ground_truth_aspect": row.get("ground_truth_aspect") or row.get("aspect", "General Academic Feedback")
                })
        return dataset
    else:
        print("\n[+] Using built-in CCC Taglish Gold-Standard Dataset (30 balanced records).")
        return BENCHMARK_DATASET

def generate_confusion_matrix_plot(cm, labels, output_filename="confusion_matrix.png"):
    fig, ax = plt.subplots(figsize=(5.5, 4.5), dpi=300)
    cax = ax.matshow(cm, cmap=plt.cm.Blues, alpha=0.85)

    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(x=j, y=i, s=cm[i, j], va='center', ha='center',
                    size=12, weight='bold',
                    color="white" if cm[i, j] > (cm.max() / 2) else "black")

    fig.colorbar(cax)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=10, weight='bold')
    ax.set_yticklabels(labels, fontsize=10, weight='bold')

    plt.title("CCC Multilingual ABSA Confusion Matrix", fontsize=11, weight='bold', pad=15)
    plt.xlabel("Predicted Sentiment Label", fontsize=10, weight='bold')
    plt.ylabel("Ground Truth (Actual) Label", fontsize=10, weight='bold')
    plt.tight_layout()

    plt.savefig(output_filename, dpi=300)
    plt.close()
    print(f"[+] Confusion Matrix visualization saved to: {output_filename}")

def evaluate_pipeline(dataset):
    print(f"[+] Executing inference on {len(dataset)} student feedback records...")

    # Fetch active database lexicon or fall back cleanly
    try:
        with app.app_context():
            lexicon = get_active_lexicon()
    except Exception:
        print("[-] Notice: Database uncontactable. Utilizing DEFAULT_LEXICON fallback dictionary.")
        lexicon = {cat: set(words) for cat, words in DEFAULT_LEXICON.items()}

    y_true_sentiment = []
    y_pred_sentiment = []

    y_true_aspect = []
    y_pred_aspect = []

    for idx, item in enumerate(dataset, start=1):
        raw_text = item["text"]
        actual_sentiment = item["ground_truth_sentiment"].strip().capitalize()
        actual_aspect = item.get("ground_truth_aspect", "General Academic Feedback").strip()

        # Run through the identical pipeline used by app.py
        cleaned, pred_sentiment, avg_conf, breakdown = run_absa_pipeline(raw_text, lexicon)

        pred_sentiment_cap = pred_sentiment.strip().capitalize()

        # Aspect attribution from top clause
        pred_aspect = breakdown[0]["aspect"] if breakdown else "General Academic Feedback"

        y_true_sentiment.append(actual_sentiment)
        y_pred_sentiment.append(pred_sentiment_cap)

        y_true_aspect.append(actual_aspect)
        y_pred_aspect.append(pred_aspect)

    # ==========================================
    # STATISTICAL METRICS CALCULATION
    # ==========================================
    labels = ["Positive", "Negative", "Neutral"]
    
    acc = accuracy_score(y_true_sentiment, y_pred_sentiment)
    precisions, recalls, f1s, supports = precision_recall_fscore_support(
        y_true_sentiment, y_pred_sentiment, labels=labels, zero_division=0
    )

    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        y_true_sentiment, y_pred_sentiment, average='macro', zero_division=0
    )

    weighted_precision, weighted_recall, weighted_f1, _ = precision_recall_fscore_support(
        y_true_sentiment, y_pred_sentiment, average='weighted', zero_division=0
    )

    cm = confusion_matrix(y_true_sentiment, y_pred_sentiment, labels=labels)

    # ==========================================
    # CONSOLE & CHAPTER 4 DELIVERABLE OUTPUT
    # ==========================================
    print("\n" + "="*70)
    print("      CITY COLLEGE OF CALAMBA — NLP ABSA BENCHMARK REPORT      ")
    print("="*70)

    print(f"\nTotal Gold-Standard Samples Evaluated: {len(dataset)}")
    print(f"Overall Classification Accuracy:       {acc * 100:.2f}%")
    print(f"Overall Macro F1-Score:                {macro_f1:.4f}")
    print(f"Overall Weighted F1-Score:             {weighted_f1:.4f}\n")

    # Thesis Objective Compliance Checks
    acc_target_met = acc >= 0.85
    f1_target_met = macro_f1 >= 0.80

    print("THESIS TARGET VERIFICATION:")
    print(f" -> Accuracy >= 85.0%: {'PASSED' if acc_target_met else 'FAILED'} ({acc*100:.2f}%)")
    print(f" -> F1-Score >= 0.80:  {'PASSED' if f1_target_met else 'FAILED'} ({macro_f1:.4f})\n")

    print("-"*70)
    print("TABLE FOR CHAPTER 4: PERFORMANCE METRICS ACROSS POLARITIES")
    print("-"*70)
    print(f"{'Polarity Class':<15} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10} | {'Support':<8}")
    print("-" * 64)
    for i, label in enumerate(labels):
        print(f"{label:<15} | {precisions[i]:<10.4f} | {recalls[i]:<10.4f} | {f1s[i]:<10.4f} | {supports[i]:<8}")
    print("-" * 64)
    print(f"{'Macro Average':<15} | {macro_precision:<10.4f} | {macro_recall:<10.4f} | {macro_f1:<10.4f} | {len(dataset):<8}")
    print(f"{'Weighted Avg':<15} | {weighted_precision:<10.4f} | {weighted_recall:<10.4f} | {weighted_f1:<10.4f} | {len(dataset):<8}")
    print("-"*70)

    header = "Actual / Pred"
    print("\nCONFUSION MATRIX (Predicted columns vs Actual rows):")
    print(f"{header:<15} | {'Positive':<10} | {'Negative':<10} | {'Neutral':<10}")
    print("-" * 52)
    for i, label in enumerate(labels):
        print(f"{label:<15} | {cm[i][0]:<10} | {cm[i][1]:<10} | {cm[i][2]:<10}")
    print("-" * 52)

    # Save heatmap plot
    generate_confusion_matrix_plot(cm, labels)

    print("\n[+] Benchmark evaluation completed successfully.\n")

if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else None
    dataset = load_data(csv_arg)
    evaluate_pipeline(dataset)