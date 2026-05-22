import os

# 填入你的 Server酱 SendKey（在 https://sct.ftqq.com 注册后获取）
SEND_KEY: str = os.environ.get("SERVERCHAN_SEND_KEY", "your_send_key_here")

# 数据快照文件路径（记录前一日价格，用于对比）
SNAPSHOT_PATH: str = os.path.join(os.path.dirname(__file__), "data", "snapshot.json")

# 日志文件路径
LOG_PATH: str = os.path.join(os.path.dirname(__file__), "data", "run.log")

# 护盘信号阈值
INTERVENTION_ETF_MIN_COUNT: int = 4     # 至少几只ETF上涨才触发信号
INTERVENTION_AVG_PCT_STRONG: float = 2.0  # 强护盘：ETF平均涨幅%
INTERVENTION_AVG_PCT_MILD: float = 1.0   # 温和护盘：ETF平均涨幅%

# 值得标红的单支涨跌幅阈值
SIGNIFICANT_MOVE_PCT: float = 1.5

# AKShare 请求重试次数与间隔
FETCH_RETRIES: int = 3
FETCH_RETRY_DELAY: float = 5.0
