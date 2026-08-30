"""Train the SaathiCare prototype risk model on synthetic data only."""
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

FEATURES = [
    "mood", "anxiety", "stress", "sleep", "safety", "social", "wellbeing",
    "functioning", "threat", "court_stress", "financial_hardship"
]
OUT = Path(__file__).resolve().parents[1] / "data" / "risk_model.joblib"


def build_data(n=3600):
    rng = np.random.default_rng(26094)
    x = rng.integers(1, 6, (n, len(FEATURES)))
    burden = (
        x[:, 0] * 0.9 + x[:, 1] * 1.2 + x[:, 2] * 1.2 + x[:, 3] * 0.8 +
        x[:, 4] * 1.7 + x[:, 5] * 0.8 + x[:, 6] * 0.9 + x[:, 7] * 0.8 +
        x[:, 8] * 1.6 + x[:, 9] * 0.9 + x[:, 10] * 0.7
    )
    burden += rng.normal(0, 1.8, n)
    y = np.where(burden < 20, 0, np.where(burden < 27, 1, np.where(burden < 34, 2, 3)))
    return x, y


def train():
    OUT.parent.mkdir(exist_ok=True)
    x, y = build_data()
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=26094, stratify=y
    )
    model = RandomForestClassifier(
        n_estimators=220, max_depth=8, random_state=26094,
        class_weight="balanced", min_samples_leaf=3
    )
    model.fit(x_train, y_train)
    pred = model.predict(x_test)
    acc = accuracy_score(y_test, pred)
    p, r, f1, _ = precision_recall_fscore_support(y_test, pred, average="weighted", zero_division=0)
    artifact = {
        "model": model,
        "features": FEATURES,
        "labels": ["Low", "Moderate", "High", "Urgent"],
        "source": "synthetic demo data only",
        "metrics": {"accuracy": round(float(acc), 4), "precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f1), 4)},
    }
    joblib.dump(artifact, OUT)
    print(f"Saved model to {OUT}")
    print(artifact["metrics"])
    return artifact

if __name__ == "__main__": train()
