"""Shared chronology, features, endpoint and personalization rules (offline + online)."""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import math
import numpy as np

CADENCE = timedelta(minutes=15)
SCHEMA = "cgm13-v1"
SENSOR_FEATURES = [f"lag_{i}" for i in range(13)] + [
    "mean", "std", "minimum", "maximum", "slope_15", "slope_60", "past_above_fraction", "hour_sin", "hour_cos"]
HISTORY_FEATURES = ["age", "diabetes_years"]
FEATURES = SENSOR_FEATURES + HISTORY_FEATURES
BASELINE_FEATURES = ["lag_0", "slope_15", "slope_60", "hour_sin", "hour_cos"]


def dt(time: str) -> datetime:
    return datetime.fromisoformat(time)


def add_minutes(time: str, minutes: int) -> str:
    return (dt(time) + timedelta(minutes=minutes)).isoformat()


def minutes_between(a: str, b: str) -> float:
    return (dt(a) - dt(b)).total_seconds() / 60


def contiguous(readings: list[dict]) -> bool:
    return all(dt(b["time"]) - dt(a["time"]) == CADENCE for a, b in zip(readings, readings[1:]))


def make_features(readings: list[dict], profile: dict) -> tuple[dict | None, str]:
    window = readings[-13:]
    if len(window) < 13:
        return None, "warming_up"
    if not contiguous(window):
        return None, "gap_recovery"
    glucose = np.array([r["glucose"] for r in window], dtype=float)
    if glucose[-1] > 180 or glucose[-2] > 180:
        return None, "above_threshold"
    # Source timestamps are explicitly Asia/Shanghai; retain local time of day.
    local = dt(window[-1]["time"])
    hour = local.hour + local.minute / 60
    result = {f"lag_{i}": float(glucose[-1-i]) for i in range(13)}
    result.update(mean=float(glucose.mean()), std=float(glucose.std()), minimum=float(glucose.min()),
                  maximum=float(glucose.max()), slope_15=float((glucose[-1]-glucose[-2])/15),
                  slope_60=float((glucose[-1]-glucose[-5])/60),
                  past_above_fraction=float((glucose > 180).mean()),
                  hour_sin=math.sin(2*math.pi*hour/24), hour_cos=math.cos(2*math.pi*hour/24),
                  age=profile.get("age"), diabetes_years=profile.get("diabetes_years"))
    return result, "ready"


def onset_indices(readings: list[dict]) -> list[int]:
    return [i for i in range(2, len(readings)-1)
            if contiguous(readings[i-2:i+2]) and readings[i-2]["glucose"] <= 180
            and readings[i-1]["glucose"] <= 180 and readings[i]["glucose"] > 180
            and readings[i+1]["glucose"] > 180]


def resolve_outcome(readings: list[dict], issued_at: str, horizon: int) -> int | None:
    # Caller must supply observed readings only. None means censored, never negative.
    expected = [add_minutes(issued_at, i*15) for i in range(-1, horizon//15+2)]
    by_time = {r["time"]: r for r in readings}
    if any(t not in by_time for t in expected):
        return None
    ordered = [by_time[t] for t in expected]
    return int(bool(onset_indices(ordered)))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1-1e-6)
    return math.log(p/(1-p))


def sigmoid(x: float) -> float:
    return 1 / (1+math.exp(-max(-35, min(35, x))))


@dataclass
class TwinState:
    bias: float = 0.0
    learned_outcomes: int = 0
    last_learning_anchor: str | None = None
    segment_start: str | None = None
    revision: int = 0

    def ready(self, at: str) -> bool:
        return self.learned_outcomes >= 20 and self.segment_start is not None and minutes_between(at, self.segment_start) >= 1440

    def personalize(self, probability: float, at: str) -> float:
        return sigmoid(logit(probability) + (self.bias if self.ready(at) else 0))

    def learn(self, population: float, label: int, issued_at: str, horizon: int) -> bool:
        # Space learning anchors apart so highly overlapping labels do not count as independent evidence.
        if self.last_learning_anchor and minutes_between(issued_at, self.last_learning_anchor) < horizon+15:
            return False
        adjusted = sigmoid(logit(population) + self.bias)
        self.bias = float(np.clip(0.99*self.bias + 0.12*(label-adjusted), -0.75, 0.75))
        self.learned_outcomes += 1
        self.last_learning_anchor = issued_at
        self.revision += 1
        return True

    def dump(self) -> dict:
        return asdict(self)

