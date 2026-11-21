---
name: mx-data
description: |
  投资分析数据层——invest-cli 的统一封装。
  不直接调用 API，不管理授权，直接复用 invest-cli 的数据源体系。
  由 invest 系列方法论层调用，不直接面向用户。
triggers:
  - mx-data
---

# mx-data：invest-cli 数据封装层

## 定位

**in-process 封装层**。不直接调用 API，不管理授权，直接复用 invest-cli 的数据源体系。

invest-cli 已经有的数据源、授权、路由、降级逻辑，全部复用。mx-data 只加一层"场景→取数"的映射。

## 统一接口

所有查询通过 `scripts/get_data.py` 入口（in-process 调 `route.fetch`，与 `invest-cli stock/fund/us` 同源同缓存；import 失败才降级 subprocess）：

```bash
# 自然语言查询（自动路由到 invest-cli 命令）
python3 scripts/get_data.py --query "茅台的ROE和毛利率"

# 指定标的和指标
python3 scripts/get_data.py --type stock --code 600519 --metrics ["ROE","PE","revenue"]

# 美股：显式 --type us，或 --type stock + 字母代码（自动识别，不会走 A 股链）
python3 scripts/get_data.py --type us --code AAPL
```

- **`--metrics` 只回传、不过滤**：指标裁剪在分析层做，别指望它减小载荷。
- **解释器升级自愈**：用任意解释器（含系统 `python3`）启动时，只要
  `invest-cli/.venv` 存在且当前不在其中，脚本会 exec 进 venv 再跑一次
  （`MX_DATA_NO_REEXEC=1` 可关）。2026-10-25 起不限美股场景——系统 3.9 已
  EOL 且 LibreSSL 会打告警假故障，本机运行时统一走 skill 自带 venv（版本
  由 `invest-cli doctor` 自报，不写死进文档）。venv 不存在时系统解释器照常
  可用（公开仓 3.9+ 承诺不变）。输出里的 `runtime` 字段就是实际执行解释器，
  可据此确认自愈是否生效。

## 场景→invest-cli 命令映射

场景状态机的唯一真值是 `scripts/query_router.py` 的 `SCENARIO_COMMANDS`（含展示名、argv、route_kind），本表与其一一对应（改映射只动代码，本表由 test_doc_source_truth 钉住）。数据源声明与优先级见 `../invest-cli/data-sources.yaml`，运行时链以 `invest-cli datasources` 自报为准；本表不写数据源链。

| 场景 | 命令 | 说明 |
|---|---|---|
| A股基本面 | `invest-cli stock <代码>` | A 股快照与基本面 |
| 港股 | `invest-cli stock <代码>` | 港股快照，市场自动识别 |
| 美股 | `invest-cli us <代码>` | 美股快照 |
| 基金 | `invest-cli fund <代码>` | 公募基金快照 |
| 债券 | `invest-cli intent deep bond <代码>` | 可转债/利率债 |
| 行业板块 | `invest-cli stock <代码>` + `invest-cli cn report <代码>` | 行情 + 研报 |
| 资讯舆情 | `invest-cli info <查询词>` | 检索资讯 |
| 宏观 | `invest-cli intent macro` | 宏观时序 |
| 企业深度 | `invest-cli stock <代码>` + `invest-cli cn holders <代码>`、`invest-cli cn notice <代码>` | 公司治理与公告 |

## 与 invest-cli 的关系

- mx-data **不重复造轮子**，直接调用 invest-cli 命令
- invest-cli 管理授权、路由、降级，mx-data 不关心
- mx-data 只负责把"方法论层的需求"翻译成"invest-cli 命令"

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/query_router.py` | 场景→invest-cli 命令映射 |
| `scripts/get_data.py` | 统一入口，调用 invest-cli |

## 与 invest 系列的关系

- invest-* 调用 mx-data 获取数据
- mx-data 调用 invest-cli 命令
- invest-cli 管理数据源和授权
