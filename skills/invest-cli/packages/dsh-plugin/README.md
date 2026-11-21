# @taxueseek/invest-cli-dsh

DeepSeek Harness (DSH) 插件：基于 [taxue-invest](https://github.com/taxueseek/taxue-invest) 项目，把 invest-cli 的 24 个子命令收敛为单个 `invest` 原生工具，并提供**参照 Argo 体系设计**的原生可视化设置页（运行看板、接入配置、命令预算、数据源拓扑、API 凭据安全托管与高级调优）。

## 安装

### 方式 A：从 GitHub 安装（推荐）

```sh
dsh plugin --profile web add "github:taxueseek/taxue-invest#path:/packages/dsh-plugin"
```

### 方式 B：从本地路径安装

```sh
# <skills-root> = 本机技能安装根（npx skills add 装到哪个根就用哪个；常见 ~/.agents/skills 或 ~/.claude/skills）
dsh plugin --profile web add "file:<skills-root>/invest-cli/packages/dsh-plugin"
```

安装或更新后重启 DSH web 生效（终端执行 `restart-web.sh` 或重新打开 DSH 桌面端）。

---

## 参照 Argo 的架构设计

与 Argo（`@taxueseek/argo-dsh`）的工程设计同源，追求极致的 Token 经济性与企业级可靠性：

1. **单入口收敛架构 (Single Tool Facet)**：
   - 工具定义（名称 + 描述 + Schema）每轮请求都全量注入上下文且压缩无法剔除；
   - 24 个具名工具会产生 ≈4.5K token/轮 的常驻开销，而 invest-cli 各命令调用面相对均衡；
   - 单入口将常驻开销大幅压缩至 **≈0.5K token/轮**，同时保留全部 24 个子命令的完整能力。
2. **原生可视化设置页 (Visual Settings Panel)**：
   - 注册至 DSH 设置弹窗左侧一级菜单（`settings.section`）及插件卡片（`plugins.item`）；
   - 中英双语，零构建步骤（纯原生 ESM / React，DSH ModuleLoader 动态驱动）；
   - 提供 6 大功能面板：
     - **运行看板 (Dashboard)**：运行状态概览、三大工作流快速预设（极速日常 30s/16K、平衡投研 60s/24K、机构深研 120s/80K）、核心数据源矩阵与即时搜索过滤。
     - **接入与执行 (Access & Runtime)**：CLI 路径自动探测与自定义配置、默认超时、字符上限、JSON/表格模式切换、参数防爆保护。
     - **命令与预算 (Commands & Limits)**：24 个子命令场景化分类（行情快照/财报基本面/选股治理/机构透传/宏观辅助）、长耗时命令保护（tenure 180s, report 120s, sec 90s 等）。
     - **数据源拓扑 (Sources & Routing)**：A股、港股、基金、美股、选股等 5 条默认快照路由链与整单回退机制可视化展示。
     - **API 凭据安全托管 (API Keys Vault)**：接入 DSH 凭证库统一托管 9 类金融数据源 Key（同花顺、东财、妙想、万得、盈米、FMP、Tiingo、FRED、易方达），绝不写入代码库或普通配置文件，面板不回显明文。
     - **高级调优 (Advanced)**：safeClip 保护与结构性配置说明。
3. **safeClip 防坏 JSON 保护**：
   - 普通截断在超过字符上限时会硬性截断字符串，导致末尾括号丢失，模型解析崩溃；
   - `safeClip` 在检测到合法 JSON 超限时，就地封装为标准 JSON 错误信封，并携带 `truncated: true`、预览以及清晰的下一步建议（如换用 `--brief`、`--limit` 或拆分子查询）。
4. **确定性与漂移门禁**：
   - 内置静态漂移门禁（`test/client.test.js` 与 `test/index.test.js`），确保前后端命令名、数据源定义、API 凭据与默认参数 100% 严格一致。

---

## 工具调用用法

```javascript
invest(command="stock",  args=["600519"])                     // A股基本面与行情快照
invest(command="fund",   args=["005827"])                     // 公募基金净值与重仓
invest(command="us",     args=["AAPL", "--history"])          // 美股快照与历史序列
invest(command="quote",  args=["600519,00700,AAPL"])          // 免鉴权毫秒级批量行情
invest(command="sec",    args=["AAPL", "--insiders"])         // SEC EDGAR 原文级 10-K / 内部人
invest(command="cn",     args=["notice", "600519"])           // A股公告/一致预期/股东/披露日历
invest(command="screen", args=["净资产收益率大于15%"])         // 自然语言多因子选股
invest(command="tenure", args=["001959", "--manager", "余懿"]) // 基金经理任职期收益复盘（慢命令）
invest(command="capabilities")                                // 询问各源能力支持矩阵
```

* `json` 参数默认 `true`（返回结构化 JSON）；置 `false` 时返回人读终端表格。

---

## 本地同步脚本

DSH profile 对 `file:` 协议依赖进行复制拷贝，修改插件源码后必须同步至已安装的 profile 副本：

```sh
bash scripts/sync-local.sh            # 同步所有已安装 profile（web / desktop）
bash scripts/sync-local.sh --check    # 仅检测漂移状态
```

---

## 自动化测试与检查

```sh
npm run check                         # 语法与编译检查
npm test                              # 运行全量单元测试与漂移门禁（28+ 测试）
```
