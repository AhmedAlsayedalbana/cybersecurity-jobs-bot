"""Local adaptive ML filter for cybersecurity jobs."""

from __future__ import annotations

import logging
import math
import os
import hashlib
import json
import sys
from typing import Any

import config

log = logging.getLogger(__name__)

_SKLEARN_READY = True
try:
    import joblib
    import sklearn
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
except Exception:
    _SKLEARN_READY = False


class ModelIntegrityError(RuntimeError):
    """Artifact contract mismatch; callers must fail closed before sending."""


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_schema_hash() -> str:
    # Keep this aligned with _feature_text field order and truncation rules.
    schema = "src,type,loc,title,company,description[:700],tags|lower|v1"
    return hashlib.sha256(schema.encode("utf-8")).hexdigest()


_PHYSICAL_SECURITY = {
    "security guard",
    "security agent",
    "security superintendent",
    "senior superintendent - security",
    "aviation security",
    "fire safety",
    "loss prevention",
    "physical security",
    "cabin crew",
}

_NON_TECH_TERMS = {
    "security guard", "physical security", "loss prevention", "business development",
    "sales", "account manager", "customer success", "office", "admin assistant",
    "marketing", "copywriter", "real estate",
}

_CYBER_TERMS = {
    "cybersecurity", "cyber security", "information security", "infosec",
    "soc", "siem", "pentest", "penetration", "red team", "blue team",
    "dfir", "incident response", "threat intelligence", "appsec", "devsecops",
    "grc", "security engineer", "security analyst", "security architect",
    "vulnerability", "malware", "forensics", "network security", "cloud security",
    "iam", "access management", "ping identity", "okta", "zero trust",
}

_INTERN_TERMS = {
    "intern", "internship", "trainee", "graduate", "entry-level", "entry level",
    "fresh grad", "new grad", "junior",
}

_POSITIVE_SEEDS = [
    "SOC Analyst",
    "Junior SOC Engineer",
    "Penetration Tester",
    "Red Team Engineer",
    "Application Security Engineer",
    "Cloud Security Engineer",
    "GRC Analyst",
    "Incident Response Analyst",
    "DFIR Specialist",
    "Threat Intelligence Analyst",
    "Network Security Engineer",
    "Security Architect",
    "IAM Security Engineer",
    "IT Security Specialist",
    "Network Security BackOffice Engineer",
    "Senior Security Operation Engineer",
    "Access Management - Ping / Okta Engineer",
    "Security Intern",
    "Cybersecurity Graduate Trainee",
    "Security Operations Center Analyst",
]

_NEGATIVE_SEEDS = [
    "Business Analyst",
    "Data Entry Specialist",
    "Aviation Security",
    "Security Agent",
    "Security Guard",
    "Senior Superintendent - Security",
    "Fire Safety Specialist",
    "Cabin Crew",
    "Sales Account Manager",
    "Marketing Specialist",
    "Customer Success Manager",
    "HR Specialist",
    "Office Manager",
    "System Administrator",
    "Network Administrator",
]


def _flatten_tags(tags: Any) -> str:
    if not tags:
        return ""
    if isinstance(tags, list):
        return " ".join(str(t) for t in tags)
    return str(tags)


def _feature_text(job: Any) -> str:
    source = (getattr(job, "source_key", "") or getattr(job, "source", "")).lower()
    content_type = (getattr(job, "content_type", "") or "job_listing").lower()
    location = (getattr(job, "location", "") or "").lower()
    return " ".join([
        f"src:{source}",
        f"type:{content_type}",
        f"loc:{location}",
        (getattr(job, "title", "") or ""),
        (getattr(job, "company", "") or ""),
        (getattr(job, "description", "") or "")[:700],
        _flatten_tags(getattr(job, "tags", None)),
    ]).lower()


def _safe_sigmoid(x: float) -> float:
    if x > 40:
        return 1.0
    if x < -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


class _AdaptiveLocalCyberClassifier:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.word_vectorizer = None
        self.char_vectorizer = None
        self.model = None
        self.ready = False
        self.last_retrain_samples = 0

    def _fit_model(self, texts: list[str], labels: list[int]) -> bool:
        if not _SKLEARN_READY:
            return False
        self.word_vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            min_df=1,
            max_features=18000,
        )
        self.char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
            max_features=12000,
        )
        x_word = self.word_vectorizer.fit_transform(texts)
        x_char = self.char_vectorizer.fit_transform(texts)
        x = hstack([x_word, x_char])
        self.model = LogisticRegression(max_iter=1200, class_weight="balanced")
        self.model.fit(x, labels)
        self.last_retrain_samples = len(texts)
        return True

    def _train_seed_model(self) -> bool:
        train_x = _POSITIVE_SEEDS + _NEGATIVE_SEEDS
        train_y = [1] * len(_POSITIVE_SEEDS) + [0] * len(_NEGATIVE_SEEDS)
        return self._fit_model(train_x, train_y)

    def _load_from_disk(self) -> bool:
        if not _SKLEARN_READY:
            raise ModelIntegrityError("scikit-learn is unavailable")
        if not self.model_path or not os.path.exists(self.model_path):
            raise ModelIntegrityError(f"model artifact missing: {self.model_path}")
        manifest_path = config.ML_MODEL_MANIFEST_PATH
        if not manifest_path or not os.path.exists(manifest_path):
            raise ModelIntegrityError(f"model manifest missing: {manifest_path}")
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            expected_version = "1.8.0"
            if manifest.get("sklearn_version") != expected_version or sklearn.__version__ != expected_version:
                raise ModelIntegrityError(
                    f"sklearn mismatch manifest={manifest.get('sklearn_version')} runtime={sklearn.__version__}"
                )
            if manifest.get("feature_schema_version") != config.ML_FEATURE_SCHEMA_VERSION:
                raise ModelIntegrityError("feature schema version mismatch")
            if manifest.get("feature_schema_hash") != feature_schema_hash():
                raise ModelIntegrityError("feature schema hash mismatch")
            if manifest.get("model_sha256") != _sha256_file(self.model_path):
                raise ModelIntegrityError("model SHA-256 mismatch")
            payload = joblib.load(self.model_path)
            self.word_vectorizer = payload.get("word_vectorizer")
            self.char_vectorizer = payload.get("char_vectorizer")
            self.model = payload.get("model")
            self.last_retrain_samples = int(payload.get("last_retrain_samples", 0) or 0)
            if not (self.word_vectorizer and self.char_vectorizer and self.model):
                raise ModelIntegrityError("artifact payload is incomplete")
            return True
        except ModelIntegrityError:
            raise
        except Exception as exc:
            raise ModelIntegrityError(f"failed loading model artifact: {type(exc).__name__}") from exc

    def _save_to_disk(self) -> None:
        if not _SKLEARN_READY or not self.model_path or not self.word_vectorizer or not self.char_vectorizer or not self.model:
            return
        try:
            os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
            joblib.dump(
                {
                    "word_vectorizer": self.word_vectorizer,
                    "char_vectorizer": self.char_vectorizer,
                    "model": self.model,
                    "last_retrain_samples": self.last_retrain_samples,
                },
                self.model_path,
            )
        except Exception as exc:
            log.debug(f"[ml] Could not persist local model: {exc}")

    def ensure_ready(self) -> bool:
        if self.ready:
            return True
        if self._load_from_disk():
            self.ready = True
            return True
        return False

    def maybe_retrain_from_db(self) -> None:
        # Runtime retraining would create a model/manifest mismatch in the
        # persisted data branch.  Human labels are retained for the explicit
        # build command instead.
        if config.ENABLE_LOCAL_ML_RETRAIN:
            log.warning("[ml] Runtime retraining is disabled; use build_ml_artifact.py explicitly.")

    def predict_proba(self, feature_text: str) -> float:
        if not self.ensure_ready():
            raise ModelIntegrityError("model could not be made ready")
        try:
            x_word = self.word_vectorizer.transform([feature_text])
            x_char = self.char_vectorizer.transform([feature_text])
            x = hstack([x_word, x_char])
            if hasattr(self.model, "predict_proba"):
                return float(self.model.predict_proba(x)[0][1])
            if hasattr(self.model, "decision_function"):
                return _safe_sigmoid(float(self.model.decision_function(x)[0]))
        except Exception as exc:
            raise ModelIntegrityError(f"model prediction failed: {type(exc).__name__}") from exc


_MODEL = _AdaptiveLocalCyberClassifier(config.ML_MODEL_PATH)


def classify_cyber_probability(job: Any) -> tuple[float, list[str]]:
    """
    Return (probability, reason_codes) using local adaptive ML first, heuristic fallback second.
    """
    title = (getattr(job, "title", "") or "").lower()
    reasons: list[str] = []

    if any(k in title for k in _PHYSICAL_SECURITY):
        return 0.0, ["physical_security_blocked"]

    if config.ML_FILTER_ENABLED:
        _MODEL.maybe_retrain_from_db()
        proba = _MODEL.predict_proba(_feature_text(job))
        if proba >= 0:
            source_key = (getattr(job, "source_key", "") or getattr(job, "source", "")).lower()
            high_cut = 0.84 if "linkedin" in source_key else 0.80
            low_cut = max(0.55, config.ML_MIN_PROB - (0.05 if "linkedin" in source_key else 0.0))
            if proba >= high_cut:
                reasons.append("ml_high_confidence")
            elif proba >= low_cut:
                reasons.append("ml_candidate")
            else:
                reasons.append("ml_low_conf")
            return proba, reasons

    text = _feature_text(job)
    pos_hits = sum(1 for k in _CYBER_TERMS if k in text)
    neg_hits = sum(1 for k in _NON_TECH_TERMS if k in text)
    title_boost = 2 if any(k in title for k in ["security", "cyber", "soc", "pentest"]) else 0
    raw = (pos_hits * 0.12) + (title_boost * 0.08) - (neg_hits * 0.24)
    proba = max(0.01, min(0.99, 0.5 + raw))
    reasons.append("heuristic_fallback")
    if neg_hits:
        reasons.append("non_tech_signal")
    return proba, reasons


def triage_job(job: Any) -> tuple[str, float, list[str]]:
    """Return triage label: hard_reject | candidate | high_confidence."""
    p, reasons = classify_cyber_probability(job)
    if p < 0.45:
        return "hard_reject", p, reasons
    if p >= 0.82:
        return "high_confidence", p, reasons
    return "candidate", p, reasons


def is_true_security_internship(job: Any) -> bool:
    try:
        from job_intelligence import is_true_security_internship as central_internship_check
        return central_internship_check(job)
    except Exception:
        pass

    text = _feature_text(job)
    title = (getattr(job, "title", "") or "").lower()
    has_intern_signal = any(t in text for t in _INTERN_TERMS)
    if not has_intern_signal:
        return False
    if any(bad in title for bad in ["business development", "sales", "marketing", "hr", "cabin crew"]):
        return False
    cyber_hits = sum(1 for k in _CYBER_TERMS if k in text)
    if any(k in title for k in ["security intern", "cybersecurity intern", "soc intern", "security trainee"]):
        return cyber_hits >= 1
    return cyber_hits >= 2
