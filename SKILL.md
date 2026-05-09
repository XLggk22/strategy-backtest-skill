---
name: strategy-backtest
description: Backtest monthly investment and DCA strategies with a maintained strategy catalog, configurable start date, price-vs-total-return modes, selected-strategy comparisons, trigger statistics, and market-context analysis. Use when Codex needs to compare strategy rules, update a strategy list, or evaluate monthly investment rules against index history.
---

# Strategy Backtest

Use this skill to maintain a reusable strategy catalog and run monthly strategy backtests with detailed trigger analysis.

## Workflow

1. Confirm the input data and backtest mode.
   Use `references/data-schema.md` for the required CSV columns.
   Require `price_index` for pure index backtests and `total_return_index` for total-return backtests.
   Require `pe` when the selected strategies use PE rules.

2. Inspect or update the strategy catalog.
   Use `python scripts/backtest.py --list-strategies` to print the built-in strategy table.
   Edit `references/strategy_catalog.json` to add or update built-in strategies.
   Keep every strategy entry populated with `id`, `name`, `rule_description`, and `rule_example`.

3. Run selected strategy comparisons.
   Use `python scripts/backtest.py --data-csv <file> --start-date YYYY-MM-DD --return-mode price --strategy-ids ST001,ST003`.
   Omit `--strategy-ids` to run all built-in strategies.
   Add `--custom-strategy-file <file>` to load extra JSON strategies that are not in the built-in catalog.

4. Present the report in two layers.
   Start with the comparison table.
   Then summarize each strategy's trigger counts, longest trigger streak, major trigger periods, and market context.
   End with an objective assessment that compares return, IRR, drawdown, and capital intensity against the peer set.

## Commands

List the catalog:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py --list-strategies
```

Backtest three built-in strategies from January 1, 2010 using total return:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py `
  --data-csv C:\path\monthly_index_data.csv `
  --start-date 2010-01-01 `
  --return-mode total_return `
  --strategy-ids ST001,ST005,ST011
```

Run built-in strategies plus custom JSON strategies and save the Markdown report:

```powershell
python .codex\skills\strategy-backtest\scripts\backtest.py `
  --data-csv C:\path\monthly_index_data.csv `
  --start-date 2008-01-01 `
  --return-mode price `
  --strategy-ids ST003,ST006 `
  --custom-strategy-file C:\path\custom_strategies.json `
  --output C:\path\backtest_report.md
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

The script prints:

- A strategy comparison table with strategy id, totals, return metrics, drawdown metrics, and rule samples
- A market-state summary for the tested dataset
- Per-strategy trigger counts and longest streaks
- Major trigger windows with dates, trigger intensity, and market context labels
- An objective peer-relative assessment

## Resources

- `scripts/backtest.py`: Run strategy catalog listing and backtests
- `references/strategy_catalog.json`: Built-in strategy list and rule samples
- `references/data-schema.md`: Required monthly CSV schema
- `references/custom_strategy_template.json`: Template for ad-hoc strategies
