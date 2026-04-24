"""
Deal scoring model using XGBoost.
Scores deals 0-100 based on:
- discount percentage
- category desirability
- price point (unit price relative to category average)
- recency (days until expiry)
- source reliability

Initially uses heuristic scoring until we have enough data to train.
Once we have 1000+ deals in DB, we can train on user interaction signals
(clicks, adds to list) as implicit positive feedback.
"""
import numpy as np
import logging
from typing import Optional
from pathlib import Path
import json

logger = logging.getLogger(__name__)

MODEL_PATH = Path("/app/app/workers/deal_scorer.json")

# Category weights — how much users typically care about deals in each category
CATEGORY_WEIGHTS = {
    "produce": 1.3,
    "meat": 1.4,
    "dairy": 1.2,
    "bakery": 1.0,
    "beverages": 0.9,
    "snacks": 0.8,
    "frozen": 1.1,
    "pantry": 1.2,
    "household": 1.0,
    "deli": 1.1,
}

# Typical price ranges per category (for unit price scoring)
CATEGORY_AVG_PRICES = {
    "produce": 2.50,
    "meat": 8.00,
    "dairy": 4.00,
    "bakery": 3.50,
    "beverages": 3.00,
    "snacks": 3.50,
    "frozen": 5.00,
    "pantry": 3.00,
    "household": 5.00,
    "deli": 6.00,
}

_model = None


def _load_model():
    """Load trained XGBoost model if it exists."""
    global _model
    if MODEL_PATH.exists():
        try:
            import xgboost as xgb
            _model = xgb.XGBRegressor()
            _model.load_model(str(MODEL_PATH))
            logger.info("Loaded trained XGBoost deal scorer")
        except Exception as e:
            logger.warning(f"Could not load XGB model: {e}, using heuristic scorer")
    return _model


def _extract_features(deal: dict) -> np.ndarray:
    """Extract feature vector from a deal dict."""
    discount_pct = deal.get("discount_pct") or 0.0
    sale_price = deal.get("sale_price") or deal.get("unit_price") or 0.0
    original_price = deal.get("original_price") or 0.0
    category = deal.get("category") or "unknown"

    # Feature 1: discount percentage (0-100)
    f_discount = min(discount_pct, 100.0)

    # Feature 2: has image (deals with images perform better)
    f_has_image = 1.0 if deal.get("image_url") else 0.0

    # Feature 3: category weight
    f_category_weight = CATEGORY_WEIGHTS.get(category, 1.0)

    # Feature 4: price relative to category average (lower is better)
    avg_price = CATEGORY_AVG_PRICES.get(category, 5.0)
    f_price_ratio = max(0, 1 - (sale_price / avg_price)) if sale_price and avg_price else 0.0

    # Feature 5: is multi-buy deal (2/$5 style)
    f_multi_buy = 1.0 if deal.get("quantity") else 0.0

    # Feature 6: source reliability
    source_weights = {"flipp": 1.0, "playwright_heb": 0.9, "kroger": 1.0}
    f_source = source_weights.get(deal.get("source", ""), 0.7)

    return np.array([
        f_discount,
        f_has_image,
        f_category_weight,
        f_price_ratio,
        f_multi_buy,
        f_source,
    ], dtype=np.float32)


def heuristic_score(deal: dict) -> float:
    """
    Heuristic deal score when ML model isn't trained yet.
    Returns 0-100.
    """
    features = _extract_features(deal)
    f_discount, f_has_image, f_category_weight, f_price_ratio, f_multi_buy, f_source = features

    # Weighted sum
    score = (
        f_discount * 0.45           # Discount % is the biggest factor
        + f_price_ratio * 20        # Absolute value
        + f_category_weight * 10    # Category desirability
        + f_has_image * 5           # Has image
        + f_multi_buy * 5           # Multi-buy deal
        + f_source * 5              # Source reliability
    )

    # Bonus: heavily discounted deals (>50% off)
    if f_discount >= 50:
        score += 10

    return round(min(score, 100.0), 1)


def score_deal(deal: dict) -> float:
    """Score a single deal. Uses ML model if trained, else heuristic."""
    model = _model or _load_model()

    if model:
        try:
            features = _extract_features(deal).reshape(1, -1)
            score = float(model.predict(features)[0])
            return round(min(max(score, 0), 100), 1)
        except Exception as e:
            logger.warning(f"ML scoring failed: {e}, falling back to heuristic")

    return heuristic_score(deal)


def score_batch(deals: list[dict]) -> list[dict]:
    """Score a batch of deals and add deal_score to each."""
    return [{**deal, "deal_score": score_deal(deal)} for deal in deals]


def train_model(training_data: list[dict], labels: list[float]):
    """
    Train XGBoost model on user interaction data.
    Call this once you have enough clicks/list-adds as implicit signals.

    training_data: list of deal dicts
    labels: implicit scores (e.g. click=1, add_to_list=3, purchased=5)
    """
    import xgboost as xgb

    X = np.array([_extract_features(d) for d in training_data])
    y = np.array(labels, dtype=np.float32)

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    model.fit(X, y, eval_set=[(X, y)], verbose=False)
    model.save_model(str(MODEL_PATH))

    global _model
    _model = model
    logger.info(f"Trained deal scorer on {len(training_data)} samples")
    return model
