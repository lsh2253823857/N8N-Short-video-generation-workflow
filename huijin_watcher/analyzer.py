import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from config import (
    INTERVENTION_AVG_PCT_MILD,
    INTERVENTION_AVG_PCT_STRONG,
    INTERVENTION_ETF_MIN_COUNT,
    SIGNIFICANT_MOVE_PCT,
    SNAPSHOT_PATH,
)
from holdings import ETFS, STOCKS

logger = logging.getLogger(__name__)


@dataclass
class QuoteItem:
    symbol: str
    name: str
    price: float
    pct_change: float      # 正数=涨，负数=跌，单位%
    value: float           # 估算持仓市值（元）
    value_change: float    # 今日市值变动（元）


@dataclass
class PortfolioResult:
    items: list[QuoteItem]
    total_value: float         # 总持仓估算市值（元）
    total_value_change: float  # 今日总市值变动（元）
    avg_pct_change: float      # 加权平均涨跌幅（%）


@dataclass
class InterventionSignal:
    triggered: bool
    level: str             # "强护盘" / "温和护盘" / "无信号"
    reason: str
    up_count: int
    down_count: int
    avg_pct: float


@dataclass
class AnalysisResult:
    trade_date: str
    stock: PortfolioResult
    etf: PortfolioResult
    signal: InterventionSignal
    new_announcements: list[dict]
    all_announcements: list[dict]
    fetch_errors: list[str] = field(default_factory=list)


def _parse_quotes(df: pd.DataFrame, holdings: dict) -> list[QuoteItem]:
    items: list[QuoteItem] = []
    for symbol, info in holdings.items():
        row = df[df["代码"] == symbol]
        if row.empty:
            logger.warning("未找到行情: %s %s", symbol, info["name"])
            continue
        r = row.iloc[0]
        price = float(r.get("最新价", 0) or 0)
        pct = float(r.get("涨跌幅", 0) or 0)
        shares = info.get("shares", 0)
        value = price * shares
        value_change = value * pct / (100 + pct) if (100 + pct) != 0 else 0
        items.append(QuoteItem(
            symbol=symbol,
            name=info["name"],
            price=price,
            pct_change=pct,
            value=value,
            value_change=value_change,
        ))
    return sorted(items, key=lambda x: x.pct_change, reverse=True)


def _portfolio_stats(items: list[QuoteItem]) -> tuple[float, float, float]:
    total_value = sum(i.value for i in items)
    total_change = sum(i.value_change for i in items)
    avg_pct = (total_change / (total_value - total_change) * 100
               if (total_value - total_change) > 0 else 0.0)
    return total_value, total_change, avg_pct


def analyze_stocks(df: pd.DataFrame) -> PortfolioResult:
    items = _parse_quotes(df, STOCKS)
    total_value, total_change, avg_pct = _portfolio_stats(items)
    return PortfolioResult(
        items=items,
        total_value=total_value,
        total_value_change=total_change,
        avg_pct_change=avg_pct,
    )


def analyze_etfs(df: pd.DataFrame) -> PortfolioResult:
    items = _parse_quotes(df, ETFS)
    total_value, total_change, avg_pct = _portfolio_stats(items)
    return PortfolioResult(
        items=items,
        total_value=total_value,
        total_value_change=total_change,
        avg_pct_change=avg_pct,
    )


def detect_intervention(etf_result: PortfolioResult) -> InterventionSignal:
    items = etf_result.items
    if not items:
        return InterventionSignal(False, "无信号", "ETF数据为空", 0, 0, 0.0)

    up_count = sum(1 for i in items if i.pct_change > 0)
    down_count = sum(1 for i in items if i.pct_change <= 0)
    avg_pct = sum(i.pct_change for i in items) / len(items)

    if avg_pct >= INTERVENTION_AVG_PCT_STRONG and up_count >= INTERVENTION_ETF_MIN_COUNT:
        return InterventionSignal(
            triggered=True,
            level="强护盘",
            reason=f"ETF平均涨幅{avg_pct:+.2f}%，{up_count}/{len(items)}只上涨",
            up_count=up_count,
            down_count=down_count,
            avg_pct=avg_pct,
        )
    if avg_pct >= INTERVENTION_AVG_PCT_MILD and up_count >= INTERVENTION_ETF_MIN_COUNT:
        return InterventionSignal(
            triggered=True,
            level="温和护盘",
            reason=f"ETF平均涨幅{avg_pct:+.2f}%，{up_count}/{len(items)}只上涨",
            up_count=up_count,
            down_count=down_count,
            avg_pct=avg_pct,
        )
    return InterventionSignal(
        triggered=False,
        level="无信号",
        reason=f"ETF平均{avg_pct:+.2f}%，{up_count}/{len(items)}只上涨",
        up_count=up_count,
        down_count=down_count,
        avg_pct=avg_pct,
    )


def detect_new_announcements(
    announcements: list[dict],
    snapshot: dict,
) -> list[dict]:
    """与快照中已知公告对比，返回新增公告列表。"""
    known: set[str] = set(snapshot.get("announcement_keys", []))
    new_items: list[dict] = []
    for item in announcements:
        key = f"{item.get('symbol', '')}|{item.get('title', '')}"
        if key not in known:
            new_items.append(item)
    return new_items


def load_snapshot() -> dict:
    if not os.path.exists(SNAPSHOT_PATH):
        return {}
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("读取快照失败: %s", exc)
        return {}


def save_snapshot(
    trade_date: str,
    stock_result: PortfolioResult,
    etf_result: PortfolioResult,
    announcements: list[dict],
) -> None:
    data = {
        "last_run_date": trade_date,
        "stock_prices": {i.symbol: i.price for i in stock_result.items},
        "etf_prices":   {i.symbol: i.price for i in etf_result.items},
        "announcement_keys": [
            f"{a.get('symbol','')}|{a.get('title','')}"
            for a in announcements
        ],
    }
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("快照已更新: %s", SNAPSHOT_PATH)


def get_top_movers(items: list[QuoteItem], threshold: float = SIGNIFICANT_MOVE_PCT) -> list[QuoteItem]:
    return [i for i in items if abs(i.pct_change) >= threshold]
