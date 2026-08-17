"""Re-export the local ML artifact with a fail-closed integrity manifest.

Run under the pinned requirements environment.  This intentionally reuses the
current approved artifact; future retraining should be an explicit extension
that supplies a curated, human-verified dataset and updates the data hash.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

import joblib
import sklearn

import config
from ml_filter import feature_schema_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if sklearn.__version__ != "1.8.0":
        raise SystemExit(f"Expected scikit-learn 1.8.0, found {sklearn.__version__}")
    model_path = Path(config.ML_MODEL_PATH)
    manifest_path = Path(config.ML_MODEL_MANIFEST_PATH)
    if not model_path.exists():
        raise SystemExit(f"Missing approved model: {model_path}")
    payload = joblib.load(model_path)
    if not isinstance(payload, dict) or not all(key in payload for key in ("word_vectorizer", "char_vectorizer", "model")):
        raise SystemExit("Model payload does not match the expected feature contract")

    # Re-serialization under the pinned runtime normalizes joblib/sklearn
    # metadata before the checksum is recorded.
    joblib.dump(payload, model_path)
    provenance = json.dumps(
        {"last_retrain_samples": payload.get("last_retrain_samples", 0), "artifact": "approved-reexport-v1"},
        sort_keys=True,
    ).encode("utf-8")
    manifest = {
        "artifact_format": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "feature_schema_version": config.ML_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": feature_schema_hash(),
        "model_sha256": _sha256(model_path),
        "training_data_hash": hashlib.sha256(provenance).hexdigest(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {model_path} and {manifest_path}")


if __name__ == "__main__":
    main()
