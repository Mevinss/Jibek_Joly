"""Plan-timed, idealized eco-driving advice. No traction/braking control."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from backend.planner.context import timestamp
from backend.planner.models import DispatchPlan
from backend.validator.resources import validate_plan
from .profile import build_speed_profile


@dataclass(frozen=True)
class SpeedAdviceConfig:
    minimum_demo_speed_kmh: float = 5.0

    def __post_init__(self):
        if not math.isfinite(self.minimum_demo_speed_kmh) or self.minimum_demo_speed_kmh <= 0:
            raise ValueError("minimum demo speed must be finite and positive")


@dataclass
class SpeedAdvice:
    train_id: str
    plan_id: str | None
    advisory: bool = True
    profile_type: str = "demonstration_advisory_profile"
    current_speed_kmh: float | None = None
    recommended_speed_kmh: float | None = None
    target_resource_id: str | None = None
    target_arrival_time: str | None = None
    full_stop_avoided: bool | None = None
    energy_proxy_units_before: float | None = None
    energy_proxy_units_after: float | None = None
    energy_proxy_delta: float | None = None
    energy_proxy_basis: dict = field(default_factory=dict)
    profile_points: list[dict] = field(default_factory=list)
    reason_code: str = "TARGET_TIME_UNKNOWN"
    reason: str = "В плане нет известного времени входа на ресурс."
    assumptions: list[str] = field(default_factory=lambda: [
        "Синтетическая модель с мгновенным изменением скорости; тормозной путь не рассчитан.",
        "Совет действителен только для указанного плана и снимка; запрещающий сигнал сохраняет приоритет.",
        "Энергетический индекс — условная оценка событий, без физических единиц энергии.",
    ])

    def to_dict(self):
        return asdict(self)


def energy_proxy(*, full_stops: int, acceleration_changes: list[float],
                 braking_changes: list[float], speed_limit_kmh: float,
                 idle_waiting_minutes: float) -> float:
    """Stops + sum((delta_speed / cap)^2) for accel/brake + idle_minutes/60."""
    if not isinstance(full_stops, int) or full_stops < 0 or not math.isfinite(speed_limit_kmh) or speed_limit_kmh <= 0:
        raise ValueError("invalid proxy stop count or speed cap")
    values = [*acceleration_changes, *braking_changes, idle_waiting_minutes]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("proxy inputs must be finite and nonnegative")
    return round(full_stops + sum((v / speed_limit_kmh) ** 2 for v in acceleration_changes + braking_changes)
                 + idle_waiting_minutes / 60, 8)


def build_speed_advice(snapshot: dict, train_id: str, plan: DispatchPlan | dict | None,
                       *, target_resource_id: str, distance_to_control_point_km: float | None,
                       segment_speed_limit_kmh: float | None,
                       current_speed_kmh: float | None = None,
                       config: SpeedAdviceConfig | None = None, infrastructure=None) -> SpeedAdvice:
    config = config or SpeedAdviceConfig()
    data = plan.to_dict() if isinstance(plan, DispatchPlan) else plan
    train = next((t for t in snapshot["trains"] if t["train_id"] == train_id), None)
    if train is None:
        raise KeyError(f"unknown train {train_id}")
    speed = train.get("speed_kmh") if current_speed_kmh is None else current_speed_kmh
    advice = SpeedAdvice(train_id, data.get("plan_id") if data else None,
                         current_speed_kmh=speed, target_resource_id=target_resource_id)
    if not data:
        return advice
    expected_index = int(train.get("block_index", -1)) + 1
    if not 0 <= expected_index < len(train.get("route", [])) or train["route"][expected_index] != target_resource_id:
        advice.reason_code, advice.reason = "TARGET_NOT_NEXT_RESOURCE", "Совет поддерживает только следующий блок маршрута."
        return advice
    checked = validate_plan(snapshot, data, infrastructure)
    if not checked.valid or not getattr(checked, "fully_validated", False):
        advice.reason_code, advice.reason = "PLAN_UNVERIFIED", "План устарел, отклонён или проверен не полностью."
        return advice
    entries = [r for r in data["resource_intervals"] if r["train_id"] == train_id
               and r["resource_id"] == target_resource_id and r["resource_type"] == "block"
               and not r["existing_occupancy"]
               and timestamp(r["start_time"]) >= timestamp(snapshot["virtual_time"])]
    if not entries:
        return advice
    entry = min(entries, key=lambda r: timestamp(r["start_time"]))
    advice.target_arrival_time = entry["start_time"]
    values = [distance_to_control_point_km, segment_speed_limit_kmh, speed]
    if any(v is None for v in values):
        advice.reason_code, advice.reason = "INPUT_UNKNOWN", "Неизвестны расстояние, текущая скорость или ограничение скорости."
        return advice
    if any(not math.isfinite(v) or v < 0 for v in values) or segment_speed_limit_kmh <= 0:
        raise ValueError("advisory inputs must be finite, nonnegative, and the speed cap positive")
    cap = float(segment_speed_limit_kmh)
    target_block = next((b for b in snapshot["blocks"] if b["block_id"] == target_resource_id), {})
    known_caps = [v for v in (target_block.get("speed_limit_kmh"), train.get("max_speed_kmh")) if v is not None]
    if infrastructure is not None:
        category_cap = infrastructure.get("parameters", {}).get(train.get("category"), {}).get("demo_max_speed_kmh")
        if category_cap is not None:
            known_caps.append(float(category_cap))
    if known_caps:
        cap = min(cap, *known_caps)
    if not math.isfinite(cap) or cap <= 0 or speed > cap:
        advice.reason_code, advice.reason = "SPEED_INPUT_REQUIRES_REVIEW", "Текущая скорость превышает доступное ограничение; требуется пересмотр входных данных."
        return advice
    seconds = (timestamp(entry["start_time"]) - timestamp(snapshot["virtual_time"])).total_seconds()
    distance = float(distance_to_control_point_km)
    if distance == 0 or seconds <= 0 or speed == 0:
        advice.reason_code, advice.reason = "STOP_OR_REPLAN_REQUIRED", "Плавный подход по этой модели недоступен: остановка или пересчёт плана."
        advice.full_stop_avoided = False
        return advice
    required = distance * 3600 / seconds
    if required > cap:
        advice.reason_code, advice.reason = "TARGET_UNREACHABLE", "До назначенного времени нельзя доехать в пределах ограничения скорости."
        advice.full_stop_avoided = False
        return advice
    if required < config.minimum_demo_speed_kmh:
        advice.reason_code, advice.reason = "STOP_REQUIRED", "Для подхода без остановки потребовалась бы скорость ниже минимальной скорости демо."
        advice.full_stop_avoided = False
        return advice
    # These are average-speed sections with idealized instantaneous transitions.
    # The reference trajectory maintains current speed, stops if early, then
    # returns to current speed after the control point. The advice trajectory
    # uses required speed, then returns to the same reference speed.
    baseline_seconds = distance * 3600 / speed
    baseline_stop = baseline_seconds < seconds - 1e-7
    advice.full_stop_avoided = baseline_stop and required >= config.minimum_demo_speed_kmh
    advice.recommended_speed_kmh = required
    advice.profile_points = [
        {"distance_km": 0.0, "speed_kmh": required, "elapsed_seconds": 0.0},
        {"distance_km": distance / 2, "speed_kmh": required, "elapsed_seconds": seconds / 2},
        {"distance_km": distance, "speed_kmh": required, "elapsed_seconds": seconds},
    ]
    before = dict(full_stops=int(baseline_stop), acceleration_changes=[speed] if baseline_stop else [],
                  braking_changes=[speed] if baseline_stop else [], speed_limit_kmh=cap,
                  idle_waiting_minutes=max(0, seconds - baseline_seconds) / 60)
    after = dict(full_stops=0, acceleration_changes=[abs(speed - required)],
                 braking_changes=[abs(speed - required)], speed_limit_kmh=cap, idle_waiting_minutes=0.0)
    advice.energy_proxy_units_before = energy_proxy(**before)
    advice.energy_proxy_units_after = energy_proxy(**after)
    advice.energy_proxy_delta = round(advice.energy_proxy_units_after - advice.energy_proxy_units_before, 8)
    advice.energy_proxy_basis = {"formula": "full_stops + sum((delta_speed/speed_limit)^2) + idle_minutes/60",
                                 "before_components": before, "after_components": after,
                                 "scope": "idealized_control_point_approach_and_return_to_reference_speed"}
    advice.reason_code = "ARRIVE_WHEN_RESOURCE_OPENS" if baseline_stop else "MATCH_PLAN_ENTRY_TIME"
    advice.reason = "Средняя скорость рассчитана по расстоянию и времени входа из проверенного плана."
    return advice


def build_speed_profile_with_plan(snapshot, train_id, plan=None, *, data_root=None, **advice_inputs):
    """Keep the existing endpoint's limit-only payload when no dispatch plan exists."""
    if plan is None:
        return build_speed_profile(snapshot, train_id, **({"data_root": data_root} if data_root is not None else {}))
    return build_speed_advice(snapshot, train_id, plan, **advice_inputs).to_dict()
