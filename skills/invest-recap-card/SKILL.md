---
name: invest-recap-card
description: "A股大盘收盘复盘卡片与复盘图一键生成器。自动调用 invest-cli 抓取当天或指定日期的指数行情、两市量能、阻力支撑与涨跌分布，按经典复盘文风（口语化问候、宏观次要原因、主力洗盘意图、操作防踩坑、避税脱敏）组装文案，并通过 Kami 设计系统（羊皮纸底色、仓耳今楷/衬线字体、墨水蓝强调色）一键编译输出高清单页 A4 图片（PNG/PDF）并自动打开预览。触发词：复盘卡片、行情卡片、出复盘图、大盘复盘长图、制作复盘卡片、今天的行情图、昨天的行情图。"
---

# invest-recap-card · 大盘复盘卡片生成器

每日 A 股收盘复盘图一键自动化流水线。集行情拉取、文案组装、Kami 典雅排版与高清单页渲染于一体。

## 核心特性

1. **自动对齐交易日**：支持 `--date today`（今日行情）、`--date yesterday`（自动识别周一对应的上一交易日周五），以及 `YYYY-MM-DD` 指定日期。
2. **多源数据整合**：直连 `invest-cli`，秒级提取三大指数（上证、深成、创业板）、两市成交额、日内高低点、关口压力位。
3. **经典文风拟合与脱敏**：
   - 吸睛策略短标题（《周X策略：……》）
   - 大白话行情拆解（宏观压制次要原因 + 主力洗盘边拉边洗主要原因）
   - 明确操作应对（杜绝追涨、逢低潜伏、防踏空防挨打）
   - **完全脱敏**：自动隐去个人姓名、执业证书及商业机构，保留合规免责声明。
4. **Kami 顶级纸张美学**：
   - 温暖羊皮纸背景（`#f5f4ed`）+ 墨水蓝核心点缀（`#1B365D`）
   - 仓耳今楷/高雅宋体衬线 Typography 排版
   - **100% 页面收敛保证**：专有比例设计，永不溢出第二页
   - 200 DPI 超清 PNG 导出，支持 macOS 自动弹窗预览

## 常用命令

在终端或通过 Agent 执行：

```bash
# 生成今天收盘复盘图并自动在屏幕上打开
python3 ~/.agents/taxue-invest/skills/invest-recap-card/scripts/run.py --date today

# 生成昨天（上一交易日）收盘复盘图
python3 ~/.agents/taxue-invest/skills/invest-recap-card/scripts/run.py --date yesterday

# 指定日期并自定义标题
python3 ~/.agents/taxue-invest/skills/invest-recap-card/scripts/run.py \
  --date 2026-11-09 \
  --title "周一策略：冲高回落，明天别乱接飞刀！" \
  --out-dir ./output
```

## 目录结构

- `scripts/fetch_market.py`：行情取数模块（调用 invest-cli）
- `scripts/render_card.py`：WeasyPrint + PyMuPDF 栅格化引擎
- `scripts/run.py`：一键自动化编排入口
- `templates/card_template.html`：Kami 单页标准模版
