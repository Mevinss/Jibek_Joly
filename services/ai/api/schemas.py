from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class DataModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class Position(DataModel):
    block_id: str = Field(min_length=1, max_length=80)
    km: float = Field(default=0, ge=0)


class Train(DataModel):
    train_id: str = Field(min_length=1, max_length=80, pattern=r'^[\w-]+$')
    type: str
    priority: int = Field(default=1, ge=0, le=10)
    position: Position
    speed: float = Field(default=0, ge=0, le=500)
    delay_s: float = Field(ge=0, le=604800)
    ts: datetime
    min_technical_time_min: float = Field(default=10, gt=0, le=180)
    time_reserve_min: float = Field(default=2, ge=0, le=180)
    deterministic_wait_s: float | None = Field(default=None, ge=0, le=604800)
    restriction_extra_s: float = Field(default=0, ge=0, le=604800)
    source_domain: str | None = None
    next_block_closed: bool = False


class Block(DataModel):
    id: str
    occupied: bool = False
    closed: bool = False
    speed_limit: float = Field(default=100, ge=0, le=500)
    block_load: int | None = Field(default=None, ge=0, le=1000)
    num_platform_tracks: int = Field(default=2, ge=1, le=100)
    is_passing_loop: bool = True
    is_node: bool = False
    active_disruption_group: int = Field(default=0, ge=0, le=7)


class Infra(DataModel):
    blocks: list[Block]
    signals: list[dict] = Field(default_factory=list)
    switches: list[dict] = Field(default_factory=list)


class State(DataModel):
    trains: list[Train] = Field(max_length=500)
    infra: Infra

    @model_validator(mode='after')
    def unique_ids(self):
        for values in [[t.train_id for t in self.trains], [b.id for b in self.infra.blocks]]:
            if len(values) != len(set(values)):
                raise ValueError('Duplicate IDs')
        return self


class FeatureImpact(DataModel):
    name: str
    impact: float


class Forecast(DataModel):
    train_id: str
    p_conflict_15m: float = Field(ge=0, le=1)
    expected_delay_s: float = Field(ge=0)
    top_features: list[FeatureImpact]
    model_version: str = 'unknown'
    horizon_min: int | None = None
    alert: bool = False
    degraded: bool = False
    horizon_semantics: str = 'next_segment_proxy_not_validated_15m'


class Message(DataModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(DataModel):
    messages: list[Message] = Field(min_length=1, max_length=20)
    session_id: str = Field(default='demo', max_length=80)
    state: State | None = None

    @model_validator(mode='after')
    def user_last(self):
        if self.messages[-1].role != 'user':
            raise ValueError('Last message must be from user')
        return self


class IncidentParams(DataModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    minutes: float | None = Field(default=None, gt=0, le=1440, description='Длительность закрытия или задержки в минутах; поле называется minutes')


class Incident(DataModel):
    id: str = Field(max_length=80)
    kind: Literal['delay', 'signal_fault', 'block_closed']
    target_id: str = Field(min_length=1, max_length=80)
    params: IncidentParams = Field(default_factory=IncidentParams)
    ts: datetime

    @model_validator(mode='after')
    def duration_required(self):
        if self.kind in ['block_closed', 'delay'] and self.params.minutes is None:
            raise ValueError('params.minutes is required for closure or delay')
        return self


class TelegramRequest(DataModel):
    incident: Incident
    context: dict = Field(default_factory=dict)


class ReportRequest(DataModel):
    analytics: dict
