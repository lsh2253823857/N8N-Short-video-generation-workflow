import logging
import time
from typing import Optional

import akshare as ak
import pandas as pd

from config import FETCH_RETRIES, FETCH_RETRY_DELAY
from holdings import ETF_SYMBOLS, STOCK_SYMBOLS

logger = logging.getLogger(__name__)


class FetchError(Exception):
    pass


def _retry(fn, retries: int = FETCH_RETRIES, delay: float = FETCH_RETRY_DELAY):
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            result = fn()
            if result is not None and (not hasattr(result, "__len__") or len(result) > 0):
                return result
            raise ValueError("返回空数据")
        except Exception as exc:
            last_exc = exc
            logger.warning("第%d次请求失败: %s", attempt, exc)
            if attempt < retries:
                time.sleep(delay)
    raise FetchError(f"重试{retries}次后仍失败: {last_exc}") from last_exc


# AKShare 各接口实际列名可能随版本变化，统一在此映射
_ETF_COL_MAP = {
    "基金代码": "代码",
    "基金简称": "名称",
    "单位净值": "最新价",
    "涨跌幅": "涨跌幅",
    "成交量": "成交量",
    "成交额": "成交额",
}

_STOCK_COL_MAP = {
    "代码": "代码",
    "名称": "名称",
    "最新价": "最新价",
    "涨跌幅": "涨跌幅",
    "成交量": "成交量",
    "成交额": "成交额",
    "流通市值": "流通市值",
}


def _normalize_columns(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    df = df.rename(columns=col_map)
    return df


def fetch_etf_quotes() -> pd.DataFrame:
    """
    返回 DataFrame，列：代码 名称 最新价 涨跌幅 成交量 成交额
    只保留汇金持有的 ETF。
    """
    def _fetch():
        df = ak.fund_etf_spot_em()
        return df

    df = _retry(_fetch)
    df = _normalize_columns(df, _ETF_COL_MAP)

    # 确保关键列存在（版本兼容兜底）
    if "最新价" not in df.columns and "单位净值" in df.columns:
        df = df.rename(columns={"单位净值": "最新价"})

    required = ["代码", "名称", "最新价", "涨跌幅"]
    for col in required:
        if col not in df.columns:
            logger.error("ETF数据缺少列: %s，现有列: %s", col, list(df.columns))
            raise FetchError(f"ETF数据缺少列: {col}")

    df["代码"] = df["代码"].astype(str).str.zfill(6)
    df = df[df["代码"].isin(ETF_SYMBOLS)].copy()

    if df.empty:
        raise FetchError("未能获取到任何汇金ETF行情数据")

    for col in ["最新价", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("获取ETF行情: %d 条", len(df))
    return df.reset_index(drop=True)


def fetch_stock_quotes() -> pd.DataFrame:
    """
    返回 DataFrame，列：代码 名称 最新价 涨跌幅 成交量 成交额
    只保留汇金持有的股票。
    """
    def _fetch():
        df = ak.stock_zh_a_spot_em()
        return df

    df = _retry(_fetch)
    df = _normalize_columns(df, _STOCK_COL_MAP)

    required = ["代码", "名称", "最新价", "涨跌幅"]
    for col in required:
        if col not in df.columns:
            logger.error("股票数据缺少列: %s，现有列: %s", col, list(df.columns))
            raise FetchError(f"股票数据缺少列: {col}")

    df["代码"] = df["代码"].astype(str).str.zfill(6)
    df = df[df["代码"].isin(STOCK_SYMBOLS)].copy()

    if df.empty:
        raise FetchError("未能获取到任何汇金股票行情数据")

    for col in ["最新价", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("获取股票行情: %d 条", len(df))
    return df.reset_index(drop=True)


def fetch_huijin_announcements() -> list[dict]:
    """
    查询与"中央汇金"相关的近期公告（增减持披露）。
    使用 ak.stock_notice_report 按关键词搜索。
    失败时返回空列表（公告为非关键路径）。
    """
    keywords = ["中央汇金", "汇金"]
    results: list[dict] = []
    try:
        for kw in keywords:
            try:
                df = ak.stock_notice_report(symbol=kw, date="")
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        results.append({
                            "title": str(row.get("标题", row.get("公告标题", ""))),
                            "date":  str(row.get("公告日期", row.get("时间", ""))),
                            "symbol": str(row.get("代码", "")),
                            "name":   str(row.get("名称", "")),
                        })
            except Exception as exc:
                logger.warning("公告查询失败(%s): %s", kw, exc)
            time.sleep(0.5)
    except Exception as exc:
        logger.warning("公告模块异常: %s", exc)

    # 去重（同标题+代码只保留一条）
    seen: set[str] = set()
    unique: list[dict] = []
    for item in results:
        key = f"{item['symbol']}|{item['title']}"
        if key not in seen:
            seen.add(key)
            unique.append(item)

    logger.info("获取汇金相关公告: %d 条", len(unique))
    return unique
