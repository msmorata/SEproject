import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix, classification_report, accuracy_score, f1_score
from app import app, run_absa_pipeline, get_active_lexicon

# Standardized Ground-Truth Validation Set (Taglish, English, Sarcastic & Compound Nuances)
EVALUATION_DATASET = [
    # Positive Sentences
    ("Sobrang galing magturo ni Sir, malinaw ang bawat lesson at hands-on activities.", "Positive"),
    ("Mabait si Ma'am at very approachable kapag may hindi kami maintindihan.", "Positive"),
    ("Clear and concise lectures. The slides provided are very helpful.", "Positive"),
    ("Goods na goods ang facilities sa computer laboratory, malamig ang aircon.", "Positive"),
    ("Masipag mag-consult si Sir bago magpa-exam, sobrang laking tulong.", "Positive"),
    ("Petiks pero may natutunan, maayos makipag-usap sa mga estudyante.", "Positive"),
    ("Sulit ang tuition, magaganda ang projector at upuan sa DCI building.", "Positive"),
    ("Prof is very professional and provides constructive feedback on projects.", "Positive"),

    # Negative Sentences
    ("Sobrang bilis magturo ni Sir, hindi namin ma-gets ang coding examples.", "Negative"),
    ("Laging late pumasok si Ma'am tapos nagagalit pa pag nagtanong.", "Negative"),
    ("Mainit sa classroom, sira ang electric fan at madilim ang projector.", "Negative"),
    ("Boring mag-discuss, binabasa lang yung PowerPoint slide per slide.", "Negative"),
    ("Masungit ang instructor tuwing submission ng laboratory exercise.", "Negative"),
    ("Walang kwenta ang Wi-Fi connection sa campus, hindi magamit sa research.", "Negative"),
    ("Magulo magpa-quiz, walang kaugnayan sa na-discuss nung prelims.", "Negative"),
    ("The pacing of the lecture is very fast and confusing for beginners.", "Negative"),

    # Nuanced, Sarcastic & Slang Clauses
    ("Ang galing mo magturo ma'am, eme lang!", "Negative"), # Sarcasm Invalidation
    ("Solid ang explanation ni Sir pero charot lang pala.", "Negative"), # Sarcasm Invalidation
    ("Mabait si Sir pero hindi nagtuturo nang maayos tuwing lecture.", "Negative"), # Compound Inversion
    ("Hindi malinaw ang instructions sa final project requirements.", "Negative"), # Negator
    ("Sobrang init sa room pero mabait naman si Sir.", "Neutral"), # Compound Split Balancing
    ("The examination covered chapters one to five as announced.", "Neutral"), # Informational
    ("The lecture started at exactly 8:00 AM in Room 302.", "Neutral"), # Informational
    ("Hindi masungit si Ma'am kapag tinatanong sa office.", "Positive") # Inverted Negative
]

def benchmark_roberta_pipeline():
    print("=" * 65)
    print("  CITY COLLEGE OF CALAMBA — INSTITUTIONAL ABSA BENCHMARK")
    print("  Model Architecture: XLM-RoBERTa + Dynamic Taglish Rule Engine")
    print("=" * 65)

    y_true = []
    y_pred = []

    with app.app_context():
        lexicon = get_active_lexicon()

    print(f"\n[*] Evaluating pipeline over {len(EVALUATION_DATASET)} ground-truth samples...\n")

    for idx, (sentence, ground_truth) in enumerate(EVALUATION_DATASET, 1):
        _, predicted_sentiment, confidence, breakdown = run_absa_pipeline(sentence, lexicon)
        y_true.append(ground_truth)
        y_pred.append(predicted_sentiment)

        match_indicator = "✓" if predicted_sentiment == ground_truth else "✗"
        print(f"[{idx:02d}] {match_indicator} [{predicted_sentiment:<8}] (Expected: {ground_truth:<8} | Conf: {confidence}) -> \"{sentence[:45]}...\"")

    labels = ["Positive", "Negative", "Neutral"]
    acc = accuracy_score(y_true, y_pred)
    macro_f1 = f1_score(y_true, y_pred, average='macro')
    weighted_f1 = f1_score(y_true, y_pred, average='weighted')

    print("\n" + "=" * 65)
    print("  EVALUATION PERFORMANCE METRICS")
    print("=" * 65)
    print(f"  • Model Accuracy:      {acc * 100:.2f}%")
    print(f"  • Macro F1-Score:      {macro_f1:.4f}")
    print(f"  • Weighted F1-Score:   {weighted_f1:.4f}")
    print("-" * 65)
    print("\nClassification Report:\n")
    print(classification_report(y_true, y_pred, target_names=labels, zero_division=0))

    # Generate Confusion Matrix Figure
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    fig, ax = plt.subplots(figsize=(6, 5), dpi=300, facecolor='#0f1a30')
    ax.set_facecolor('#070d1d')

    cax = ax.matshow(cm, cmap=plt.cm.Blues, alpha=0.85)

    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(x=j, y=i, s=cm[i, j], va='center', ha='center',
                    fontsize=14, fontweight='bold',
                    color='#f8fafc' if cm[i, j] > (cm.max() / 2) else '#94a3b8')

    fig.colorbar(cax)
    ax.set_xticks([0, 1, 2])
    ax.set_yticks([0, 1, 2])
    ax.set_xticklabels(labels, fontsize=10, fontweight='bold', color='#f8fafc')
    ax.set_yticklabels(labels, fontsize=10, fontweight='bold', color='#f8fafc')

    ax.tick_params(axis='both', which='both', length=0)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('rgba(255,255,255,0.1)')
    ax.spines['left'].set_color('rgba(255,255,255,0.1)')

    plt.title("XLM-RoBERTa ABSA Confusion Matrix", color='#f8fafc', fontsize=12, fontweight='bold', pad=20)
    plt.xlabel("Predicted Polarity", color='#94a3b8', fontsize=10, labelpad=10)
    plt.ylabel("Ground Truth Polarity", color='#94a3b8', fontsize=10, labelpad=10)

    output_path = "confusion_matrix.png"
    plt.tight_layout()
    plt.savefig(output_path, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()

    print(f"[+] Confusion matrix plot successfully saved to: {os.path.abspath(output_path)}\n")

if __name__ == "__main__":
    benchmark_roberta_pipeline()