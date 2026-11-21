# CLI Runtime（数据层统一约定）

一行原则：**PATH 优先，skill 树兜底；禁止写死个人家目录。**

取数口径以 `invest/SKILL.md` 的「场景 → invest-cli 取数映射」表为真源；可用性以 `invest-cli datasources` 的运行时探测为准。本文件只管运行时解析与外部分工。

## 解析顺序

```bash
# 1) 用户覆盖
# 2) PATH 上的同名命令（真实运行态，优先 invest-cli）
# 3) 相邻 skill 树 bin/（打包快照）
# 4) 常见 skills 根下的探测
command -v invest-cli
# invest-cli 兜底：
#   $INVEST_CLI | $INVEST_CLI_ROOT/scripts/invest_cli.py
#   | sibling invest-cli/scripts/invest_cli.py
#   | $HOME/.agents|/.claude|/.grok|/.codex/skills/invest-cli/...
```

## 数据层外部依赖（仅两类）

invest-cli 是唯一数据入口。它对外部技能的依赖只允许两类的其中一种：

| 外部依赖 | 用途 | 例 |
|---------|------|-----|
| **登录态源** | 需用户凭据/登录的官方源（缺登录态时按优先级降级，整单回退） | hithink（同花顺 key/凭据）、wind（Wind key）、yingmi（盈米登录）、ttskill（天天基金登录）、eastmoney（东财 key） |
| **搜索技能** | 无结构化 API 的资讯/舆情/宏观补充检索 | argo（`info` / `intent macro`） |

不外接任何「分析技能」当取数依赖。ttfund / fundfof / fundscreen 已退役（2026-09-03，能力并入官方 ttskill 业务包与 invest-cli `intent`），不作为活性依赖。

## 历史快照已删除（2026-10-17）

这里曾有两张表：一份「数据源分工」、一份「某机可用性快照」。两张都标了「已作废」
却仍占 40 行——而投资 agent 读文件是整段读的，作废表一样会被当成事实。
它们的共同问题是**同一事实的第三份副本**（真源分别是 `invest/SKILL.md` 的场景表和
`invest-cli datasources` 的运行时探测），且已经漂移（写「债券 → mxds」，实际走 Wind）。
需要考古看 git 历史；日常只认上面两个真源。

## 模糊词默认

| 用户说 | 默认 |
|--------|------|
| 「诊断一下 005827」（无买/不买） | `invest-cli intent deep fund`（盈米诊断雷达） |
| 「这只基金怎么样 / 值不值得」 | invest-fund（判断） |
| 「查某标的行情/数据」 | `invest-cli stock/fund/us`（按标的类型） |
| 「市场环境/宏观」 | `intent macro`（argo） |

## 未知环境兼容

1. 先 `command -v invest-cli`；失败再读 skill 树 `bin/`。
2. CLI 缺失：降级 web_search / 用户粘贴数据，**不得假装已取数**。
3. 名称→代码：以各 CLI 自己的 resolve 为准；经理人名**不得**绑死单只产品代码。
4. 口径不一致不合并；输出必须标注数据来源。