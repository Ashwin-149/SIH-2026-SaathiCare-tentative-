"""Train the explainable demo distress-screening model on synthetic data only."""
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

FEATURES = ["mood", "anxiety", "stress", "sleep", "safety", "social", "wellbeing"]
OUT = Path(__file__).resolve().parents[1] / "data" / "risk_model.joblib"

def build_data(n=1800):
    rng = np.random.default_rng(26094)
    # answers use 1=best/least concern through 5=most concern
    x = rng.integers(1, 6, (n, len(FEATURES)))
    burden = (x[:,0]*.9 + x[:,1]*1.3 + x[:,2]*1.3 + x[:,3]*.8 + x[:,4]*1.6 + x[:,5]*.7 + x[:,6]*1.0)
    burden += rng.normal(0, 1.25, n)
    y = np.where(burden < 17.5, 0, np.where(burden < 24.5, 1, 2))
    return x, y

def train():
    OUT.parent.mkdir(exist_ok=True)
    x, y = build_data()
    model = RandomForestClassifier(n_estimators=160, max_depth=7, random_state=26094, class_weight="balanced")
    model.fit(x, y)
    joblib.dump({"model": model, "features": FEATURES, "labels": ["Low", "Moderate", "High"], "source": "synthetic demo data"}, OUT)
    print(f"Saved synthetic-data model to {OUT}")

if __name__ == "__main__": train()
