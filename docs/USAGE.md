# 使用教程

## 1. 这个项目是做什么的

这个项目提供了一个 Codex Skill、一个回测脚本和一个图表脚本，用于分析月度投资策略。

典型用途包括：

- 对比内置定投策略
- 只回测指定的几个策略
- 从特定历史时间开始回测
- 在纯价格指数和全收益指数之间切换
- 回测不同指数，例如标普500、纳斯达克100、沪深300、中证500、上证50
- 自动寻找本地数据，缺失时自动下载并补齐
- 不改 Python 代码就添加自定义策略
- 查看触发次数、最长触发区间、主要触发时段和市场背景
- 生成固定布局的总览图表

## 2. 查看内置清单

查看内置策略清单：

```powershell
python .\scripts\backtest.py --list-strategies
```

查看内置指数清单：

```powershell
python .\scripts\backtest.py --list-indices
```

## 3. 运行基础回测

```powershell
python .\scripts\backtest.py `
  --start-date 2010-01-01 `
  --index-name 标普500指数 `
  --return-mode price
```

默认附带动作：

- 自动覆盖输出最新 Markdown 报告：
  - `docs/backtest_report_latest.md`
- 自动覆盖输出最新图表：
  - `docs/backtest_summary_chart.svg`

## 4. 自动定位和补齐数据

如果不传 `--data-csv`，脚本会自动：

1. 根据 `--index-name` 匹配内置指数清单
2. 去默认本地文件路径查找数据
3. 检查是否缺失、不完整或过旧
4. 按指数清单配置自动下载并补齐
5. 将结果写入 `data/` 目录后继续回测

## 5. 生成图表

图表脚本：

- [scripts/render_summary_chart.py](D:\workspace-my\strategy-backtest-skill\scripts\render_summary_chart.py)

示例：

```powershell
python .\scripts\render_summary_chart.py `
  --data-csv C:\path\monthly_index_data.csv `
  --start-date 2008-01-01 `
  --index-name 标普500指数 `
  --return-mode price `
  --output D:\reports\backtest_summary_chart.svg
```

图表固定布局如下：

1. 第1张图为“策略-收益率对比折线图”
   - 横跨当前图表区域两列宽
   - `x轴` 为时间
   - `y轴` 为收益率
   - 每个数据点支持内嵌 JavaScript hover tooltip
   - tooltip 展示：
     - 策略名
     - 时间
     - 当期收益率
     - 总收益率
     - 年化IRR
     - 最大回撤
     - 总投入
   - 同一策略在折线、图例、柱状图中保持同一种颜色

2. 后面共6张柱状图
   - 总收益率：从高到低
   - 年化 IRR：从高到低
   - 最大回撤：从低到高
   - 总投入：从低到高
   - 期末资产：从高到低
   - 总盈利：从高到低

说明：

- 这套图表排序和布局已经固化到 skill 内
- 换电脑运行同一个 skill 时，默认仍按这套方式生成
- 若要获得 hover 交互，优先在浏览器中打开生成的 `svg`

## 6. 文本报告默认排序

策略对比表默认按下面顺序排序：

1. `总收益率降序`
2. `年化IRR降序`
3. `最大回撤升序`
4. `总投入升序`

## 7. 当前限制

- 还不支持直接解析自然语言策略
- 自动下载依赖外部公开数据源，稳定性受网络和数据源变化影响
- 还没有手续费、税费、汇率和单月投入上限模型
