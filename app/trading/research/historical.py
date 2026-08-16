"""Structured outputs for deterministic historical research."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from .canonical import AssetIdentity, DataQuality, FreshnessStatus, ResearchProvenance, _utc

class HistoricalStatus(StrEnum): COMPLETE="complete"; INSUFFICIENT_DATA="insufficient_data"; INVALID_INPUT="invalid_input"
@dataclass(frozen=True, slots=True)
class HistoricalContext:
    asset: AssetIdentity; provenance: ResearchProvenance; quality: DataQuality; freshness: FreshnessStatus; sample_start: datetime|None; sample_end: datetime|None; frequency: str|None; parameters: tuple[tuple[str,str],...]; generated_at: datetime
    def __post_init__(self):
        for name in ("sample_start","sample_end","generated_at"):
            value=getattr(self,name)
            if value is not None: object.__setattr__(self,name,_utc(value,name))
        object.__setattr__(self,"parameters",tuple(sorted((str(k),str(v)) for k,v in self.parameters)))
@dataclass(frozen=True, slots=True)
class HistoricalEvent:
    timestamp: datetime; value: Decimal|None=None
    def __post_init__(self): object.__setattr__(self,"timestamp",_utc(self.timestamp,"timestamp"))
@dataclass(frozen=True, slots=True)
class ForwardReturnObservation:
    event_timestamp: datetime; horizon: int; end_timestamp: datetime; return_value: Decimal
    def __post_init__(self):
        object.__setattr__(self,"event_timestamp",_utc(self.event_timestamp,"event_timestamp")); object.__setattr__(self,"end_timestamp",_utc(self.end_timestamp,"end_timestamp"))
@dataclass(frozen=True, slots=True)
class ForwardReturnSummary:
    horizon: int; observations: int; mean: Decimal|None; median: Decimal|None; positive_frequency: Decimal|None; minimum: Decimal|None; maximum: Decimal|None; quantiles: tuple[tuple[str,Decimal],...]=()
    def __post_init__(self): object.__setattr__(self,"quantiles",tuple(sorted(self.quantiles)))
@dataclass(frozen=True, slots=True)
class EventStudyResult:
    context: HistoricalContext; status: HistoricalStatus; event_definition: tuple[tuple[str,str],...]; events: tuple[HistoricalEvent,...]; forward_returns: tuple[ForwardReturnObservation,...]; summaries: tuple[ForwardReturnSummary,...]; warnings: tuple[str,...]=()
    def __post_init__(self):
        object.__setattr__(self,"event_definition",tuple(sorted((str(k),str(v)) for k,v in self.event_definition))); object.__setattr__(self,"warnings",tuple(sorted(set(self.warnings))))
@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    peak_at: datetime; trough_at: datetime; recovery_at: datetime|None; drawdown: Decimal; duration_periods: int; recovered: bool
    def __post_init__(self):
        object.__setattr__(self,"peak_at",_utc(self.peak_at,"peak_at")); object.__setattr__(self,"trough_at",_utc(self.trough_at,"trough_at"))
        if self.recovery_at is not None: object.__setattr__(self,"recovery_at",_utc(self.recovery_at,"recovery_at"))
@dataclass(frozen=True, slots=True)
class DrawdownResearchResult:
    context: HistoricalContext; status: HistoricalStatus; maximum_drawdown: Decimal|None; average_drawdown: Decimal|None; episodes: tuple[DrawdownEpisode,...]; warnings: tuple[str,...]=()
    def __post_init__(self): object.__setattr__(self,"warnings",tuple(sorted(set(self.warnings))))
@dataclass(frozen=True, slots=True)
class RegimeHistoricalResult:
    context: HistoricalContext; status: HistoricalStatus; first_label: str; second_label: str; first_event_study: EventStudyResult; second_event_study: EventStudyResult; warnings: tuple[str,...]=()
    def __post_init__(self): object.__setattr__(self,"warnings",tuple(sorted(set(self.warnings))))
