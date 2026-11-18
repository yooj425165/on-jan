"""Prediction and replaceable, explicitly provisional music matching."""
import json
import math

from .config import ROOT
from .music import tracks


class Recommendation:
    def __init__(self):
        self.model = None

    def predict(self, data):
        try:
            from .ai_demo import MODEL, TARGETS, inputs, load_model
        except ImportError as exc:
            raise ValueError("AI 라이브러리 설치 필요: pip install -r requirements-ai.txt") from exc
        frame = inputs(float(data.get("lux")), float(data.get("weight_g")),
                       float(data.get("distance_cm")))
        if self.model is None:
            if not MODEL.exists():
                raise ValueError("모델 생성 필요: python -m onjan.ai_demo")
            self.model = load_model(MODEL)
        scores = self.model.predict(frame)[0].tolist()
        return self.rank(scores, TARGETS)

    def rank(self, scores, targets):
        catalog = json.loads((ROOT / "music" / "demo-profiles.json").read_text())
        available = set(tracks())
        ranked = []
        for track in catalog["tracks"]:
            if track["file"] not in available:
                continue
            profile = track["scores"]
            if len(profile) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x)
                                           and 0 <= x <= 1 for x in profile):
                raise ValueError("음악 프로필 점수 형식 오류")
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(scores, profile)))
            ranked.append({"file": track["file"], "distance": round(distance, 4)})
        ranked.sort(key=lambda item: (item["distance"], item["file"]))
        return {"scores": dict(zip(targets, scores)), "recommendations": ranked[:3],
                "input_source": "manual", "model_source": "synthetic_rule_demo",
                "matching_source": catalog["source"],
                "notice": "가상 학습 모델 + 수동 임시 음악 프로필. 실제 추천 성능은 미검증입니다."}
