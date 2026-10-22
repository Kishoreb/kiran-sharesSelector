#!/usr/bin/env python3
"""
Governance-flag second opinion (shortlisting doc, section 4).

qualitative.py finds red flags with regular expressions. They catch nearly everything but also produce
false positives (a broker "cuts rating", a bid for an insolvent rival, boilerplate IBC wording). This module
trains a small text classifier that answers: "given this flag type and this text, is it a genuine concern?"

How it is used:
  * The regexes stay the candidate generator (recall). The model only DEMOTES a flag one severity step
    (High -> Medium -> Low) when it is confident the flag is a false positive. It never deletes or promotes.
  * Every flag keeps `ml_prob` (probability it is genuine) and `ml_note`, so you can still see and verify it.

Training data = SEED (below, a small starter set) + your own reviewed rows. Review the "Governance flags" sheet
written by holdings_analysis.py, fill the `label` column (1 = genuine, 0 = false positive), then:

    python gov_classifier.py import-sheet Kiran_2026-06_holdings_analysis.xlsx
    python gov_classifier.py train                     # TF-IDF + logistic regression (scikit-learn only)
    python gov_classifier.py train --embedder ProsusAI/finbert   # PyTorch sentence embeddings + logistic regression
    python gov_classifier.py predict "Nomura cuts rating on Siemens to neutral" --flag rating_downgrade

    python holdings_analysis.py holdings.xls --gov-model gov_model.pkl

The seed set alone is a demo: with only a few dozen examples the model is weak. Add reviewed rows (100+ is a
sensible target) and read the cross-validation report that `train` prints, in particular the line that says how
many genuine flags would have been wrongly demoted.
"""

import argparse
import csv
import os
import pickle
import sys
import time

DEFAULT_LABELS = "governance_labels.csv"
DEFAULT_MODEL = "gov_model.pkl"
DEMOTE_BELOW = 0.35            # probability of "genuine" below which a flag is demoted one step
MIN_LABELS = 30
MIN_PER_CLASS = 8
SEVERITY_DOWN = {"High": "Medium", "Medium": "Low", "Low": "Low"}

# (flag, text, label)   label 1 = genuine concern for that flag type, 0 = false positive.
# Several are verbatim cases seen in real runs (see test_sources.py); the rest are typical phrasings.
SEED = [
    ("auditor_resignation", "Intimation: the Company has received the resignation of M/s XYZ & Co as its statutory auditors", 1),
    ("auditor_resignation", "Auditor resigns citing lack of information", 1),
    ("auditor_resignation", "Resignation of Statutory Auditors of the Company; resignation letter received citing pre-occupation", 1),
    ("qualified_audit", "Auditor flags qualified opinion on FY25 accounts", 1),
    ("qualified_audit", "Auditors report contains an adverse opinion on the consolidated financial statements", 1),
    ("sebi_action", "SEBI slaps penalty on promoter of Test", 1),
    ("sebi_action", "SEBI probe into insider trading", 1),
    ("sebi_action", "SEBI issues show cause notice to the company over disclosure lapses", 1),
    ("sebi_action", "SEBI bars promoters from the securities market for two years", 1),
    ("sebi_action", "Company clarifies it has received no notice from SEBI regarding media reports of a probe", 0),
    ("fraud_probe", "ED raids offices of Test Ltd", 1),
    ("fraud_probe", "Forensic audit ordered amid fraud allegations against management", 1),
    ("fraud_probe", "CBI books company officials in bank fraud case", 1),
    ("fraud_probe", "Company says no investigation is pending; strengthens fraud prevention controls after industry-wide card fraud probe", 0),
    ("pledge_invocation", "Lenders invoke pledge on promoter shares", 1),
    ("pledge_invocation", "Pledge invoked on 3% promoter stake by lender", 1),
    ("insolvency_default", "NCLT admits insolvency plea against Test", 1),
    ("insolvency_default", "Company defaults on loan repayment, lender classifies account as NPA", 1),
    ("insolvency_default", "Polycab wins bid for insolvent cable maker under IBC, resolution applicant approved", 0),
    ("insolvency_default", "Test Industries to acquire stake in firm undergoing insolvency resolution process", 0),
    ("insolvency_default", "No proceedings are pending against the company under the Insolvency and Bankruptcy Code", 0),
    ("insolvency_default", "Siemens Energy flags insolvency and bankruptcy law changes in disclosure", 0),
    ("insolvency_default", "Clarification with respect to Media Reports concerning NCLT Order in the Personal Insolvency Proceedings of Dr. Subhash Chandra", 0),
    ("rating_downgrade", "CRISIL downgrades rating on Test's bonds", 1),
    ("rating_downgrade", "ICRA downgrades Test's long-term rating to BBB-", 1),
    ("rating_downgrade", "India Ratings downgrades the company's NCDs to A from AA-", 1),
    ("rating_downgrade", "Nomura cuts rating on Siemens to neutral, trims target price", 0),
    ("rating_downgrade", "Brokerage lowers rating on stock to sell and cuts target price", 0),
    ("results_delay", "Test delays submission of financial results", 1),
    ("results_delay", "Company postpones board meeting to approve quarterly results", 1),
    ("mgmt_exit", "CFO of Test resigns", 1),
    ("mgmt_exit", "Resignation of Mr X as Chief Financial Officer of the Company", 1),
    ("mgmt_exit", "Colgate Shares Fall 1.2% As CEO Prabha Narasimhan To Step Down", 1),
    ("mgmt_exit_minor", "Intimation of resignation of Non-Executive Non-Independent Director of the Company", 1),
    ("mgmt_exit_minor", "Resignation of Company Secretary and Compliance Officer of the company", 1),
    ("promoter_selling", "Promoters sell 2% stake in Test via block deal", 1),
    ("promoter_selling", "Edelweiss Financial promoter sells over half a percent stake; HDFC MF buys 0.51% stake in HEG", 0),
    ("short_seller", "Test hit by short seller report alleging accounting irregularities", 1),
]


def _doc(flag, text):
    return f"{flag} || {text}"


# ---------------------------------------------------------------- data
def load_labels(path):
    """[(flag, text, label)] from a CSV with columns flag,text,label (label 1 or 0). Missing file -> []."""
    rows = []
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                flag, text = (r.get("flag") or "").strip(), (r.get("text") or "").strip()
                lab = str(r.get("label") or "").strip()
                if flag and text and lab in ("0", "1"):
                    rows.append((flag, text, int(lab)))
    return rows


def _norm_label(v):
    s = str(v).strip().lower()
    if s in ("1", "1.0", "y", "yes", "true", "real", "genuine", "tp"):
        return 1
    if s in ("0", "0.0", "n", "no", "false", "fp", "false positive"):
        return 0
    return None


def import_sheet(xlsx, labels_path, sheet="Governance flags"):
    """Append reviewed rows (label filled) of the holdings_analysis 'Governance flags' sheet to the labels CSV."""
    import pandas as pd
    df = pd.read_excel(xlsx, sheet_name=sheet)
    for col in ("flag", "text", "label"):
        if col not in df.columns:
            raise ValueError(f"sheet '{sheet}' has no '{col}' column")
    existing = {(f, t) for f, t, _ in load_labels(labels_path)}
    new = []
    for _, r in df.iterrows():
        lab = _norm_label(r["label"]) if str(r["label"]) not in ("nan", "") else None
        key = (str(r["flag"]).strip(), str(r["text"]).strip())
        if lab is None or not key[0] or not key[1] or key in existing:
            continue
        existing.add(key)
        new.append((key[0], key[1], lab))
    fresh = not os.path.exists(labels_path)
    with open(labels_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if fresh:
            w.writerow(["flag", "text", "label"])
        w.writerows(new)
    return len(new)


# ---------------------------------------------------------------- embeddings (PyTorch, optional)
class Embedder:
    """Mean-pooled sentence embeddings from any Hugging Face encoder (local folder or model id). Loaded once."""

    def __init__(self, model_id, batch=32, max_len=128):
        self.model_id, self.batch, self.max_len = model_id, batch, max_len
        self._tok = self._mdl = None

    def __call__(self, texts):
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer
        if self._mdl is None:
            self._tok = AutoTokenizer.from_pretrained(self.model_id)
            self._mdl = AutoModel.from_pretrained(self.model_id).eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), self.batch):
                enc = self._tok(list(texts[i:i + self.batch]), padding=True, truncation=True,
                                max_length=self.max_len, return_tensors="pt")
                h = self._mdl(**enc).last_hidden_state
                m = enc["attention_mask"].unsqueeze(-1).float()
                out.append(((h * m).sum(1) / m.sum(1).clamp(min=1)).numpy())
        return np.vstack(out)


# ---------------------------------------------------------------- model
class GovModel:
    def __init__(self, clf, kind="tfidf", embedder_id=None, created=None, demote_below=DEMOTE_BELOW, report=None):
        self.clf, self.kind, self.embedder_id = clf, kind, embedder_id
        self.created = created or time.strftime("%Y%m%d%H%M%S")
        self.demote_below, self.report = demote_below, report or {}
        self._emb = None

    @property
    def name(self):
        return f"gov:{self.kind}:{self.created}"

    def prob(self, flag, text):
        """Probability that this flag is a genuine concern."""
        doc = _doc(flag, text)
        if self.kind == "tfidf":
            return float(self.clf.predict_proba([doc])[0][1])
        if self._emb is None:
            self._emb = Embedder(self.embedder_id)
        return float(self.clf.predict_proba(self._emb([doc]))[0][1])

    def apply(self, f, text):
        """Annotate a flag dict in place; demote its severity one step when the model says false positive."""
        try:
            p = self.prob(f["flag"], text)
        except Exception as e:                      # a model problem must never break a run
            f["ml_note"] = f"model error: {type(e).__name__}"
            return f
        f["ml_prob"] = round(p, 3)
        if p < self.demote_below and f.get("severity") in SEVERITY_DOWN:
            old = f["severity"]
            f["severity"] = SEVERITY_DOWN[old]
            f["ml_note"] = f"model: likely false positive ({p:.2f}); severity {old} -> {f['severity']}"
        return f

    def save(self, path):
        with open(path, "wb") as fh:
            pickle.dump({"clf": self.clf, "kind": self.kind, "embedder_id": self.embedder_id,
                         "created": self.created, "demote_below": self.demote_below, "report": self.report}, fh)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as fh:
            d = pickle.load(fh)
        return cls(d["clf"], d["kind"], d.get("embedder_id"), d.get("created"), d.get("demote_below", DEMOTE_BELOW),
                   d.get("report"))


def load_gov_model(path):
    return GovModel.load(path) if path else None


# ---------------------------------------------------------------- training
def _estimator():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    return Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
                     ("lr", LogisticRegression(C=3.0, class_weight="balanced", max_iter=2000))])


def train(labels_path=DEFAULT_LABELS, out=DEFAULT_MODEL, embedder_id=None, use_seed=True, log=print):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    rows = (SEED if use_seed else []) + load_labels(labels_path)
    uniq = {}
    for flag, text, lab in rows:                    # a user label overrides a seed row with the same text
        uniq[(flag, text)] = lab
    rows = [(f, t, l) for (f, t), l in uniq.items()]
    y = np.array([l for _, _, l in rows])
    n1, n0 = int(y.sum()), int((1 - y).sum())
    if len(rows) < MIN_LABELS or min(n0, n1) < MIN_PER_CLASS:
        raise ValueError(f"need at least {MIN_LABELS} labelled rows with {MIN_PER_CLASS}+ of each class "
                         f"(have {len(rows)}: {n1} genuine, {n0} false positive)")
    docs = [_doc(f, t) for f, t, _ in rows]
    log(f"Training on {len(rows)} rows ({n1} genuine, {n0} false positive)"
        + (f" from {labels_path} + seed" if use_seed else ""))

    if embedder_id:
        X = Embedder(embedder_id)(docs)
        est, kind = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000), "embed"
    else:
        X, est, kind = docs, _estimator(), "tfidf"

    folds = max(2, min(5, n0, n1))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    p = cross_val_predict(est, X, y, cv=cv, method="predict_proba")[:, 1]
    demoted = p < DEMOTE_BELOW
    fp_total, real_total = n0, n1
    fp_caught = int((demoted & (y == 0)).sum())
    real_hurt = int((demoted & (y == 1)).sum())
    report = {"rows": len(rows), "genuine": n1, "false_positive": n0, "cv_folds": folds,
              "cv_auc": round(float(roc_auc_score(y, p)), 3), "fp_caught": fp_caught, "fp_total": fp_total,
              "real_demoted": real_hurt, "real_total": real_total}
    log(f"Cross-validated ({folds}-fold) AUC {report['cv_auc']}. At the demotion cut-off {DEMOTE_BELOW}: "
        f"{fp_caught} of {fp_total} false positives caught; {real_hurt} of {real_total} genuine flags wrongly demoted.")
    if len(rows) < 100:
        log("  Warning: fewer than 100 labelled rows - treat this model as a demo and add reviewed rows "
            "(see 'import-sheet').")
    if real_hurt:
        log("  Note: genuine flags are only lowered one severity step and keep their text and ml_prob, "
            "but consider more labels before relying on this.")
    est.fit(X, y)
    model = GovModel(est, kind, embedder_id, report=report)
    model.save(out)
    log(f"Saved {out}")
    return model


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Governance-flag false-positive classifier")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train from the seed set + your labels CSV")
    t.add_argument("--labels", default=DEFAULT_LABELS)
    t.add_argument("--out", default=DEFAULT_MODEL)
    t.add_argument("--embedder", default=None, help="Hugging Face model id/folder for PyTorch embeddings "
                                                    "(default: TF-IDF, no PyTorch needed)")
    t.add_argument("--no-seed", action="store_true", help="ignore the built-in seed rows")
    i = sub.add_parser("import-sheet", help="append reviewed rows from a holdings_analysis .xlsx")
    i.add_argument("xlsx")
    i.add_argument("--labels", default=DEFAULT_LABELS)
    i.add_argument("--sheet", default="Governance flags")
    p = sub.add_parser("predict", help="score one piece of text")
    p.add_argument("text")
    p.add_argument("--flag", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    try:
        if a.cmd == "train":
            train(a.labels, a.out, a.embedder, use_seed=not a.no_seed)
        elif a.cmd == "import-sheet":
            n = import_sheet(a.xlsx, a.labels, a.sheet)
            print(f"{n} new labelled row(s) added to {a.labels}")
        else:
            m = GovModel.load(a.model)
            print(f"P(genuine) = {m.prob(a.flag, a.text):.3f}  (demoted below {m.demote_below})")
    except (ValueError, OSError, ImportError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
