"""Historical event studies over canonical prices; VectorBT is isolated to drawdowns."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import sqrt
from typing import Iterable, Sequence
import numpy as np
import pandas as pd
import vectorbt as vbt
from .canonical import PriceSeries
from .historical import *

ZERO=Decimal("0")
def _d(value): return Decimal(str(round(float(value),12)))
@dataclass(frozen=True, slots=True)
class HistoricalResearchPolicy:
    minimum_events:int=3; minimum_volatility_lookback:int=10
    def __post_init__(self):
        if self.minimum_events<1 or self.minimum_volatility_lookback<2: raise ValueError("invalid historical policy")
class HistoricalResearchService:
    def __init__(self,policy:HistoricalResearchPolicy|None=None): self.policy=policy or HistoricalResearchPolicy()
    def return_threshold_events(self, prices:PriceSeries, *, threshold:Decimal, direction:str="above") -> tuple[HistoricalEvent,...]:
        rows,_=self._prices(prices); events=[]
        for (_,previous),(timestamp,current) in zip(rows,rows[1:]):
            change=(current/previous)-ONE if previous>ZERO else None
            if change is not None and ((direction=="above" and change>=threshold) or (direction=="below" and change<=threshold)):
                events.append(HistoricalEvent(timestamp,change))
        return tuple(events)
    def volatility_percentile_events(self,prices:PriceSeries,*,lookback:int=20,percentile:Decimal=Decimal("0.90")) -> tuple[HistoricalEvent,...]:
        if lookback<self.policy.minimum_volatility_lookback or not ZERO<percentile<ONE: raise ValueError("invalid volatility event parameters")
        rows,_=self._prices(prices); returns=[(t,float(c/p-ONE)) for (_,p),(t,c) in zip(rows,rows[1:]) if p>ZERO]; events=[]
        for index in range(lookback,len(returns)):
            # Context ends at the event timestamp; later returns are never used to define it.
            current=float(np.std([v for _,v in returns[index-lookback+1:index+1]],ddof=1)); history=[float(np.std([v for _,v in returns[start-lookback+1:start+1]],ddof=1)) for start in range(lookback-1,index)]
            if history and current>=float(np.quantile(history,float(percentile))): events.append(HistoricalEvent(returns[index][0],_d(current)))
        return tuple(events)
    def event_study(self,prices:PriceSeries,events:Iterable[HistoricalEvent|datetime],*,horizons:Sequence[int]=(1,3,5,7,14,30),event_definition:tuple[tuple[str,str],...]=(("kind","explicit"),)) -> EventStudyResult:
        if not horizons or any(h<1 for h in horizons): raise ValueError("horizons must be positive")
        rows,warnings=self._prices(prices); context=self._context(prices,rows,(("horizons",",".join(map(str,horizons))),)+event_definition)
        requested=tuple(HistoricalEvent(item) if isinstance(item,datetime) else item for item in events); index={timestamp:i for i,(timestamp,_) in enumerate(rows)}; observations=[]
        for event in requested:
            if event.timestamp not in index: warnings.append(f"Event {event.timestamp.isoformat()} is outside the usable price series."); continue
            start=index[event.timestamp]
            for horizon in horizons:
                end=start+horizon
                if end>=len(rows): continue
                observations.append(ForwardReturnObservation(event.timestamp,horizon,rows[end][0],rows[end][1]/rows[start][1]-ONE))
        summaries=tuple(self._summary(h,[item.return_value for item in observations if item.horizon==h]) for h in sorted(set(horizons)))
        if not requested: warnings.append("No events matched the requested definition.")
        if requested and not observations: warnings.append("Events near the end of the series had no complete forward window and were excluded.")
        if any(item.observations<self.policy.minimum_events for item in summaries): warnings.append(f"Some horizon summaries have fewer than {self.policy.minimum_events} events.")
        status=HistoricalStatus.COMPLETE if observations else HistoricalStatus.INSUFFICIENT_DATA
        return EventStudyResult(context,status,event_definition,requested,tuple(observations),summaries,tuple(warnings))
    def drawdown_analysis(self,prices:PriceSeries) -> DrawdownResearchResult:
        rows,warnings=self._prices(prices); context=self._context(prices,rows,(("engine","vectorbt"),))
        if len(rows)<2: return DrawdownResearchResult(context,HistoricalStatus.INSUFFICIENT_DATA,None,None,(),tuple(warnings+["At least two valid prices are required for drawdown analysis."]))
        ts=pd.Series([float(value) for _,value in rows],index=pd.DatetimeIndex([at for at,_ in rows])); readable=vbt.Drawdowns.from_ts(ts,wrapper_kwargs={"freq":"d"}).records_readable
        episodes=[]; index_map={timestamp:index for index,(timestamp,_) in enumerate(rows)}
        for _,row in readable.iterrows():
            peak=row["Peak Timestamp"].to_pydatetime(); trough=row["Valley Timestamp"].to_pydatetime(); recovered=str(row["Status"])=="Recovered"; recovery=row["End Timestamp"].to_pydatetime() if recovered else None
            end_at=row["End Timestamp"].to_pydatetime()
            episodes.append(DrawdownEpisode(peak,trough,recovery,_d(row["Valley Value"]/row["Peak Value"]-1),index_map.get(end_at,index_map[trough])-index_map[peak],recovered))
        values=[item.drawdown for item in episodes]
        return DrawdownResearchResult(context,HistoricalStatus.COMPLETE,_d(min(values)) if values else Decimal("0"),_d(np.mean([float(v) for v in values])) if values else Decimal("0"),tuple(episodes),tuple(warnings))
    def regime_comparison(self,prices:PriceSeries,first_events:Iterable[HistoricalEvent|datetime],second_events:Iterable[HistoricalEvent|datetime],*,horizons:Sequence[int]=(1,5),first_label:str="first",second_label:str="second") -> RegimeHistoricalResult:
        first=self.event_study(prices,first_events,horizons=horizons,event_definition=(("kind","regime"),("label",first_label))); second=self.event_study(prices,second_events,horizons=horizons,event_definition=(("kind","regime"),("label",second_label)))
        status=HistoricalStatus.COMPLETE if first.status is HistoricalStatus.COMPLETE and second.status is HistoricalStatus.COMPLETE else HistoricalStatus.INSUFFICIENT_DATA
        return RegimeHistoricalResult(first.context,status,first_label,second_label,first,second,tuple(sorted(set(first.warnings+second.warnings))))
    def _prices(self,prices):
        seen=set(); rows=[]; warnings=list(prices.quality.warnings)
        for bar in prices.bars:
            if bar.timestamp in seen: warnings.append("Duplicate timestamps were excluded."); continue
            seen.add(bar.timestamp)
            if bar.close is None or bar.close<=ZERO: warnings.append("Missing or non-positive close was excluded; no forward fill was applied."); continue
            rows.append((bar.timestamp,bar.close))
        return rows,warnings
    def _context(self,prices,rows,parameters): return HistoricalContext(prices.asset,prices.provenance,prices.quality,prices.freshness,rows[0][0] if rows else None,rows[-1][0] if rows else None,prices.interval,parameters,prices.provenance.retrieved_at)
    def _summary(self,horizon,values):
        if not values:return ForwardReturnSummary(horizon,0,None,None,None,None,None)
        a=np.array([float(v) for v in values]); return ForwardReturnSummary(horizon,len(values),_d(np.mean(a)),_d(np.median(a)),_d(np.mean(a>0)),_d(np.min(a)),_d(np.max(a)),(("p25",_d(np.quantile(a,.25))),("p75",_d(np.quantile(a,.75)))))
ONE=Decimal("1")
