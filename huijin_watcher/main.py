#!/usr/bin/env python3
"""
中央汇金持仓分析 · 每日14:30推送
用法：
  直接运行：python3 main.py
  定时任务：crontab -e 添加
    SERVERCHAN_SEND_KEY=你的SendKey
    30 14 * * 1-5 /usr/bin/python3 /home/user/-/huijin_watcher/main.py >> /home/user/-/huijin_watcher/data/run.log 2>&1
"""
import logging
import os
import sys
from datetime import datetime

# 确保从脚本所在目录导入模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import akshare as ak

from analyzer import (
    AnalysisResult,
    analyze_etfs,
    analyze_stocks,
    detect_intervention,
    detect_new_announcements,
    load_snapshot,
    save_snapshot,
)
from config import LOG_PATH, SEND_KEY
from fetcher import FetchError, fetch_etf_quotes, fetch_huijin_announcements, fetch_stock_quotes
from notifier import build_message, push_notification


def setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("main")


def is_trading_day() -> bool:
    """检查今天是否为交易日（工作日）。"""
    weekday = datetime.now().weekday()
    if weekday >= 5:
        return False
    try:
        trade_dates = ak.tool_trade_date_hist_sina()
        today_str = datetime.now().strftime("%Y-%m-%d")
        col = trade_dates.columns[0]
        dates = trade_dates[col].astype(str).tolist()
        return today_str in dates
    except Exception:
        # AKShare 获取交易日历失败时，回退到仅判断工作日
        return True


def main() -> int:
    logger = setup_logging()
    logger.info("=== 中央汇金持仓分析启动 ===")

    if not is_trading_day():
        logger.info("今日非交易日，退出")
        return 0

    trade_date = datetime.now().strftime("%Y-%m-%d")
    fetch_errors: list[str] = []

    # ── 抓取行情 ──────────────────────────────────────────
    try:
        etf_df = fetch_etf_quotes()
    except FetchError as exc:
        logger.error("ETF行情获取失败: %s", exc)
        push_notification(SEND_KEY, "汇金监控异常", f"ETF行情获取失败: {exc}")
        return 1

    try:
        stock_df = fetch_stock_quotes()
    except FetchError as exc:
        logger.error("股票行情获取失败: %s", exc)
        push_notification(SEND_KEY, "汇金监控异常", f"股票行情获取失败: {exc}")
        return 1

    # ── 抓取公告（非关键路径）────────────────────────────
    announcements = fetch_huijin_announcements()

    # ── 分析 ──────────────────────────────────────────────
    snapshot = load_snapshot()
    etf_result = analyze_etfs(etf_df)
    stock_result = analyze_stocks(stock_df)
    signal = detect_intervention(etf_result)
    new_announcements = detect_new_announcements(announcements, snapshot)

    result = AnalysisResult(
        trade_date=trade_date,
        stock=stock_result,
        etf=etf_result,
        signal=signal,
        new_announcements=new_announcements,
        all_announcements=announcements,
        fetch_errors=fetch_errors,
    )

    logger.info(
        "分析完成 | 股票组合: %+.2f%% | ETF组合: %+.2f%% | 护盘信号: %s",
        stock_result.avg_pct_change,
        etf_result.avg_pct_change,
        signal.level,
    )

    # ── 构建消息并推送 ───────────────────────────────────
    title, content = build_message(result)
    success = push_notification(SEND_KEY, title, content)

    if not success:
        logger.warning("推送失败，但继续保存快照")

    # ── 保存快照（无论推送是否成功）───────────────────────
    save_snapshot(trade_date, stock_result, etf_result, announcements)

    logger.info("=== 运行完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
