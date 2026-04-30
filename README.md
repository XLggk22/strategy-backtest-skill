# 策略回测 Skill

这是一个面向 Codex 的策略回测 Skill，用来维护策略清单，并基于月度指数数据回测定投和加仓策略。

它适合下面这类场景：

- 对比固定定投、PE 估值、回撤加仓、均线偏离等策略
- 从指定历史起点开始回测
- 在纯价格指数和全收益指数之间切换
- 回测不同市场指数，例如标普500、纳斯达克100、沪深300、中证500、上证50
- 自动寻找本地数据，缺失时自动下载并补齐
- 只挑选部分内置策略做横向比较
- 加载列表外的自定义 JSON 策略
- 输出触发次数、主要触发区间、市场背景和客观评价
- 输出固定布局的图表总览，跨电脑运行保持一致

## 项目结构

```text
strategy-backtest-skill/
|- SKILL.md
|- README.md
|- agents/
|  |- openai.yaml
|- docs/
|  |- USAGE.md
|- references/
|  |- strategy_catalog.json
|  |- index_catalog.json
|  |- data-schema.md
|  |- custom_strategy_template.json
|  |- examples/
|     |- csi300_monthly_template.csv
|- data/
|  |- auto-downloaded monthly csv files
|- scripts/
|  |- backtest.py
|  |- render_summary_chart.py
```

## 核心能力

- 内置策略清单，带策略编号、规则描述、规则描述样例
- 内置指数清单，带别名、市场画像、默认本地文件和自动下载配置
- 支持通过 JSON 扩展策略列表
- 支持输入回测起始时间
- 支持两种回测模式
  - `price`：纯指数收益
  - `total_return`：全收益指数
- 支持通过 `--index-name` 和 `--market-profile` 指定回测指数及市场背景
- 支持自动定位本地数据
- 本地没有数据或数据不完整时，按指数清单自动下载并补齐
- 支持指定若干策略做对比
- 支持输出详细结果
  - 总投入
  - 期末资产
  - 总盈利
  - 总收益率
  - 年化 IRR
  - 最大回撤
  - 夏普率
  - 触发次数
  - 最长连续触发
  - 主要触发区间
  - 客观评价
- 结果对比表默认按 `总收益率降序` 排序，跨电脑运行保持一致
- 支持固定布局图表输出，跨电脑运行保持一致

## 快速开始

查看内置策略清单：

```powershell
python .\scripts\backtest.py --list-strategies
```

查看内置指数清单：

```powershell
python .\scripts\backtest.py --list-indices
```

回测标普500指数：

```powershell
python .\scripts\backtest.py `
  --start-date 2010-01-01 `
  --index-name 标普500指数 `
  --return-mode price `
  --strategy-ids ST001,ST006,ST011
```

回测标普500全收益指数：

```powershell
python .\scripts\backtest.py `
  --start-date 2010-01-01 `
  --index-name 标普500全收益指数 `
  --market-profile us `
  --return-mode total_return `
  --strategy-ids ST001,ST006,ST011
```

回测沪深300指数：

```powershell
python .\scripts\backtest.py `
  --start-date 2012-01-01 `
  --index-name 沪深300指数 `
  --market-profile cn `
  --return-mode price `
  --strategy-ids ST001,ST006,ST011
```

导出 Markdown 报告：

```powershell
python .\scripts\backtest.py `
  --start-date 2008-01-01 `
  --index-name 标普500指数 `
  --return-mode price `
  --strategy-ids ST003,ST006 `
  --output C:\path\backtest_report.md
```

默认行为：

- 每次执行回测后，都会自动覆盖生成最新 Markdown 报告：
  - `docs/backtest_report_latest.md`
- 每次执行回测后，都会自动覆盖生成最新图表：
  - `docs/backtest_summary_chart.svg`
- 即使你额外传了 `--output`，默认报告和默认图表也仍然会一起更新

生成图表总览：

```powershell
python .\scripts\render_summary_chart.py `
  --data-csv C:\path\monthly_index_data.csv `
  --start-date 2008-01-01 `
  --index-name 标普500指数 `
  --return-mode price `
  --output C:\path\backtest_summary_chart.svg
```

图表固定布局：

- 第1张：策略-收益率对比折线图
  - 横跨两列宽度
  - `x轴` 为时间
  - `y轴` 为收益率
  - 每个数据点支持内嵌 JavaScript hover tooltip
  - hover 时显示：策略名、时间、当期收益率、总收益率、年化IRR、最大回撤、总投入
  - 同一策略在折线、图例、柱状图中保持同一种颜色
- 后面6张柱状图：
  - 总收益率：从高到低
  - 年化 IRR：从高到低
  - 最大回撤：从低到高
  - 总投入：从低到高
  - 期末资产：从高到低
  - 总盈利：从高到低

提示：

- 如果要看到 hover 效果，建议在浏览器中打开 `svg`
- 某些系统图片查看器只会把 `svg` 当静态图显示，不支持脚本交互

## 自动数据机制

当你不传 `--data-csv` 时，脚本会：

1. 根据 `--index-name` 去 [references/index_catalog.json](D:\workspace-my\strategy-backtest-skill\references\index_catalog.json) 里匹配指数
2. 自动寻找对应本地数据文件
3. 如果本地没有数据，或数据不完整、过旧，就自动尝试下载
4. 下载完成后写入 `data/` 目录
5. 再使用补齐后的数据回测

## 文档

详细使用教程：

- [docs/USAGE.md](D:\workspace-my\strategy-backtest-skill\docs\USAGE.md)

## 说明

- 脚本暂不直接支持“自然语言策略描述自动解析”
- 对于纯文本策略，建议先翻译成 JSON 再回测
- 自动下载依赖外部公开数据源，稳定性受网络和数据源变化影响
- 回测结果高度依赖输入月度数据的完整性和质量
