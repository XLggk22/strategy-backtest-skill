from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_CATALOG_PATH = ROOT / "references" / "strategy_catalog.json"
INDEX_CATALOG_PATH = ROOT / "references" / "index_catalog.json"
DATA_DIR = ROOT / "data"
DEFAULT_REPORT_PATH = ROOT / "docs" / "backtest_report_latest.md"
DEFAULT_CHART_PATH = ROOT / "docs" / "backtest_summary_chart.svg"
BASELINE_AMOUNT = 1000.0
ROW_RE = re.compile(
    r"<tr class=\"(?:odd|even)\">\s*<td>([^<]+)</td>\s*<td>(.*?)</td>\s*</tr>",
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


@dataclass
class Row:
    when: date
    price_index: float
    total_return_index: float | None
    pe: float | None


@dataclass
class StrategyResult:
    strategy_id: str
    name: str
    rule_description: str
    rule_example: str
    total_invested: float
    final_value: float
    profit: float
    total_return: float
    annual_irr: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    active_months: int
    longest_streak: int
    trigger_counts: dict[str, int]
    key_periods: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest strategy catalog against monthly index data.")
    parser.add_argument("--data-csv", help="Optional monthly CSV path. If omitted, the script auto-resolves local index data.")
    parser.add_argument("--start-date", help="Backtest start date in YYYY-MM-DD")
    parser.add_argument("--return-mode", choices=["price", "total_return"], default="price")
    parser.add_argument("--index-name", default="Custom Index", help="Index name shown in the report, for example S&P 500 or CSI 300")
    parser.add_argument(
        "--market-profile",
        choices=["auto", "us", "cn", "generic"],
        default="auto",
        help="Market-context profile used for trigger-period commentary",
    )
    parser.add_argument("--strategy-ids", help="Comma-separated strategy IDs to compare")
    parser.add_argument("--custom-strategy-file", help="Optional JSON file with extra strategies")
    parser.add_argument("--catalog", default=str(STRATEGY_CATALOG_PATH), help="Override built-in strategy catalog path")
    parser.add_argument("--index-catalog", default=str(INDEX_CATALOG_PATH), help="Override built-in index catalog path")
    parser.add_argument("--list-strategies", action="store_true", help="Print the strategy catalog table")
    parser.add_argument("--list-indices", action="store_true", help="Print the built-in index catalog table")
    parser.add_argument("--top-periods", type=int, default=3, help="How many trigger periods to show per strategy")
    parser.add_argument("--output", help="Optional output Markdown file")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(catalog_path: Path, custom_path: Path | None = None) -> list[dict[str, Any]]:
    catalog = load_json(catalog_path)
    if custom_path:
        custom_data = load_json(custom_path)
        if isinstance(custom_data, dict):
            catalog.append(custom_data)
        else:
            catalog.extend(custom_data)
    return catalog


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def normalize_month(value: date) -> date:
    return date(value.year, value.month, 1)


def load_rows(csv_path: Path) -> list[Row]:
    rows: list[Row] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            when = normalize_month(datetime.strptime(raw["date"], "%Y-%m-%d").date())
            rows.append(
                Row(
                    when=when,
                    price_index=float(raw["price_index"]),
                    total_return_index=parse_optional_float(raw.get("total_return_index")),
                    pe=parse_optional_float(raw.get("pe")),
                )
            )
    rows.sort(key=lambda item: item.when)
    return rows


def choose_series_value(row: Row, return_mode: str) -> float:
    if return_mode == "price":
        return row.price_index
    if row.total_return_index is None:
        raise ValueError("Selected return mode requires total_return_index values in the CSV.")
    return row.total_return_index


def percentile_rank(history: list[float], current: float) -> float:
    if not history:
        return 50.0
    less_or_equal = sum(1 for item in history if item <= current)
    return 100.0 * less_or_equal / len(history)


def monthly_irr(cashflows: list[tuple[date, float]]) -> float | None:
    if not cashflows:
        return None
    first = cashflows[0][0]
    series = []
    for when, amount in cashflows:
        offset = (when.year - first.year) * 12 + (when.month - first.month)
        series.append((offset, amount))

    def npv(rate: float) -> float:
        total = 0.0
        for offset, amount in series:
            total += amount / ((1.0 + rate) ** offset)
        return total

    low = -0.5
    high = 1.0
    npv_low = npv(low)
    npv_high = npv(high)
    expand = 0
    while npv_low * npv_high > 0 and expand < 50:
        high *= 2
        npv_high = npv(high)
        expand += 1
    if npv_low * npv_high > 0:
        return None

    for _ in range(200):
        mid = (low + high) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-10:
            break
        if npv_low * npv_mid <= 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    monthly_rate = (low + high) / 2
    return (1.0 + monthly_rate) ** 12 - 1.0


def max_drawdown(series: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in series:
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = value / peak - 1.0
        worst = min(worst, drawdown)
    return abs(worst)


def annualized_sharpe(monthly_returns: list[float]) -> float | None:
    if len(monthly_returns) < 2:
        return None
    mean_value = sum(monthly_returns) / len(monthly_returns)
    variance = sum((item - mean_value) ** 2 for item in monthly_returns) / (len(monthly_returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return None
    return math.sqrt(12.0) * mean_value / std_dev


def format_threshold(value: float) -> str:
    return f">{int(round(value * 100))}%"


def infer_market_profile(index_name: str, requested_profile: str) -> str:
    if requested_profile != "auto":
        return requested_profile

    normalized = index_name.lower()
    us_keywords = ["s&p", "sp500", "spy", "nasdaq", "ndx", "dow", "russell", "qqq"]
    cn_keywords = ["沪深300", "沪深", "中证", "上证", "深证", "创业板", "csi 300", "csi300", "hs300"]

    if any(keyword in normalized for keyword in us_keywords):
        return "us"
    if any(keyword in normalized for keyword in cn_keywords):
        return "cn"
    return "generic"


def market_profile_label(profile: str) -> str:
    labels = {
        "us": "美股市场",
        "cn": "中国市场",
        "generic": "通用市场",
    }
    return labels.get(profile, profile)


def evaluate_strategy(strategy: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, list[str]]:
    kind = strategy["kind"]

    if kind == "fixed_amount":
        return float(strategy["amount"]), []

    if kind == "pe_percentile":
        pe_value = ctx["pe_percentile"]
        if pe_value is None:
            raise ValueError(f"Strategy '{ctx['name']}' requires PE data.")
        if pe_value > float(strategy["high_threshold"]):
            return float(strategy["high_amount"]), [f"pe:{format_threshold(float(strategy['high_threshold']))}"]
        if pe_value < float(strategy["low_threshold"]):
            return float(strategy["low_amount"]), [f"pe:<{int(round(float(strategy['low_threshold'])))}%"]
        low = int(round(float(strategy["low_threshold"])))
        high = int(round(float(strategy["high_threshold"])))
        return float(strategy["mid_amount"]), [f"pe:{low}-{high}%"]

    if kind == "drawdown_total":
        amount = float(strategy.get("base_amount", 0.0))
        events: list[str] = []
        for band in sorted(strategy.get("bands", []), key=lambda item: float(item["threshold"])):
            if ctx["drawdown"] > float(band["threshold"]):
                amount = float(band["total_amount"])
                events = [f"drawdown:{format_threshold(float(band['threshold']))}"]
        return amount, events

    if kind == "drawdown_cumulative":
        amount = float(strategy.get("base_amount", 0.0))
        events: list[str] = []
        for band in sorted(strategy.get("bands", []), key=lambda item: float(item["threshold"])):
            if ctx["drawdown"] > float(band["threshold"]):
                amount += float(band["extra_amount"])
                events.append(f"drawdown:{format_threshold(float(band['threshold']))}")
        return amount, events

    if kind == "ma12_deviation":
        deviation = ctx["ma12_deviation"]
        if deviation <= float(strategy["lower_threshold"]):
            pct = abs(float(strategy["lower_threshold"])) * 100
            return float(strategy["lower_amount"]), [f"ma12:<=-{int(round(pct))}%"]
        if deviation >= float(strategy["upper_threshold"]):
            pct = float(strategy["upper_threshold"]) * 100
            return float(strategy["upper_amount"]), [f"ma12:>=+{int(round(pct))}%"]
        return float(strategy.get("base_amount", BASELINE_AMOUNT)), []

    if kind == "composite_sum":
        total = 0.0
        events: list[str] = []
        for component in strategy.get("components", []):
            component_amount, component_events = evaluate_strategy(component, ctx)
            total += component_amount
            events.extend(component_events)
        return total, events

    raise ValueError(f"Unsupported strategy kind: {kind}")


def market_context_windows(profile: str) -> list[tuple[date, date, str]]:
    if profile == "us":
        return [
            (date(2008, 1, 1), date(2010, 6, 1), "全球金融危机与后续修复"),
            (date(2011, 7, 1), date(2012, 1, 1), "欧债危机与美债降级波动"),
            (date(2020, 2, 1), date(2020, 6, 1), "疫情冲击与快速反弹"),
            (date(2022, 1, 1), date(2022, 12, 1), "通胀与加息驱动的熊市"),
        ]
    if profile == "cn":
        return [
            (date(2008, 1, 1), date(2009, 12, 1), "全球金融危机对A股的冲击与修复"),
            (date(2015, 6, 1), date(2016, 2, 1), "A股杠杆牛与股灾去杠杆"),
            (date(2018, 1, 1), date(2019, 1, 1), "去杠杆与中美贸易摩擦调整"),
            (date(2020, 2, 1), date(2020, 6, 1), "疫情冲击与国内流动性修复"),
            (date(2022, 1, 1), date(2022, 12, 1), "地产压力与疫情扰动下的回撤"),
        ]
    return [
        (date(2008, 1, 1), date(2010, 6, 1), "全球金融危机与后续修复"),
        (date(2020, 2, 1), date(2020, 6, 1), "疫情冲击与快速反弹"),
        (date(2022, 1, 1), date(2022, 12, 1), "全球紧缩与风险资产调整"),
    ]


def major_market_context(start: date, end: date, profile: str) -> str:
    windows = market_context_windows(profile)
    best_overlap = 0
    best_label = ""
    for window_start, window_end, label in windows:
        overlap = (min(end, window_end) - max(start, window_start)).days
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    if best_label:
        return best_label
    return "长时间回撤或恢复阶段"


def ranking(values: list[float], target: float, reverse: bool) -> int:
    ordered = sorted(values, reverse=reverse)
    return ordered.index(target) + 1


def objective_comment(result: StrategyResult, peers: list[StrategyResult]) -> str:
    returns = [item.total_return for item in peers]
    irrs = [item.annual_irr or float("-inf") for item in peers]
    drawdowns = [item.max_drawdown for item in peers]
    invested = [item.total_invested for item in peers]

    return_rank = ranking(returns, result.total_return, True)
    irr_rank = ranking(irrs, result.annual_irr or float("-inf"), True)
    drawdown_rank = ranking(drawdowns, result.max_drawdown, False)
    invested_rank = ranking(invested, result.total_invested, False)
    peer_count = len(peers)

    parts = [
        f"总收益率排名 {return_rank}/{peer_count}",
        f"年化IRR排名 {irr_rank}/{peer_count}",
        f"最大回撤排名 {drawdown_rank}/{peer_count}",
        f"总投入压力排名 {invested_rank}/{peer_count}",
    ]

    if return_rank <= max(1, peer_count // 3) and drawdown_rank <= max(1, peer_count // 3):
        summary = "综合表现强，收益与回撤控制都处于前列。"
    elif invested_rank > math.ceil(peer_count * 0.75) and return_rank > math.ceil(peer_count * 0.5):
        summary = "结果较依赖高投入，资金效率不占优。"
    elif drawdown_rank > math.ceil(peer_count * 0.75):
        summary = "回撤压力偏大，实盘执行难度较高。"
    else:
        summary = "表现中性，更适合作为收益或风险偏好的折中方案。"

    return "；".join(parts) + "。 " + summary


def selected_strategies_need_pe(strategies: list[dict[str, Any]]) -> bool:
    def needs_pe(strategy: dict[str, Any]) -> bool:
        kind = strategy["kind"]
        if kind == "pe_percentile":
            return True
        if kind == "composite_sum":
            return any(needs_pe(component) for component in strategy.get("components", []))
        return False

    return any(needs_pe(strategy) for strategy in strategies)


def selected_strategies_need_ma12(strategies: list[dict[str, Any]]) -> bool:
    def needs_ma12(strategy: dict[str, Any]) -> bool:
        kind = strategy["kind"]
        if kind == "ma12_deviation":
            return True
        if kind == "composite_sum":
            return any(needs_ma12(component) for component in strategy.get("components", []))
        return False

    return any(needs_ma12(strategy) for strategy in strategies)


def previous_month_start(today: date) -> date:
    first = date(today.year, today.month, 1)
    if first.month == 1:
        return date(first.year - 1, 12, 1)
    return date(first.year, first.month - 1, 1)


def assess_data_file(
    csv_path: Path,
    start_date: date,
    return_mode: str,
    needs_pe: bool,
) -> tuple[bool, list[str], list[Row]]:
    reasons: list[str] = []
    if not csv_path.exists():
        return False, ["本地数据文件不存在"], []

    rows = load_rows(csv_path)
    if not rows:
        return False, ["本地数据文件为空"], []

    if return_mode == "total_return" and any(row.total_return_index is None for row in rows):
        reasons.append("缺少 total_return_index 列或数据")

    if needs_pe and any(row.pe is None for row in rows):
        reasons.append("所选策略需要 PE 数据，但本地数据不完整")

    if not any(row.when >= start_date for row in rows):
        reasons.append("没有覆盖回测起始日期之后的数据")

    freshness_cutoff = previous_month_start(date.today())
    latest = max(row.when for row in rows)
    if latest < freshness_cutoff:
        reasons.append(f"数据最新日期 {latest} 早于建议更新阈值 {freshness_cutoff}")

    return len(reasons) == 0, reasons, rows


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 StrategyBacktestSkill/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_json(url: str) -> Any:
    return json.loads(fetch_text(url))


def fetch_yahoo_monthly_series(symbol: str, range_value: str = "25y", interval: str = "1mo") -> dict[date, dict[str, float | None]]:
    query = urlencode(
        {
            "range": range_value,
            "interval": interval,
            "includeAdjustedClose": "true",
            "events": "div,splits",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
    payload = fetch_json(url)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    closes = quote.get("close", [])
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])

    series: dict[date, dict[str, float | None]] = {}
    for idx, timestamp in enumerate(timestamps):
        close = closes[idx] if idx < len(closes) else None
        adjclose = adj[idx] if idx < len(adj) else None
        if close is None:
            continue
        when = normalize_month(datetime.fromtimestamp(timestamp, tz=timezone.utc).date())
        series[when] = {
            "price_index": float(close),
            "total_return_index": float(adjclose) if adjclose is not None else float(close),
            "pe": None,
        }
    return series


def fetch_multpl_monthly_pe(url: str) -> dict[date, float]:
    text = fetch_text(url)
    values: dict[date, float] = {}
    for date_text, value_html in ROW_RE.findall(text):
        when = normalize_month(datetime.strptime(date_text.strip(), "%b %d, %Y").date())
        cleaned = html.unescape(TAG_RE.sub(" ", value_html)).replace("\xa0", " ")
        matches = NUM_RE.findall(cleaned)
        if not matches:
            continue
        values[when] = float(matches[-1].replace(",", ""))
    return values


def write_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "price_index", "total_return_index", "pe"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def download_index_data(index_def: dict[str, Any], target_path: Path) -> list[str]:
    download = index_def.get("download")
    if not download:
        raise ValueError(f"指数 '{index_def['name']}' 没有配置自动下载源。")

    actions: list[str] = []
    provider = download.get("provider")
    if provider != "yahoo_chart":
        raise ValueError(f"暂不支持下载提供方: {provider}")

    symbol = download["symbol"]
    range_value = download.get("range", "25y")
    interval = download.get("interval", "1mo")
    base_series = fetch_yahoo_monthly_series(symbol, range_value=range_value, interval=interval)
    actions.append(f"已从 Yahoo Finance 下载 {index_def['name']} 代理数据，符号 {symbol}")

    pe_provider = download.get("pe_provider")
    if pe_provider and pe_provider.get("provider") == "multpl_pe":
        pe_values = fetch_multpl_monthly_pe(pe_provider["url"])
        for when, pe_value in pe_values.items():
            if when in base_series:
                base_series[when]["pe"] = pe_value
        actions.append("已合并 Multpl 月度 PE 数据")

    output_rows = []
    for when in sorted(base_series):
        values = base_series[when]
        output_rows.append(
            {
                "date": when.isoformat(),
                "price_index": f"{float(values['price_index']):.6f}",
                "total_return_index": f"{float(values['total_return_index']):.6f}" if values["total_return_index"] is not None else "",
                "pe": f"{float(values['pe']):.6f}" if values["pe"] is not None else "",
            }
        )
    write_rows(target_path, output_rows)
    actions.append(f"已写入本地数据文件 {target_path}")
    return actions


def find_index_definition(index_catalog: list[dict[str, Any]], index_name: str) -> dict[str, Any] | None:
    if not index_name or index_name == "Custom Index":
        return None
    normalized = index_name.strip().lower()
    for item in index_catalog:
        names = [item["name"], *item.get("aliases", [])]
        for name in names:
            if normalized == name.strip().lower():
                return item
    for item in index_catalog:
        names = [item["name"], *item.get("aliases", [])]
        for name in names:
            if normalized in name.strip().lower() or name.strip().lower() in normalized:
                return item
    return None


def resolve_data_file(
    args: argparse.Namespace,
    index_catalog: list[dict[str, Any]],
    strategies: list[dict[str, Any]],
) -> tuple[Path, dict[str, Any] | None, list[str]]:
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    needs_pe = selected_strategies_need_pe(strategies)
    actions: list[str] = []
    index_def = find_index_definition(index_catalog, args.index_name)

    if args.data_csv:
        csv_path = Path(args.data_csv)
    else:
        if index_def is None:
            raise ValueError("未指定 --data-csv，且无法根据 --index-name 匹配内置指数清单。")
        csv_path = ROOT / index_def["default_local_csv"]
        actions.append(f"已根据指数清单自动定位本地数据文件 {csv_path}")

    okay, reasons, _ = assess_data_file(csv_path, start_date, args.return_mode, needs_pe)
    if not okay:
        actions.append("检测到本地数据缺失或不完整：" + "；".join(reasons))
        if index_def is not None and index_def.get("download"):
            actions.extend(download_index_data(index_def, csv_path))
            okay, reasons, _ = assess_data_file(csv_path, start_date, args.return_mode, needs_pe)
            if not okay:
                raise ValueError("自动下载后数据仍不完整：" + "；".join(reasons))
        else:
            raise ValueError("本地数据不完整，且当前指数没有配置自动下载源：" + "；".join(reasons))
    else:
        actions.append("本地数据完整，直接用于回测")

    return csv_path, index_def, actions


def require_fields(strategies: list[dict[str, Any]], rows: list[Row], return_mode: str) -> None:
    if return_mode == "total_return" and any(row.total_return_index is None for row in rows):
        raise ValueError("return-mode=total_return requires total_return_index for every row.")

    if selected_strategies_need_pe(strategies) and any(row.pe is None for row in rows):
        raise ValueError("Selected strategies require a 'pe' column with values for every row.")


def build_context(rows: list[Row], index: int, return_mode: str) -> dict[str, Any]:
    current = rows[index]
    current_value = choose_series_value(current, return_mode)
    peak = max(choose_series_value(row, return_mode) for row in rows[: index + 1])
    drawdown = max(0.0, 1.0 - current_value / peak)

    ma_rows = rows[max(0, index - 11) : index + 1]
    ma12 = sum(choose_series_value(row, return_mode) for row in ma_rows) / len(ma_rows)
    ma12_deviation = current_value / ma12 - 1.0

    pe_history = [row.pe for row in rows[:index] if row.pe is not None]
    pe_percentile = percentile_rank(pe_history + [current.pe], current.pe) if current.pe is not None else None

    return {
        "date": current.when,
        "series_value": current_value,
        "drawdown": drawdown,
        "ma12_deviation": ma12_deviation,
        "pe_percentile": pe_percentile,
        "name": "",
    }


def summarize_periods(periods: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    ordered = sorted(periods, key=lambda item: (abs(item["extra_sum"]), item["months"]), reverse=True)
    return ordered[:top_n]


def backtest_strategy(
    strategy: dict[str, Any],
    rows: list[Row],
    start_index: int,
    return_mode: str,
    top_periods: int,
    market_profile: str,
) -> StrategyResult:
    shares = 0.0
    invested = 0.0
    cashflows: list[tuple[date, float]] = []
    capital_multiple_series: list[float] = []
    trigger_counts: dict[str, int] = {}
    periods: list[dict[str, Any]] = []
    current_period: dict[str, Any] | None = None
    longest_streak = 0
    current_streak = 0

    monthly_returns: list[float] = []
    for idx in range(start_index, len(rows)):
        ctx = build_context(rows, idx, return_mode)
        ctx["name"] = strategy["name"]
        amount, events = evaluate_strategy(strategy, ctx)
        current_value = ctx["series_value"]

        shares += amount / current_value
        invested += amount
        cashflows.append((rows[idx].when, -amount))
        capital_multiple_series.append((shares * current_value) / invested)

        for event in events:
            trigger_counts[event] = trigger_counts.get(event, 0) + 1

        active = abs(amount - BASELINE_AMOUNT) > 1e-9
        if active:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
            if current_period is None:
                current_period = {
                    "start": rows[idx].when,
                    "end": rows[idx].when,
                    "months": 0,
                    "extra_sum": 0.0,
                    "max_drawdown": 0.0,
                }
            current_period["end"] = rows[idx].when
            current_period["months"] += 1
            current_period["extra_sum"] += amount - BASELINE_AMOUNT
            current_period["max_drawdown"] = max(current_period["max_drawdown"], ctx["drawdown"])
        else:
            current_streak = 0
            if current_period is not None:
                current_period["context"] = major_market_context(current_period["start"], current_period["end"], market_profile)
                periods.append(current_period)
                current_period = None

        if idx > start_index:
            previous = choose_series_value(rows[idx - 1], return_mode)
            monthly_returns.append(current_value / previous - 1.0)

    if current_period is not None:
        current_period["context"] = major_market_context(current_period["start"], current_period["end"], market_profile)
        periods.append(current_period)

    final_value = shares * choose_series_value(rows[-1], return_mode)
    cashflows.append((rows[-1].when, final_value))

    total_return = final_value / invested - 1.0
    annual_irr = monthly_irr(cashflows)
    max_dd = max_drawdown(capital_multiple_series + [final_value / invested])
    sharpe = annualized_sharpe(monthly_returns)

    active_months = sum(item["months"] for item in periods)

    return StrategyResult(
        strategy_id=strategy["id"],
        name=strategy["name"],
        rule_description=strategy["rule_description"],
        rule_example=strategy["rule_example"],
        total_invested=invested,
        final_value=final_value,
        profit=final_value - invested,
        total_return=total_return,
        annual_irr=annual_irr,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        active_months=active_months,
        longest_streak=longest_streak,
        trigger_counts=dict(sorted(trigger_counts.items())),
        key_periods=summarize_periods(periods, top_periods),
    )


def market_state_summary(rows: list[Row], start_index: int, return_mode: str) -> dict[str, int]:
    counts = {
        "<=5%": 0,
        "5%-10%": 0,
        "10%-20%": 0,
        "20%-30%": 0,
        "30%-40%": 0,
        ">40%": 0,
    }
    for idx in range(start_index, len(rows)):
        ctx = build_context(rows, idx, return_mode)
        dd = ctx["drawdown"]
        if dd > 0.40:
            counts[">40%"] += 1
        elif dd > 0.30:
            counts["30%-40%"] += 1
        elif dd > 0.20:
            counts["20%-30%"] += 1
        elif dd > 0.10:
            counts["10%-20%"] += 1
        elif dd > 0.05:
            counts["5%-10%"] += 1
        else:
            counts["<=5%"] += 1
    return counts


def list_strategy_table(catalog: list[dict[str, Any]]) -> str:
    lines = [
        "| 策略编号 | 策略 | 规则描述 | 规则描述样例 |",
        "|---|---|---|---|",
    ]
    for item in catalog:
        lines.append(f"| {item['id']} | {item['name']} | {item['rule_description']} | {item['rule_example']} |")
    return "\n".join(lines)


def list_index_table(catalog: list[dict[str, Any]]) -> str:
    lines = [
        "| 指数编号 | 指数名称 | 别名 | 市场画像 | 默认本地文件 | 自动下载 | 说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in catalog:
        aliases = " / ".join(item.get("aliases", []))
        downloadable = "是" if item.get("download") else "否"
        lines.append(
            f"| {item['id']} | {item['name']} | {aliases} | {market_profile_label(item.get('market_profile', 'generic'))} | "
            f"{item['default_local_csv']} | {downloadable} | {item.get('notes', '')} |"
        )
    return "\n".join(lines)


def comparison_table(results: list[StrategyResult]) -> str:
    header = [
        "| 策略编号 | 策略 | 总投入 | 期末资产 | 总盈利 | 总收益率 | 年化IRR | 最大回撤 | 夏普率 | 规则描述 | 规则描述样例 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    ordered = sorted(
        results,
        key=lambda item: (
            -item.total_return,
            -(item.annual_irr if item.annual_irr is not None else float("-inf")),
            item.max_drawdown,
            item.total_invested,
        ),
    )
    for item in ordered:
        irr_text = "n/a" if item.annual_irr is None else f"{item.annual_irr * 100:.2f}%"
        sharpe_text = "n/a" if item.sharpe_ratio is None else f"{item.sharpe_ratio:.3f}"
        header.append(
            f"| {item.strategy_id} | {item.name} | {item.total_invested:,.2f} | {item.final_value:,.2f} | "
            f"{item.profit:,.2f} | {item.total_return * 100:.2f}% | {irr_text} | {item.max_drawdown * 100:.2f}% | "
            f"{sharpe_text} | {item.rule_description} | {item.rule_example} |"
        )
    return "\n".join(header)


def render_trigger_counts(trigger_counts: dict[str, int]) -> str:
    if not trigger_counts:
        return "- 无额外触发"
    return "\n".join(f"- `{key}`: {value} 次" for key, value in trigger_counts.items())


def render_periods(periods: list[dict[str, Any]]) -> str:
    if not periods:
        return "- 无显著触发窗口"
    lines = []
    for item in periods:
        lines.append(
            f"- {item['start']} 到 {item['end']}，{item['months']} 个月，额外投入 {item['extra_sum']:,.2f}，"
            f"区间最大回撤 {item['max_drawdown'] * 100:.2f}%，市场背景：{item['context']}"
        )
    return "\n".join(lines)


def render_report(
    index_name: str,
    market_profile: str,
    data_path: Path,
    data_actions: list[str],
    rows: list[Row],
    start_index: int,
    return_mode: str,
    start_date: date,
    results: list[StrategyResult],
) -> str:
    market_summary = market_state_summary(rows, start_index, return_mode)
    lines = [
        "# Strategy Backtest Report",
        "",
        f"- 回测指数: {index_name}",
        f"- 市场画像: {market_profile_label(market_profile)}",
        f"- 数据文件: {data_path}",
        f"- 回测起点: {start_date}",
        f"- 回测终点: {rows[-1].when}",
        f"- 回测模式: {'纯指数收益' if return_mode == 'price' else '全收益指数'}",
        f"- 回测月份数: {len(rows) - start_index}",
        "",
        "## 数据准备",
        "",
    ]
    for action in data_actions:
        lines.append(f"- {action}")

    lines.extend(
        [
            "",
            "## 策略对比",
            "",
            comparison_table(results),
            "",
            "## 市场状态分布",
            "",
            "| 回撤区间 | 月数 |",
            "|---|---:|",
        ]
    )
    for label, value in market_summary.items():
        lines.append(f"| {label} | {value} |")

    for result in results:
        lines.extend(
            [
                "",
                f"## {result.strategy_id} {result.name}",
                "",
                f"- 规则描述: {result.rule_description}",
                f"- 规则描述样例: {result.rule_example}",
                f"- 触发活跃月份: {result.active_months}",
                f"- 最长连续触发: {result.longest_streak} 个月",
                "",
                "### 触发次数",
                "",
                render_trigger_counts(result.trigger_counts),
                "",
                "### 主要触发时间",
                "",
                render_periods(result.key_periods),
                "",
                "### 客观评价",
                "",
                f"- {objective_comment(result, results)}",
            ]
        )
    return "\n".join(lines) + "\n"


def write_default_report(report: str, explicit_output: str | None) -> list[Path]:
    written_paths: list[Path] = []
    DEFAULT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT_PATH.write_text(report, encoding="utf-8")
    written_paths.append(DEFAULT_REPORT_PATH)

    if explicit_output:
        explicit_path = Path(explicit_output)
        explicit_path.parent.mkdir(parents=True, exist_ok=True)
        explicit_path.write_text(report, encoding="utf-8")
        if explicit_path.resolve() != DEFAULT_REPORT_PATH.resolve():
            written_paths.append(explicit_path)
    return written_paths


def generate_default_chart(
    data_csv: Path,
    start_date: date,
    index_name: str,
    return_mode: str,
    market_profile: str,
) -> Path:
    render_script = Path(__file__).resolve().parent / "render_summary_chart.py"
    DEFAULT_CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(render_script),
        "--data-csv",
        str(data_csv),
        "--start-date",
        start_date.isoformat(),
        "--index-name",
        index_name,
        "--return-mode",
        return_mode,
        "--market-profile",
        market_profile,
        "--output",
        str(DEFAULT_CHART_PATH),
    ]
    subprocess.run(command, check=True)
    return DEFAULT_CHART_PATH


def main() -> None:
    args = parse_args()
    strategy_catalog = load_catalog(Path(args.catalog), Path(args.custom_strategy_file) if args.custom_strategy_file else None)
    index_catalog = load_json(Path(args.index_catalog))

    if args.list_strategies:
        output = list_strategy_table(strategy_catalog)
        if args.output:
            Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(output)
        return

    if args.list_indices:
        output = list_index_table(index_catalog)
        if args.output:
            Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(output)
        return

    if not args.start_date:
        raise SystemExit("--start-date is required unless --list-strategies or --list-indices is used.")

    selected_ids = None
    if args.strategy_ids:
        selected_ids = {item.strip() for item in args.strategy_ids.split(",") if item.strip()}
    strategies = [item for item in strategy_catalog if selected_ids is None or item["id"] in selected_ids]
    if not strategies:
        raise ValueError("No strategies were selected.")

    data_path, index_def, data_actions = resolve_data_file(args, index_catalog, strategies)
    rows = load_rows(data_path)
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    start_index = next((index for index, row in enumerate(rows) if row.when >= start_date), -1)
    if start_index == -1:
        raise ValueError("No rows remain after applying the start date.")

    if index_def and args.index_name == "Custom Index":
        args.index_name = index_def["name"]

    if index_def and args.market_profile == "auto":
        market_profile = index_def.get("market_profile", infer_market_profile(args.index_name, args.market_profile))
    else:
        market_profile = infer_market_profile(args.index_name, args.market_profile)

    require_fields(strategies, rows, args.return_mode)

    results = []
    for strategy in strategies:
        result = backtest_strategy(strategy, rows, start_index, args.return_mode, args.top_periods, market_profile)
        results.append(result)

    report = render_report(args.index_name, market_profile, data_path, data_actions, rows, start_index, args.return_mode, start_date, results)
    written_reports = write_default_report(report, args.output)
    chart_path = generate_default_chart(data_path, start_date, args.index_name, args.return_mode, market_profile)
    print(report)
    print("已写入报告文件:")
    for path in written_reports:
        print(f"- {path}")
    print(f"已写入图表文件:\n- {chart_path}")


if __name__ == "__main__":
    main()
