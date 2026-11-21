# invest-cli 文档索引

> 取数口径只认两处：`data-sources.yaml`（声明真值：priority / route_kinds），
> 与 `invest-cli datasources` 的运行时自报。SKILL.md 的门闩表只写「场景 → 命令」，
> 不再承载源名。**历史报告是过程记录，结论可能被后续轮次推翻**——引用前先看
> 日期与「复核/遗留」段。

## 现行（按需读）

| 文档 | 用途 |
|---|---|
| [data-sources.md](data-sources.md) | 数据源能力矩阵、字段口径、降级链的详细说明 |
| [capability-gap.md](capability-gap.md) | 与盈米 69 工具 / ttskill 37 包的差距清单 |
| [ablation.md](ablation.md) | 2026-09-03 数据源补齐的消融实验记录 |

## 历史轮次（过程记录，勿当现状）

过程报告已统一归档到 `taxue-invest/docs-local/archive/`（不进公开仓），
清单见该目录的 README。本文件不再逐篇链接——归档位置与内容会变，
链接留在原处只会积累失效链接。

## 维护约定

- 命令面唯一真源：`scripts/command_registry.py`；插件 `dsh/registry.generated.js` 与 `client.js` 的注册表块由 `scripts/sync_registry.py` 生成，`check.py` 校验是否过期。加命令先改注册表，再补 parser/dispatch，最后跑一次生成脚本。
- 新报告文件名带日期；只把**当前仍成立**的结论写进 `SKILL.md` / `data-sources.md`。
- 报告里被后续推翻的结论，在原文加「已被 X 取代」，不要删（保留决策轨迹）。
- 每轮结束跑一次 `../scripts/check.py`（pytest + F821 + 文档源序一致性）。
