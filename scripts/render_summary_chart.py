from __future__ import annotations

import argparse
import html
import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def load_backtest_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("strategy_backtest_runtime", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a summary SVG chart from strategy backtest results.")
    parser.add_argument("--data-csv", required=True, help="Monthly CSV used for the backtest")
    parser.add_argument("--start-date", required=True, help="Backtest start date in YYYY-MM-DD")
    parser.add_argument("--index-name", required=True, help="Index name shown in the chart")
    parser.add_argument("--return-mode", choices=["price", "total_return"], default="price")
    parser.add_argument("--market-profile", choices=["auto", "us", "cn", "generic"], default="auto")
    parser.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parents[1] / "references" / "strategy_catalog.json"),
        help="Strategy catalog JSON path",
    )
    parser.add_argument("--output", required=True, help="Target SVG file path")
    return parser.parse_args()


def render_svg(results, index_name: str, start_date: str, end_date: str) -> str:
    def order_items(items, key_name: str, descending: bool):
        return sorted(items, key=lambda item: item[key_name], reverse=descending)

    def esc(value: str) -> str:
        return html.escape(value, quote=True)

    title = "\u7b56\u7565\u56de\u6d4b\u7ed3\u679c\u603b\u89c8\uff08\u6309\u603b\u6536\u76ca\u7387\u6392\u5e8f\uff09"
    subtitle = (
        f"\u6570\u636e\u533a\u95f4\uff1a{start_date} \u81f3 {end_date} | "
        f"\u6307\u6570\uff1a{index_name} | "
        f"\u5171{len(results)}\u4e2a\u5185\u7f6e\u7b56\u7565"
    )
    panel_titles = {
        "return": "\u603b\u6536\u76ca\u7387 (%)",
        "irr": "\u5e74\u5316 IRR (%)",
        "drawdown": "\u6700\u5927\u56de\u64a4 (%)",
        "invested": "\u603b\u6295\u5165",
        "final_value": "\u671f\u672b\u8d44\u4ea7",
        "profit": "\u603b\u76c8\u5229",
    }

    width = 1800
    height = 2220
    margin = 70
    panel_gap = 50
    top_chart_h = 520
    panel_w = (width - margin * 2 - panel_gap) // 2
    panel_h = 430
    colors = {
        "return": "#1f77b4",
        "irr": "#2ca02c",
        "drawdown": "#d62728",
        "invested": "#9467bd",
        "final_value": "#0ea5e9",
        "profit": "#f59e0b",
        "text": "#1f2937",
        "grid": "#d1d5db",
        "axis": "#6b7280",
        "bg": "#ffffff",
        "card": "#f8fafc",
    }

    chart_rows = [
        {
            "key": "return",
            "title": panel_titles["return"],
            "value_key": "total_return_pct",
            "max_value": max(r["total_return_pct"] for r in results),
            "descending": True,
            "formatter": lambda v: f"{v:.2f}%",
        },
        {
            "key": "irr",
            "title": panel_titles["irr"],
            "value_key": "irr_pct",
            "max_value": max(r["irr_pct"] for r in results),
            "descending": True,
            "formatter": lambda v: f"{v:.2f}%",
        },
        {
            "key": "drawdown",
            "title": panel_titles["drawdown"],
            "value_key": "drawdown_pct",
            "max_value": max(r["drawdown_pct"] for r in results),
            "descending": False,
            "formatter": lambda v: f"{v:.2f}%",
        },
        {
            "key": "invested",
            "title": panel_titles["invested"],
            "value_key": "invested",
            "max_value": max(r["invested"] for r in results),
            "descending": False,
            "formatter": lambda v: f"{v / 10000:.1f}\u4e07",
        },
        {
            "key": "final_value",
            "title": panel_titles["final_value"],
            "value_key": "final_value",
            "max_value": max(r["final_value"] for r in results),
            "descending": True,
            "formatter": lambda v: f"{v / 10000:.1f}\u4e07",
        },
        {
            "key": "profit",
            "title": panel_titles["profit"],
            "value_key": "profit",
            "max_value": max(r["profit"] for r in results),
            "descending": True,
            "formatter": lambda v: f"{v / 10000:.1f}\u4e07",
        },
    ]

    svg: list[str] = []
    add = svg.append
    add('<?xml version="1.0" encoding="UTF-8"?>')
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    add("<style>")
    add(".data-point .hover-ring { opacity: 0; transition: opacity 0.15s ease; }")
    add(".data-point:hover .hover-ring { opacity: 0.95; }")
    add(".data-point .hover-core { transition: r 0.15s ease; }")
    add(".data-point:hover .hover-core { r: 5; }")
    add("#chart-tooltip { pointer-events: none; }")
    add("</style>")
    add("<script><![CDATA[")
    add("function showTooltip(evt){")
    add("  var svg = evt.target.ownerSVGElement;")
    add("  var tip = svg.getElementById('chart-tooltip');")
    add("  var bg = svg.getElementById('chart-tooltip-bg');")
    add("  var body = svg.getElementById('chart-tooltip-body');")
    add("  var raw = evt.currentTarget.getAttribute('data-tip') || '';")
    add("  var color = evt.currentTarget.getAttribute('data-color') || '#111827';")
    add("  var lines = raw.split('||');")
    add("  while (body.firstChild) { body.removeChild(body.firstChild); }")
    add("  for (var i = 0; i < lines.length; i++) {")
    add("    var t = document.createElementNS('http://www.w3.org/2000/svg','tspan');")
    add("    t.setAttribute('x','0');")
    add("    t.setAttribute('dy', i === 0 ? '0' : '18');")
    add("    if (i === 0) { t.setAttribute('font-weight','700'); t.setAttribute('fill', color); }")
    add("    t.textContent = lines[i];")
    add("    body.appendChild(t);")
    add("  }")
    add("  tip.setAttribute('visibility','visible');")
    add("  requestAnimationFrame(function(){")
    add("    var box = body.getBBox();")
    add("    var paddingX = 12, paddingY = 10;")
    add("    bg.setAttribute('width', box.width + paddingX * 2);")
    add("    bg.setAttribute('height', box.height + paddingY * 2);")
    add("    bg.setAttribute('x', -paddingX);")
    add("    bg.setAttribute('y', -box.height + box.y - paddingY);")
    add("    moveTooltip(evt);")
    add("  });")
    add("}")
    add("function moveTooltip(evt){")
    add("  var svg = evt.target.ownerSVGElement;")
    add("  var tip = svg.getElementById('chart-tooltip');")
    add("  if (tip.getAttribute('visibility') !== 'visible') return;")
    add("  var pt = svg.createSVGPoint();")
    add("  pt.x = evt.clientX; pt.y = evt.clientY;")
    add("  var cursor = pt.matrixTransform(svg.getScreenCTM().inverse());")
    add("  var x = cursor.x + 16;")
    add("  var y = cursor.y - 16;")
    add("  tip.setAttribute('transform', 'translate(' + x + ',' + y + ')');")
    add("}")
    add("function hideTooltip(evt){")
    add("  var svg = evt.target.ownerSVGElement;")
    add("  var tip = svg.getElementById('chart-tooltip');")
    add("  tip.setAttribute('visibility','hidden');")
    add("}")
    add("]]></script>")
    add(f'<rect width="100%" height="100%" fill="{colors["bg"]}"/>')
    add(
        f'<text x="{margin}" y="40" font-size="28" font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" '
        f'fill="{colors["text"]}" font-weight="700">{title}</text>'
    )
    add(
        f'<text x="{margin}" y="68" font-size="15" font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" '
        f'fill="{colors["axis"]}">{subtitle}</text>'
    )

    # Top line chart across two columns.
    line_x0 = margin
    line_y0 = 100
    line_w = width - margin * 2
    line_h = top_chart_h
    add(f'<rect x="{line_x0}" y="{line_y0}" width="{line_w}" height="{line_h}" rx="18" fill="{colors["card"]}" stroke="#e5e7eb"/>')
    add(
        f'<text x="{line_x0 + 20}" y="{line_y0 + 34}" font-size="22" font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" '
        f'fill="{colors["text"]}" font-weight="700">\u7b56\u7565-\u6536\u76ca\u7387\u5bf9\u6bd4\u6298\u7ebf\u56fe</text>'
    )
    line_left = line_x0 + 80
    line_top = line_y0 + 56
    line_chart_w = line_w - 120
    line_chart_h = line_h - 110
    max_line = max(max(point[1] for point in item["series"]) for item in results)
    min_line = min(min(point[1] for point in item["series"]) for item in results)
    min_line = min(min_line, 0.0)
    line_range = max_line - min_line if max_line != min_line else 1.0

    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
        "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#0ea5e9", "#f59e0b",
    ]

    # grid + y labels
    for step in range(6):
        value = min_line + line_range * step / 5
        y = line_top + line_chart_h - (value - min_line) / line_range * line_chart_h
        add(f'<line x1="{line_left}" y1="{y:.2f}" x2="{line_left + line_chart_w}" y2="{y:.2f}" stroke="{colors["grid"]}" stroke-width="1"/>')
        add(
            f'<text x="{line_left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="12" '
            f'font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="{colors["axis"]}">{value:.0f}%</text>'
        )

    max_points = max(len(item["series"]) for item in results)
    if max_points > 1:
        x_ticks = 6
        for step in range(x_ticks):
            idx = round((max_points - 1) * step / (x_ticks - 1))
            x = line_left + (idx / (max_points - 1)) * line_chart_w
            label = results[0]["series"][idx][0]
            add(f'<line x1="{x:.2f}" y1="{line_top}" x2="{x:.2f}" y2="{line_top + line_chart_h}" stroke="{colors["grid"]}" stroke-width="1" opacity="0.5"/>')
            add(
                f'<text x="{x:.2f}" y="{line_top + line_chart_h + 24}" text-anchor="middle" font-size="12" '
                f'font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="{colors["axis"]}">{label}</text>'
            )

    strategy_colors = {}
    for idx, item in enumerate(results):
        color = palette[idx % len(palette)]
        strategy_colors[item["id"]] = color
        points = []
        for point_idx, (label, value) in enumerate(item["series"]):
            x = line_left if max_points == 1 else line_left + (point_idx / (max_points - 1)) * line_chart_w
            y = line_top + line_chart_h - (value - min_line) / line_range * line_chart_h
            points.append(f"{x:.2f},{y:.2f}")
        add(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{" ".join(points)}"/>')
        for point_idx, (label, value) in enumerate(item["series"]):
            x = line_left if max_points == 1 else line_left + (point_idx / (max_points - 1)) * line_chart_w
            y = line_top + line_chart_h - (value - min_line) / line_range * line_chart_h
            tooltip = (
                f"{item['id']} {item['name']}\n"
                f"时间: {label}\n"
                f"当期收益率: {value:.2f}%\n"
                f"总收益率: {item['total_return_pct']:.2f}%\n"
                f"年化IRR: {item['irr_pct']:.2f}%\n"
                f"最大回撤: {item['drawdown_pct']:.2f}%\n"
                f"总投入: {item['invested'] / 10000:.1f}万"
            )
            tooltip_attr = esc(tooltip.replace("\n", "||"))
            add(
                f'<g class="data-point" data-tip="{tooltip_attr}" data-color="{color}" '
                f'onmouseenter="showTooltip(evt)" onmousemove="moveTooltip(evt)" onmouseleave="hideTooltip(evt)">'
            )
            add(f"<title>{tooltip}</title>")
            add(f'<circle class="hover-core" cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"/>')
            add(f'<circle class="hover-ring" cx="{x:.2f}" cy="{y:.2f}" r="8" fill="none" stroke="{color}" stroke-width="2"/>')
            add(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="10" fill="transparent"/>')
            add("</g>")

    # legend
    legend_x = line_left + 10
    legend_y = line_y0 + line_h - 28
    col_gap = 280
    for idx, item in enumerate(results):
        x = legend_x + (idx % 4) * col_gap
        y = legend_y + (idx // 4) * 18
        color = strategy_colors[item["id"]]
        add(f'<line x1="{x}" y1="{y}" x2="{x + 20}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        add(
            f'<text x="{x + 28}" y="{y + 4}" font-size="12" '
            f'font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="{colors["text"]}">{item["id"]} {item["name"]}</text>'
        )

    panel_positions = []
    base_y = line_y0 + line_h + 40
    for row in range(3):
        for col in range(2):
            panel_positions.append(
                (
                    margin + col * (panel_w + panel_gap),
                    base_y + row * (panel_h + panel_gap),
                )
            )

    for panel_def, (x0, y0) in zip(chart_rows, panel_positions):
        key = panel_def["key"]
        items = order_items(results, panel_def["value_key"], panel_def["descending"])
        max_val = panel_def["max_value"]
        add(f'<rect x="{x0}" y="{y0}" width="{panel_w}" height="{panel_h}" rx="18" fill="{colors["card"]}" stroke="#e5e7eb"/>')
        add(
            f'<text x="{x0 + 20}" y="{y0 + 34}" font-size="22" font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" '
            f'fill="{colors["text"]}" font-weight="700">{panel_def["title"]}</text>'
        )
        chart_left = x0 + 180
        chart_top = y0 + 58
        chart_w = panel_w - 220
        chart_h = panel_h - 90
        row_h = chart_h / len(items)
        for i, row in enumerate(items):
            y = chart_top + i * row_h + row_h * 0.68
            label = f"{row['id']} {row['name']}"
            value = row[panel_def["value_key"]]
            bar_w = 0 if max_val == 0 else chart_w * value / max_val
            color = strategy_colors[row["id"]]
            add(f'<line x1="{chart_left}" y1="{y + 8}" x2="{chart_left + chart_w}" y2="{y + 8}" stroke="{colors["grid"]}" stroke-width="1"/>')
            add(
                f'<text x="{x0 + 16}" y="{y + 7}" font-size="13" '
                f'font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="{colors["text"]}">{label}</text>'
            )
            add(f'<rect x="{chart_left}" y="{y - 6}" width="{bar_w:.2f}" height="14" rx="7" fill="{color}" opacity="0.9"/>')
            value_text = panel_def["formatter"](value)
            add(
                f'<text x="{chart_left + bar_w + 8:.2f}" y="{y + 6}" font-size="12" '
                f'font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="{colors["text"]}">{value_text}</text>'
            )

    add('<g id="chart-tooltip" visibility="hidden">')
    add('<rect id="chart-tooltip-bg" rx="10" fill="#ffffff" stroke="#cbd5e1" opacity="0.96"/>')
    add('<text id="chart-tooltip-body" x="0" y="0" font-size="12" font-family="Segoe UI, Microsoft YaHei, Arial, sans-serif" fill="#111827"></text>')
    add("</g>")
    add("</svg>")
    return "\n".join(svg)


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve().parents[0] / "backtest.py"
    module = load_backtest_module(script_path)
    strategy_catalog = module.load_catalog(Path(args.catalog))
    rows = module.load_rows(Path(args.data_csv))
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    start_index = next(index for index, row in enumerate(rows) if row.when >= start_date)
    market_profile = module.infer_market_profile(args.index_name, args.market_profile)
    raw_results = [
        module.backtest_strategy(strategy, rows, start_index, args.return_mode, 3, market_profile)
        for strategy in strategy_catalog
    ]
    raw_results.sort(
        key=lambda item: (
            -item.total_return,
            -(item.annual_irr if item.annual_irr is not None else float("-inf")),
            item.max_drawdown,
            item.total_invested,
        )
    )

    results = []
    for result in raw_results:
        shares = 0.0
        invested = 0.0
        series = []
        for idx in range(start_index, len(rows)):
            ctx = module.build_context(rows, idx, args.return_mode)
            ctx["name"] = result.name
            strategy_def = next(item for item in strategy_catalog if item["id"] == result.strategy_id)
            amount, _ = module.evaluate_strategy(strategy_def, ctx)
            current_value = ctx["series_value"]
            shares += amount / current_value
            invested += amount
            return_pct = (shares * current_value / invested - 1.0) * 100 if invested else 0.0
            series.append((rows[idx].when.isoformat(), return_pct))
        results.append(
            {
                "id": result.strategy_id,
                "name": result.name,
                "invested": result.total_invested,
                "final_value": result.final_value,
                "profit": result.profit,
                "total_return_pct": result.total_return * 100,
                "irr_pct": (result.annual_irr or 0) * 100,
                "drawdown_pct": result.max_drawdown * 100,
                "series": series,
            }
        )

    output = render_svg(results, args.index_name, args.start_date, rows[-1].when.isoformat())
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
