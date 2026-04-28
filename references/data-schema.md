# Monthly Data Schema

Use a monthly CSV with one row per observation date.
Sort rows ascending by date.

## Required columns

| Column | Required | Meaning |
|---|---|---|
| `date` | yes | Observation date in `YYYY-MM-DD` |
| `price_index` | yes | Pure price index level used for `--return-mode price` |
| `total_return_index` | no, but required for total-return mode | Total-return index level used for `--return-mode total_return` |
| `pe` | no, but required for PE strategies | Raw PE value for the same date |

## Notes

- Include rows before the requested backtest `start-date` when possible.
  The script uses prior rows to compute expanding PE percentiles and MA12 windows.
- Use the same frequency across all columns.
- Use numeric values only; do not include commas in the CSV numeric fields.
- The script treats the selected return-mode series as the series used for monthly returns, drawdown, and MA12 deviation.

## Minimal example

```csv
date,price_index,total_return_index,pe
2009-11-01,1036.19,1834.52,20.11
2009-12-01,1115.10,1981.33,21.07
2010-01-01,1073.87,1908.11,20.19
2010-02-01,1104.49,1964.26,20.45
```
