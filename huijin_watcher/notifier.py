import logging
from typing import Optional

import requests

from analyzer import AnalysisResult, InterventionSignal, PortfolioResult, QuoteItem

logger = logging.getLogger(__name__)

_BILLION = 1e8   # 亿


def _fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _fmt_value(val: float) -> str:
    """将元转换为亿元字符串。"""
    return f"{val / _BILLION:.1f}亿"


def _signal_emoji(signal: InterventionSignal) -> str:
    if not signal.triggered:
        return "⬜"
    return "🔴" if signal.level == "强护盘" else "🟡"


def _build_title(result: AnalysisResult) -> str:
    stock_pct = result.stock.avg_pct_change
    etf_pct = result.etf.avg_pct_change
    overall = (stock_pct + etf_pct) / 2
    signal_tag = f" | {result.signal.level}" if result.signal.triggered else ""
    new_tag = f" | {len(result.new_announcements)}条新公告" if result.new_announcements else ""
    return f"汇金持仓 {_fmt_pct(overall)}{signal_tag}{new_tag}"


def _build_etf_table(etf: PortfolioResult) -> str:
    lines = [
        "## ETF持仓",
        f"> 组合今日: **{_fmt_pct(etf.avg_pct_change)}**  |  估算市值变动: {_fmt_value(etf.total_value_change)}",
        "",
        "| ETF名称 | 代码 | 最新价 | 今日涨跌 |",
        "|--------|------|--------|---------|",
    ]
    for item in etf.items:
        pct_str = _fmt_pct(item.pct_change)
        if item.pct_change >= 1.5:
            pct_str = f"**{pct_str}**"
        elif item.pct_change <= -1.5:
            pct_str = f"~~{pct_str}~~"
        lines.append(f"| {item.name} | {item.symbol} | {item.price:.4f} | {pct_str} |")
    return "\n".join(lines)


def _build_stock_table(stock: PortfolioResult) -> str:
    lines = [
        "## 股票持仓",
        f"> 组合今日: **{_fmt_pct(stock.avg_pct_change)}**  |  估算市值变动: {_fmt_value(stock.total_value_change)}",
        "",
        "| 股票名称 | 代码 | 最新价 | 今日涨跌 |",
        "|--------|------|--------|---------|",
    ]
    for item in stock.items:
        pct_str = _fmt_pct(item.pct_change)
        if item.pct_change >= 1.5:
            pct_str = f"**{pct_str}**"
        elif item.pct_change <= -1.5:
            pct_str = f"~~{pct_str}~~"
        lines.append(f"| {item.name} | {item.symbol} | {item.price:.2f} | {pct_str} |")
    return "\n".join(lines)


def _build_signal_section(signal: InterventionSignal) -> str:
    emoji = _signal_emoji(signal)
    if signal.triggered:
        return (
            f"## {emoji} 护盘信号: {signal.level}\n"
            f"> {signal.reason}\n"
        )
    return f"## {emoji} 护盘信号: 无明显信号\n> {signal.reason}\n"


def _build_announcement_section(
    new_items: list[dict],
    all_items: list[dict],
) -> str:
    if not all_items:
        return "## 公告\n> 今日无相关公告\n"

    lines = ["## 公告"]
    new_keys = {f"{a.get('symbol','')}|{a.get('title','')}" for a in new_items}
    for a in all_items[:10]:
        key = f"{a.get('symbol','')}|{a.get('title','')}"
        prefix = "**[新]** " if key in new_keys else ""
        title = a.get("title", "")
        date = a.get("date", "")
        name = a.get("name", a.get("symbol", ""))
        lines.append(f"- {prefix}{name}: {title}（{date}）")
    return "\n".join(lines) + "\n"


def build_message(result: AnalysisResult) -> tuple[str, str]:
    title = _build_title(result)

    sections = [
        f"# 中央汇金持仓日报 · {result.trade_date} 14:30",
        "",
        _build_signal_section(result.signal),
        _build_etf_table(result.etf),
        "",
        _build_stock_table(result.stock),
        "",
        _build_announcement_section(result.new_announcements, result.all_announcements),
    ]

    if result.fetch_errors:
        sections.append("## 警告")
        for err in result.fetch_errors:
            sections.append(f"> ⚠ {err}")

    total_change = result.stock.total_value_change + result.etf.total_value_change
    sections += [
        "",
        "---",
        f"估算持仓总市值变动: **{_fmt_value(total_change)}**",
        f"数据来源: AKShare / 东方财富  |  推送: Server酱",
    ]

    return title, "\n".join(sections)


def push_notification(send_key: str, title: str, content: str, timeout: int = 15) -> bool:
    if not send_key or send_key == "your_send_key_here":
        logger.error("SEND_KEY 未配置，跳过推送")
        return False

    url = f"https://sctapi.ftqq.com/{send_key}.send"
    try:
        resp = requests.post(
            url,
            data={"title": title, "desp": content},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") == 0:
            logger.info("Server酱推送成功")
            return True
        logger.error("Server酱返回错误: %s", body)
        return False
    except Exception as exc:
        logger.error("Server酱推送异常: %s", exc)
        return False
