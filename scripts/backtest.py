from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "strategy_catalog.json"
BASELINE_AMOUNT = 1000.0


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
    parser.add_argument("--data-csv", help="Monthly CSV matching references/data-schema.md")
    parser.add_argument("--start-date", help="Backtest start date in YYYY-MM-DD")
    parser.add_argument("--return-mode", choices=["price", "total_return"], default="price")
    parser.add_argument("--strategy-ids", help="Comma-separated strategy IDs to compare")
    parser.add_argument("--custom-strategy-file", help="Optional JSON file with extra strategies")
    parser.add_argument("--catalog", default=str(CATALOG_PATH), help="Override built-in strategy catalog path")
    parser.add_argument("--list-strategies", action="store_true", help="Print the strategy catalog table")
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


def load_rows(csv_path: Path) -> list[Row]:
    rows: list[Row] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            when = datetime.strptime(raw["date"], "%Y-%m-%d").date()
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


def evaluate_strategy(strategy: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, list[str]]:
    kind = strategy["kind"]

    if kind == "fixed_amount":
        return float(strategy["amount"]), []

    if kind == "pe_percentile":
        pe_value = ctx["pe_percentile"]
        if pe_value is None:
            raise ValueError(f"Strategy '{ctx['name']}' requires PE data.")
        if pe_value > float(strategy["high_threshold"]):
            return float(strategy["high_amount"]), [f"pe:{format_threshold(strategy['high_threshold'])}"]
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
            pct = abs(strategy["lower_threshold"]) * 100
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


def major_market_context(start: date, end: date) -> str:
    windows = [
        (date(2008, 1, 1), date(2010, 6, 1), "全球金融危机与后续修复"),
        (date(2011, 7, 1), date(2012, 1, 1), "欧债危机与美债降级波动"),
        (date(2020, 2, 1), date(2020, 6, 1), "疫情冲击与快速反弹"),
        (date(2022, 1, 1), date(2022, 12, 1), "通胀与加息驱动的熊市"),
    ]
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


def require_fields(strategies: list[dict[str, Any]], rows: list[Row], return_mode: str) -> None:
    if return_mode == "total_return" and any(row.total_return_index is None for row in rows):
        raise ValueError("return-mode=total_return requires total_return_index for every row.")

    def needs_pe(strategy: dict[str, Any]) -> bool:
        kind = strategy["kind"]
        if kind == "pe_percentile":
            return True
        if kind == "composite_sum":
            return any(needs_pe(component) for component in strategy.get("components", []))
        return False

    if any(needs_pe(strategy) for strategy in strategies) and any(row.pe is None for row in rows):
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
                current_period["context"] = major_market_context(current_period["start"], current_period["end"])
                periods.append(current_period)
                current_period = None

        if idx > start_index:
            previous = choose_series_value(rows[idx - 1], return_mode)
            monthly_returns.append(current_value / previous - 1.0)

    if current_period is not None:
        current_period["context"] = major_market_context(current_period["start"], current_period["end"])
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


def market_state_summary(rows: list[Row], return_mode: str) -> dict[str, int]:
    counts = {
        "<=5%": 0,
        "5%-10%": 0,
        "10%-20%": 0,
        "20%-30%": 0,
        "30%-40%": 0,
        ">40%": 0,
    }
    for idx in range(len(rows)):
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


def list_table(catalog: list[dict[str, Any]]) -> str:
    lines = [
        "| 策略编号 | 策略 | 规则描述 | 规则描述样例 |",
        "|---|---|---|---|",
    ]
    for item in catalog:
        lines.append(
            f"| {item['id']} | {item['name']} | {item['rule_description']} | {item['rule_example']} |"
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
            -item.total_invested,
            -item.total_return,
            -(item.annual_irr if item.annual_irr is not None else float("-inf")),
            item.max_drawdown,
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
    rows: list[Row],
    return_mode: str,
    start_date: date,
    results: list[StrategyResult],
) -> str:
    market_summary = market_state_summary(rows, return_mode)
    lines = [
        "# Strategy Backtest Report",
        "",
        f"- 回测起点: {start_date}",
        f"- 回测终点: {rows[-1].when}",
        f"- 回测模式: {'纯指数收益' if return_mode == 'price' else '全收益指数'}",
        f"- 回测月份数: {len(rows)}",
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


def main() -> None:
    args = parse_args()
    catalog = load_catalog(Path(args.catalog), Path(args.custom_strategy_file) if args.custom_strategy_file else None)

    if args.list_strategies:
        output = list_table(catalog)
        if args.output:
            Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(output)
        return

    if not args.data_csv or not args.start_date:
        raise SystemExit("--data-csv and --start-date are required unless --list-strategies is used.")

    rows = load_rows(Path(args.data_csv))
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    filtered_rows = [row for row in rows if row.when >= start_date]
    if not filtered_rows:
        raise ValueError("No rows remain after applying the start date.")
    start_index = next(index for index, row in enumerate(rows) if row.when >= start_date)

    selected_ids = None
    if args.strategy_ids:
        selected_ids = {item.strip() for item in args.strategy_ids.split(",") if item.strip()}
    strategies = [item for item in catalog if selected_ids is None or item["id"] in selected_ids]
    if not strategies:
        raise ValueError("No strategies were selected.")

    require_fields(strategies, rows, args.return_mode)

    results = []
    for strategy in strategies:
        result = backtest_strategy(strategy, rows, start_index, args.return_mode, args.top_periods)
        results.append(result)

    report = render_report(filtered_rows, args.return_mode, start_date, results)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
