---
name: strategy-backtest
description: Backtest monthly investment and DCA strategies with a maintained strategy catalog, built-in index catalog, configurable start date, price-vs-total-return modes, selected-strategy comparisons, trigger statistics, market-context analysis, automatic local-data resolution plus download backfill, and fixed-layout visual chart output. Use when Codex needs to compare strategy rules, update a strategy list, or evaluate monthly investment rules against index history.
---

# Strategy Backtest

Use this skill to maintain a reusable strategy catalog and run monthly strategy backtests with detailed trigger analysis and fixed-layout chart output.

## Workflow

1. Confirm the input data and backtest mode.
   Use `references/data-schema.md` for the required CSV columns.
   Require `price_index` for pure index backtests and `total_return_index` for total-return backtests.
   Require `pe` when the selected strategies use PE rules.
   If the user does not provide `--data-csv`, prefer resolving data from the built-in index catalog.

2. Inspect or update the catalogs.
   Use `python scripts/backtest.py --list-strategies` to print the built-in strategy table.
   Use `python scripts/backtest.py --list-indices` to print the built-in index table.
   Edit `references/strategy_catalog.json` to add or update built-in strategies.
   Edit `references/index_catalog.json` to add or update built-in index mappings and download sources.
   Keep every strategy entry populated with `id`, `name`, `rule_description`, and `rule_example`.

3. Run selected strategy comparisons.
   Use `python scripts/backtest.py --start-date YYYY-MM-DD --index-name 标普500指数 --return-mode price --strategy-ids ST001,ST003`.
   Add `--data-csv <file>` only when the user wants to force a specific local file.
   Omit `--strategy-ids` to run all built-in strategies.
   Add `--custom-strategy-file <file>` to load extra JSON strategies that are not in the built-in catalog.
   If the resolved local data is missing, stale, or incomplete, let the script auto-download and backfill before evaluating the strategies.

4. Present the textual report in two layers.
   Start with the comparison table.
   Keep the comparison table sorted by total return descending by default.
   Then summarize each strategy's trigger counts, longest trigger streak, major trigger periods, and market context.
   End with an objective assessment that compares return, IRR, drawdown, and capital intensity against the peer set.
   After every backtest run, overwrite the default Markdown report at `docs/backtest_report_latest.md`.

5. Generate charts when the user asks for a visual summary.
   The backtest script should automatically regenerate the default summary SVG at `docs/backtest_summary_chart.svg` after each backtest run.
   Use `python scripts/render_summary_chart.py` directly only when the user explicitly wants chart-only regeneration.
   Keep the chart layout fixed:
   - The first chart is a two-column-wide line chart for strategy vs. return over time.
   - The line chart should use embedded JavaScript hover tooltips on each data point.
   - Each tooltip should show strategy name, date, point-in-time return, total return, annual IRR, max drawdown, and total invested.
   - Each strategy should keep the same color across the line chart, legend, and all six bar charts.
   - The next six charts are bar charts for total return, annual IRR, max drawdown, total invested, final value, and total profit.
   - Sort total return and annual IRR charts descending.
   - Sort max drawdown and total invested charts ascending.
   - Sort final value and total profit charts descending.

## Commands

List the catalog:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py --list-strategies
```

List the built-in indices:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py --list-indices
```

Backtest three built-in strategies from January 1, 2010 using total return:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py `
  --start-date 2010-01-01 `
  --index-name 标普500指数 `
  --return-mode total_return `
  --strategy-ids ST001,ST005,ST011
```

Run built-in strategies plus custom JSON strategies and save the Markdown report:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py `
  --start-date 2008-01-01 `
  --index-name 沪深300指数 `
  --market-profile cn `
  --return-mode price `
  --strategy-ids ST003,ST006 `
  --custom-strategy-file C:\path\custom_strategies.json `
  --output C:\path\backtest_report.md
```

Generate the summary SVG chart:

```powershell
python .codex\skills\strategy-backtest\scripts\render_summary_chart.py `
  --data-csv C:\path\monthly_index_data.csv `
  --start-date 2008-01-01 `
  --index-name 标普500指数 `
  --return-mode price `
  --output C:\path\backtest_summary_chart.svg
```

## Custom Strategies

Structured custom strategies are supported through JSON.
Use `references/custom_strategy_template.json` as the starting point.

Supported custom strategy kinds:

- `fixed_amount`
- `pe_percentile`
- `drawdown_total`
- `drawdown_cumulative`
- `ma12_deviation`
- `composite_sum`

Free-form natural-language strategy parsing is not implemented in the script.
If the user supplies a plain-language strategy, translate it into the JSON schema before running the script.

## Output Expectations

The backtest script prints:

- A strategy comparison table with strategy id, totals, return metrics, drawdown metrics, and rule samples
- A market-state summary for the tested dataset
- Per-strategy trigger counts and longest streaks
- Major trigger windows with dates, trigger intensity, and market context labels
- An objective peer-relative assessment
- Default output paths for the latest Markdown report and latest summary chart

The chart script outputs:

- One summary SVG with a top line chart and six bar charts
- A fixed chart order and fixed ranking rules so the display remains consistent across computers
- Embedded JavaScript hover tooltips for line-chart points when the SVG is opened in a browser or another SVG-script-capable viewer

## Resources

- `scripts/backtest.py`: Run strategy catalog listing and backtests
- `scripts/render_summary_chart.py`: Render the fixed-layout summary SVG chart
- `references/strategy_catalog.json`: Built-in strategy list and rule samples
- `references/index_catalog.json`: Built-in index list, aliases, local files, and download sources
- `references/data-schema.md`: Required monthly CSV schema
- `references/custom_strategy_template.json`: Template for ad-hoc strategies
