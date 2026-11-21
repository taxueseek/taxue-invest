---
name: mx-mcp-install
description: "妙想(MX) MCP Server 安装配置技能：自动检测当前 Agent 类型，为 Claude Code、WorkBuddy、Codex、OpenClaw（含妙想Claw）、Cursor、Hermes Agent、Trae、QClaw 等主流 Agent 配置妙想 MCP Server，并提供兜底通用配置方法。"
version: 1.0.0
author: hermes-agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [mcp, 妙想, mx, eastmoney, 配置, 安装, claude-code, cursor, codex, openclaw, hermes, trae, qclaw, workbuddy, 妙想claw]
    related_skills: [native-mcp, hermes-agent, cross-agent-mcp-config]
---

# 妙想 MCP Server 安装配置技能

## 概述

本技能用于指导各类 AI Agent 配置**妙想(MX) MCP Server**，实现通过 MCP 协议访问东方财富妙想数据服务。

支持配置的 Agent 列表：Claude Code、WorkBuddy (CodeBuddy)、Codex、OpenClaw（含妙想Claw）、Cursor、Hermes Agent、Trae、QClaw。

对于不在列表中的 Agent，提供**兜底通用配置方法**。

**执行原则**：除 API KEY 获取可能需要用户参与外，其余检测、配置、验证、故障排查步骤都应由 Agent 优先尝试自动完成；只有遇到权限限制、需要用户在 UI 中操作、需要重启应用、或无法自动判断时，才请求用户协助。

---

## 核心信息

| 项目 | 值 |
|------|----|
| MCP Server 名称 | `mx-ds-mcp` |
| MCP Server URL | `https://mxapi.eastmoney.com/mxds/mcp` |
| 传输协议 | StreamableHttp |
| 认证请求头 | `em_api_key: <EM_API_KEY>`（优先使用环境变量 `EM_API_KEY`；未设置时由用户提供） |

---

## 完整处理流程

本技能按以下 4 步顺序执行，**不可跳步**：

```
步骤1: 获取 API KEY（跑检测脚本 → 有则用 → 无则问用户）
  ↓
步骤2: 检测当前 Agent 类型
  ↓
步骤3: 根据 Agent 类型执行对应配置方案
  ↓
步骤4: 验证 MCP 是否正常工作
```

---

## 步骤 1：获取 API KEY

**操作**：自动检测环境变量 `EM_API_KEY`；检测到则直接使用，不问用户；未检测到才向用户询问。

按当前操作系统选择对应命令：

- Windows：`if "%EM_API_KEY%"=="" (echo EM_API_KEY_FOUND=no) else (echo EM_API_KEY_FOUND=yes)`
- macOS/Linux：`if [ -z "$EM_API_KEY" ]; then echo EM_API_KEY_FOUND=no; else echo EM_API_KEY_FOUND=yes; fi`

分流：

| 输出 | 下一步 |
| --- | --- |
| `EM_API_KEY_FOUND=yes` | 执行 `echo $EM_API_KEY`（bash）或 `echo %EM_API_KEY%`（Windows CMD）读取实际值，记下后进入步骤 2（**不需要问用户**） |
| `EM_API_KEY_FOUND=no` | 向用户询问 API KEY |

向用户询问时使用以下文案：

> 未检测到环境变量 EM_API_KEY，请提供您的妙想 API KEY。如尚未获取，请前往妙想平台申请。

用户提供 API KEY 后，记录下来进入步骤 2。

- API KEY 格式校验：非空字符串，去除首尾空格后使用
- **安全提醒**：API KEY 属于敏感凭证，不要将其写入日志、打印到终端或提交到 git

---

## 步骤 2：检测当前 Agent 类型

### 2.1 自动检测（按优先级依次尝试）

| 优先级 | 检测方式 | 具体操作 |
|--------|---------|---------|
| 0 | **Agent 自认知** | Agent 根据自身长期记忆/系统信息判断自己属于哪个 Agent（如 Claude Code 知道自己是 Claude Code，WorkBuddy 知道自己是 WorkBuddy）。**能确定则直接使用，跳过后续检测** |
| 1 | 环境变量 | 检查 `HERMES_HOME` → Hermes Agent |
| 2 | CLI 工具 | `which claude` → Claude Code；`which codex` → Codex；`which openclaw` → OpenClaw；`which hermes` → Hermes Agent |
| 3 | 配置目录 | 检查以下目录是否存在（按顺序）： |

配置目录检测详情：

| Agent | Linux/Mac 检测路径 | Windows 检测路径                                          |
|-------|-------------------|-------------------------------------------------------|
| Claude Code | `~/.claude/` 或 `~/.claude.json` | `C:\Users\<用户>\.claude\` 或 `C:\Users\<用户>\.claude.json` |
| Codex | `~/.codex/` | `C:\Users\<用户>\.codex\`                               |
| OpenClaw | `~/.openclaw/` | `C:\Users\<用户>\.openclaw\`                            |
| Cursor | `~/.cursor/` | `C:\Users\<用户>\.cursor\`                              |
| Hermes Agent | `~/.hermes/` | `%LOCALAPPDATA%\hermes\`                              |
| Trae | `~/.trae/` | `%LOCALAPPDATA%\Trae CN\` 或 `C:\Users\<用户>\.trae-cn\`         |
| QClaw | `~/.qclaw/` | `C:\Users\<用户>\.qclaw\`                               |
| WorkBuddy | CodeBuddy IDE 进程 | CodeBuddy IDE 进程                                      |

### 2.2 OpenClaw / 妙想Claw 二级检测

如果步骤 2.1 识别当前 Agent 为 OpenClaw，需进一步判断是**原生 OpenClaw**还是**妙想Claw**（基于 OpenClaw 的妙想定制版）。直接运行 3.4 章节的检测脚本，按 `RESULT=` 输出值分流。

| RESULT 输出 | 后续配置指引 |
|------------|------------|
| `妙想Claw` | 进入 3.4 OpenClaw 章节，按妙想Claw 分支操作 |
| `原生OpenClaw` | 进入 3.4 OpenClaw 章节，按原生 OpenClaw 分支操作 |

### 2.3 用户确认

如果自动检测识别到多个可能的 Agent，或未能确定，则向用户确认：

> 检测到当前可能运行在 [Agent名称] 环境中，请确认您使用的是哪个 Agent？
> 可选项：Claude Code / WorkBuddy / Codex / OpenClaw（含妙想Claw） / Cursor / Hermes Agent / Trae / QClaw / 其他

如果用户选择"其他"，进入**兜底通用配置方法**（见下文）。

---

## 步骤 3：根据 Agent 类型执行对应配置方案

根据步骤 2 确定的 Agent 类型，跳转到对应章节执行配置。以下 `<EM_API_KEY>` 均替换为步骤 1 获取的**用户 API KEY 实际值**（字面量字符串）。

> ⚠️ **关键提醒**：所有 Agent 的配置文件（JSON/YAML/TOML）中，`em_api_key` 的值必须是**字面量字符串**——不要写成 `${EM_API_KEY}`、`$EM_API_KEY`、`%EM_API_KEY%` 等任何变量占位符，配置文件解析器不会展开这些语法。请先通过步骤 1 读取实际值，再直接写入。

---

### 3.1 Claude Code

**参考文档**：https://code.claude.com/docs/en/mcp-quickstart

#### 方式 A：CLI 命令（推荐，最可靠）

**全局生效**（所有项目可用，`--scope user`）：

```bash
claude mcp add --scope user --transport http mx-ds-mcp https://mxapi.eastmoney.com/mxds/mcp --header "em_api_key: <EM_API_KEY>"
```

**项目级生效**（仅当前项目可用，`--scope project`）：

```bash
claude mcp add --scope project --transport http mx-ds-mcp https://mxapi.eastmoney.com/mxds/mcp --header "em_api_key: <EM_API_KEY>"
```

#### 方式 B：编辑配置文件

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.claude.json` |
| Windows | `C:\Users\<用户名>\.claude.json` |

在配置文件中**合并**以下内容（保留已有其他配置，仅添加/更新 `mcpServers` 部分）：

```json
{
    "mcpServers": {
        "mx-ds-mcp": {
            "type": "http",
            "url": "https://mxapi.eastmoney.com/mxds/mcp",
            "headers": {
                "em_api_key": "<EM_API_KEY>"
            }
        }
    }
}
```

> ⚠️ **注意**：如果配置文件已有其他 `mcpServers` 条目，仅添加 `mx-ds-mcp` 这一个条目，不要覆盖已有的其他 MCP Server。

#### 验证方式

> ⛔ **必须重启 Claude Code 才能生效**：MCP 工具只在新会话中加载。配置完成后 Agent 必须提醒用户退出当前会话（输入 `/exit` 或关闭终端），然后重新启动 Claude Code。

提醒用户文案：

> ✅ MCP 配置完成。**请退出当前 Claude Code 会话（输入 `/exit` 或关闭终端），然后重新启动 Claude Code**，新的 MCP 工具才会加载到可用工具列表中。

重启后进入 Claude Code 交互界面，输入：

```
/mcp
```

查看 `mx-ds-mcp` 是否出现在已连接的 MCP Server 列表中且状态正常。

---

### 3.2 WorkBuddy

**参考文档**：https://www.codebuddy.cn/docs/ide/User-guide/MCP

#### 配置方法（修改配置文件 + 人工 UI 点击信任）

配置分两步执行，**不可跳步**：

---

**步骤 1**：修改配置文件

| 平台 | 配置文件路径                               |
|------|--------------------------------------|
| Linux / Mac | `~/.workbuddy/mcp.json`              |
| Windows | `C:\Users\<用户名>\.workbuddy\mcp.json` |

> ⚠️ **路径易错点**：文件名是 `mcp.json`，**不是** `.mcp.json`（没有前缀点号）。写错路径会导致配置不生效。

在配置文件中**合并**以下内容（保留已有其他配置，仅添加/更新 `mcpServers` 部分）：

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "type": "http",
      "url": "https://mxapi.eastmoney.com/mxds/mcp",
      "headers": {
          "em_api_key": "<EM_API_KEY>"
      }
    }
  }
}
```

---

**步骤 2**：人工 UI 点击信任（必须由用户操作，Agent 无法自动完成）

> ⛔ **配置写入后还必须手动点击信任才能激活！** 请用户执行以下操作：
>
> **新版本**：
>
> 1. 在 WorkBuddy 界面左侧导航中，找到 **专家** 页
> 2. 点击顶部的 **连接器** 标签页
> 3. 点击右上角的 **自定义连接器** 按钮，在弹出的对话框里找到我的 MCP 里的 mx-ds-mcp，点击其右侧的 **信任** 按钮
>
> 旧版本操作（如界面无「专家」页，请用此方式）
>
> 1. 在 WorkBuddy 界面左侧导航中，找到 **连接器** 并点击
> 2. 点击右上角的 **自定义连接器** 按钮，在弹出的对话框里找到我的 MCP 里的 mx-ds-mcp，点击其右侧的 **信任** 按钮
>

> ⛔ **Agent 输出纪律**：以上信任提醒**必须是 Agent 回复的最后一部分**，且必须视觉上独立醒目（使用 ⛔ 前缀 + 独立段落）。配置摘要、验证方式等辅助信息应放在信任提醒**之前**，绝不允许信任提醒被淹没在长文本中间或被其他内容压过。

---

#### 信任生效后验证

信任激活后，在 WorkBuddy 对话中输入：

> 使用 mx-ds-mcp 查询贵州茅台最新价

观察是否成功调用 MCP 工具并返回数据。

---

### 3.3 Codex

**参考文档**：https://www.runoob.com/codex/codex-mcp.html

#### 配置方法（编辑配置文件）

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.codex/config.toml` |
| Windows | `C:\Users\<用户名>\.codex\config.toml` |

在 `config.toml` 文件的 `[mcp_servers]` 段落下添加：

```toml
[mcp_servers.mx-ds-mcp]
url = "https://mxapi.eastmoney.com/mxds/mcp"
transport = "StreamableHttp"
http_headers = {em_api_key = "<EM_API_KEY>"}
```

> ⚠️ **关键注意**：
> - Codex 使用 **TOML 格式**（非 JSON），语法与 JSON 完全不同
> - `transport` 值为 `"StreamableHttp"`（注意大小写）
> - `http_headers` 使用 TOML 内联表语法 `{key = "value"}`
> - 如果配置文件已有其他 `[mcp_servers.xxx]` 段落，在其后追加即可

#### 验证方式

在 Codex 交互界面中，检查 MCP 工具列表中是否出现 `mx-ds-mcp` 的工具。

---

### 3.4 OpenClaw（含妙想Claw）

**参考文档**：https://docs.openclaw.ai/cli/mcp#streamable-http-transport

配置分三步执行，**不可跳步**：

---

#### 第 1 步：修改配置文件

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.openclaw/openclaw.json` |
| Windows | `C:\Users\<用户名>\.openclaw\openclaw.json` |

在配置文件中**合并**以下内容：

```json
{
  "mcp": {
    "servers": {
      "mx-ds-mcp": {
        "url": "https://mxapi.eastmoney.com/mxds/mcp",
        "transport": "streamable-http",
        "connectTimeout": 10,
        "timeout": 120,
        "headers": {
          "em_api_key": "<EM_API_KEY>"
        }
      }
    }
  }
}
```

> ⚠️ **关键注意**：
> - OpenClaw 使用 `mcp.servers` 嵌套结构（**不是** `mcpServers`）
> - `transport` 值为 `"streamable-http"`（全小写，带连字符）
> - 建议设置 `connectTimeout: 10` 和 `timeout: 120` 避免超时
> - 如果配置文件已有 `mcp.servers` 下的其他条目，仅添加 `mx-ds-mcp` 条目

---

#### 第 2 步：检测是妙想Claw还是原生 OpenClaw

直接执行以下脚本，输出 `RESULT=妙想Claw` 或 `RESULT=原生OpenClaw`：

**Linux / Mac / Windows（bash）**：

```bash
MX_CLAW=0
if [ -d ~/.openclaw/extensions/mx-claw ]; then
  if [ -n "$INGRESS_URL" ] && [ -n "$KUBERNETES_PORT" ]; then MX_CLAW=1; fi
  if [ -n "$WUYING_INSTANCE_ID" ]; then MX_CLAW=1; fi
fi
if [ "$MX_CLAW" = "1" ]; then echo "RESULT=妙想Claw"; else echo "RESULT=原生OpenClaw"; fi
```

**Windows（CMD）**：

```cmd
set MX_CLAW=0
if exist "%USERPROFILE%\.openclaw\extensions\mx-claw" (
  if defined INGRESS_URL if defined KUBERNETES_PORT set MX_CLAW=1
  if defined WUYING_INSTANCE_ID set MX_CLAW=1
)
if "%MX_CLAW%"=="1" (echo RESULT=妙想Claw) else (echo RESULT=原生OpenClaw)
```

> **检测逻辑说明**：标记目录 `~/.openclaw/extensions/mx-claw` 是前提门槛；通过后还需环境变量确认（K8s 组合 `INGRESS_URL` + `KUBERNETES_PORT`，或无影组合 `WUYING_INSTANCE_ID`），两者缺一则标记目录视为残留，仍判原生 OpenClaw。

---

#### 第 3 步：根据检测结果完成重启生效

> ⛔ **配置完成后必须重启才能生效！** 请根据第 2 步检测结果执行对应操作：

**如果是妙想Claw**：

> ⛔ 请点击妙想Claw右上角「设置」按钮（齿轮图标） → 点击「重启妙想Claw」

**如果是原生 OpenClaw**：

> ⛔ 请跟 OpenClaw 说：「帮我重启网关」

> ⛔ **Agent 输出纪律**：以上重启提醒**必须是 Agent 回复的最后一部分**，且必须视觉上独立醒目（使用 ⛔ 前缀 + 独立段落）。配置摘要、验证方式等辅助信息应放在重启提醒**之前**，绝不允许重启提醒被淹没在长文本中间或被其他内容压过。

---

#### 重启生效后验证

重启完成后，在 OpenClaw / 妙想Claw 对话中，**需要主动提示模型去使用 MCP 查询**，例如：

> 使用 mx-ds-mcp 查询东方财富市盈率

---

### 3.5 Cursor

**参考文档**：https://cursor.com/cn/docs/mcp

#### 方式 A：UI 操作（推荐）

1. 打开 Cursor 设置页面：**Tools & MCPs**
2. 点击 **New MCP Server**
3. 按以下信息填写：
    - Name: `mx-ds-mcp`
    - Type/Transport: `http` 或 `streamable-http`
    - URL: `https://mxapi.eastmoney.com/mxds/mcp`
    - Header: `em_api_key` = `<EM_API_KEY>`
4. 保存

#### 方式 B：编辑配置文件

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.cursor/mcp.json` |
| Windows | `C:\Users\<用户名>\.cursor\mcp.json` |

在配置文件中**合并**以下内容：

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "url": "https://mxapi.eastmoney.com/mxds/mcp",
      "headers": {
        "em_api_key": "<EM_API_KEY>"
      }
    }
  }
}
```

> ⚠️ Cursor 的 `mcpServers` 条目中**无需**显式指定 `type` 字段，Cursor 会根据 `url` 字段自动识别为 HTTP 传输。

#### 验证方式

在 Cursor 的 **Tools & MCPs** 设置页面中，查看 `mx-ds-mcp` 的连接状态指示灯：
- 🟢 绿色 = 已连接 ✅
- 🔴 红色 = 连接失败 ❌
- ⚪ 灰色 = 未连接

---

### 3.6 Hermes Agent

**参考文档**：
- https://hermes-agent.nousresearch.com/docs/guides/use-mcp-with-hermes
- https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference

#### 配置方法（编辑配置文件）

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.hermes/config.yaml` |
| Windows | `%LOCALAPPDATA%\hermes\config.yaml`（即 `C:\Users\<用户名>\AppData\Local\hermes\config.yaml`） |

> ⚠️ **Windows 路径特殊**：Hermes Agent 在 Windows 下的配置目录是 `%LOCALAPPDATA%\hermes\`，**不是** `C:\Users\<用户名>\.hermes\`。`~/.hermes/` 在 Windows 上是无效路径。

在 `config.yaml` 中**合并**以下内容：

```yaml
mcp_servers:
  mx-ds-mcp:
    url: "https://mxapi.eastmoney.com/mxds/mcp"
    headers:
      em_api_key: "<EM_API_KEY>"
    tools:
      include: []
```

> **字段说明**：
> - `tools.include: []` — 空列表表示包含所有工具（无过滤），如需限制可填入指定工具名
> - Hermes 使用 **YAML 格式** + **下划线键名** `mcp_servers`（非 JSON 的 `mcpServers`）
> - 如果配置文件已有 `mcp_servers` 下的其他条目，仅添加 `mx-ds-mcp` 条目

#### 重新加载 MCP

配置完成后，在 Hermes 交互界面中执行：

```
/reload-mcp
```

或通过 CLI 重新加载：

```bash
hermes mcp list
```

#### CLI 验证

```bash
hermes mcp test mx-ds-mcp
```

---

### 3.7 Trae

**参考文档**：https://docs.trae.cn/ide/add-mcp-servers

#### 方式 A：UI 操作（推荐）

1. 打开 Trae 设置页面：**MCP**
2. 点击 **添加** → **手动配置**
3. 在 JSON 配置编辑器中输入：

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "url": "https://mxapi.eastmoney.com/mxds/mcp",
      "headers": {
        "em_api_key": "<EM_API_KEY>"
      }
    }
  }
}
```

4. 保存

#### 方式 B：编辑配置文件

| 平台 | 配置文件路径                                                          |
|------|-----------------------------------------------------------------|
| Linux / Mac | `~/.trae/mcp.json`                                              |
| Windows | `%LOCALAPPDATA%\Trae CN\User\mcp.json` 或 `C:\Users\<用户名>\.trae-cn\mcp.json` |

在配置文件中**合并**以下内容：

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "url": "https://mxapi.eastmoney.com/mxds/mcp",
      "headers": {
        "em_api_key": "<EM_API_KEY>"
      }
    }
  }
}
```

#### 验证方式

在 Trae 的 **MCP** 设置页面中，查看 `mx-ds-mcp` 的连接状态是否正常。

---

### 3.8 QClaw

#### 方式 A：编辑配置文件

| 平台 | 配置文件路径 |
|------|------------|
| Linux / Mac | `~/.qclaw/openclaw.json` |
| Windows | `C:\Users\<用户名>\.qclaw\openclaw.json` |

在配置文件中**合并**以下内容：

```json
{
  "mcp": {
    "servers": {
      "mx-ds-mcp": {
        "url": "https://mxapi.eastmoney.com/mxds/mcp",
        "headers": {
          "em_api_key": "<EM_API_KEY>",
          "Accept": "application/json, text/event-stream"
        },
        "type": "http",
        "transport": "streamable-http"
      }
    }
  }
}
```

> ⚠️ **QClaw 特殊注意**：
> - 使用 `mcp.servers` 嵌套结构（与 OpenClaw 相同）
> - **必须**额外添加 `Accept: application/json, text/event-stream` 请求头，否则可能调用失败
> - 需要显式指定 `"type": "http"`
> - 需要显式指定 `"transport": "streamable-http"`

#### 方式 B：对话方式安装

直接将上述 JSON 配置通过对话发给 QClaw，让其自行安装配置。

#### 验证方式

在 QClaw 对话中，尝试使用 MCP 工具查询数据：

> 使用 mx-ds-mcp 查询贵州茅台最新价

---

## 步骤 4：验证 MCP 是否正常工作

### 4.1 标准验证查询

配置完成后，使用以下标准查询验证 MCP 是否正常工作：

> **贵州茅台今天最新价**

### 4.2 验证操作步骤

1. 在 Agent 对话中输入验证查询："贵州茅台今天最新价"
2. 观察是否成功调用了 `mx-ds-mcp` 的 MCP 工具
3. 检查返回结果是否包含贵州茅台（600519）的股价数据
4. 判断结果：
    - ✅ 返回有效股价数据 → **配置成功**
    - ❌ 调用失败 / 无响应 / 报错 → 进入故障排查

### 4.3 各 Agent 专属验证方式

| Agent | 专属验证操作 |
|-------|------------|
| Claude Code | 交互界面输入 `/mcp`，查看 mx-ds-mcp 连接状态 |
| WorkBuddy | 对话输入"使用 mx-ds-mcp 查询贵州茅台最新价" |
| Codex | 交互界面检查 MCP 工具列表中是否出现 mx-ds-mcp 工具 |
| OpenClaw（含妙想Claw） | 原生 OpenClaw：CLI 执行 `openclaw mcp list`；妙想Claw：对话中输入"使用 mx-ds-mcp 查询东方财富市盈率" |
| Cursor | Tools & MCPs 页面查看 mx-ds-mcp 连接状态指示灯是否为绿色 |
| Hermes Agent | CLI 执行 `hermes mcp test mx-ds-mcp`，或交互界面 `/reload-mcp` 后查看工具列表 |
| Trae | MCP 设置页面查看 mx-ds-mcp 连接状态 |
| QClaw | 对话中尝试使用 MCP 工具查询 |

---

## 兜底通用配置方法

当用户当前 Agent **不在**上述 8 种已覆盖范围内时，采用以下通用指导方法：

### 通用配置步骤

#### 第 1 步：确认 Agent 是否支持 MCP

- 查阅 Agent 官方文档，搜索关键词：**"MCP"**、**"Model Context Protocol"**、**"MCP Server"**
- 如果 Agent **不支持 MCP 协议**，则无法配置妙想 MCP Server，提示用户：
  > 当前 Agent 不支持 MCP 协议，无法配置妙想 MCP Server。建议使用支持 MCP 的 Agent（如 Claude Code、Cursor、Hermes Agent 等）。

#### 第 2 步：确认 Agent 支持的传输协议

- 查阅文档确认 Agent 支持哪种 MCP 传输协议
- 妙想 MCP Server 使用 **StreamableHttp** 协议
- 三种情况：
    - ✅ **支持 HTTP / StreamableHttp** → 直接配置（进入第 3 步）
    - ✅ **支持 SSE** → 可尝试配置（部分 Agent 的 SSE 兼容 StreamableHttp）
    - ❌ **仅支持 stdio** → 需要使用 stdio 代理（见下文"stdio 代理方案"）

#### 第 3 步：找到 Agent 的 MCP 配置位置

常见配置位置模式：

| 模式 | 示例路径 |
|------|---------|
| Agent 全局配置目录 | `~/.<agent-name>/` 下的 JSON/YAML/TOML 文件 |
| Agent 设置界面 | Settings / Preferences → MCP / Tools / Integrations |
| VS Code 扩展设置 | `.vscode/settings.json` |
| 项目级配置 | 项目根目录 `.<agent-name>/` 下 |

#### 第 4 步：确定配置格式并添加

**通用 JSON 配置模板**（适用于大多数 Agent）：

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "type": "http",
      "url": "https://mxapi.eastmoney.com/mxds/mcp",
      "headers": {
        "em_api_key": "<EM_API_KEY>"
      }
    }
  }
}
```

**不同 Agent 可能使用的顶层键名**（按常见程度排序）：

| 顶层键名 | 适用 Agent 类型 | 格式 |
|---------|--------------|------|
| `mcpServers` | 大多数 Agent（Claude Code、Cursor、WorkBuddy、Trae 等） | JSON |
| `mcp.servers` | OpenClaw 系（OpenClaw、QClaw、妙想Claw） | JSON |
| `mcp_servers` | Hermes Agent | YAML |
| `roo.mcpServers` | Roo Code | JSON (VS Code settings) |
| `cline.mcpServers` | Cline | JSON (VS Code settings) |

> 💡 **提示**：如果不确定顶层键名，先查看 Agent 配置文件中已有的 MCP 配置，模仿其格式添加。

#### stdio 代理方案（当 Agent 仅支持 stdio 传输时）

如果 Agent 仅支持 stdio 传输（不支持 HTTP/StreamableHttp），需要使用代理工具将 HTTP MCP 转为 stdio。

**方案 A：使用 `mcp-remote` 代理**

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mxapi.eastmoney.com/mxds/mcp", "--header", "em_api_key:<EM_API_KEY>"]
    }
  }
}
```

**方案 B：使用 `supergateway` 代理**

```json
{
  "mcpServers": {
    "mx-ds-mcp": {
      "command": "npx",
      "args": ["-y", "supergateway", "--streamableHttp", "https://mxapi.eastmoney.com/mxds/mcp", "--header", "em_api_key:<EM_API_KEY>"]
    }
  }
}
```

> ⚠️ 使用 stdio 代理方案需要 Node.js 环境（npx 命令可用）。首次运行时代理会自动下载依赖，可能较慢。

#### 第 5 步：重启 Agent 使配置生效

配置完成后，**必须重启 Agent**（完全退出后重新打开）才能加载新的 MCP 配置。

---

## 配置速查表

| Agent | 配置文件路径 (Linux/Mac) | 配置文件路径 (Windows) | 格式 | 顶层键名 | 传输方式标识 |
|-------|------------------------|----------------------|------|---------|------------|
| Claude Code | `~/.claude.json` | `C:\Users\<用户>\.claude.json` | JSON | `mcpServers` | `type: "http"` |
| WorkBuddy | `~/.workbuddy/mcp.json` | `C:\Users\<用户>\.workbuddy\mcp.json` | JSON | `mcpServers` | `type: "http"` |
| Codex | `~/.codex/config.toml` | `C:\Users\<用户>\.codex\config.toml` | TOML | `[mcp_servers.xxx]` | `transport = "StreamableHttp"` |
| OpenClaw（含妙想Claw） | `~/.openclaw/openclaw.json` | `C:\Users\<用户>\.openclaw\openclaw.json` | JSON | `mcp.servers` | `transport: "streamable-http"` |
| Cursor | `~/.cursor/mcp.json` | `C:\Users\<用户>\.cursor\mcp.json` | JSON | `mcpServers` | 自动识别（无需指定） |
| Hermes Agent | `~/.hermes/config.yaml` | `%LOCALAPPDATA%\hermes\config.yaml` | YAML | `mcp_servers` | 自动识别（无需指定） |
| Trae | `~/.trae/mcp.json` | `C:\Users\<用户>\.trae\mcp.json` | JSON | `mcpServers` | 自动识别（无需指定） |
| QClaw | `~/.qclaw/openclaw.json` | `C:\Users\<用户>\.qclaw\openclaw.json` | JSON | `mcp.servers` | `type: "http"` |

> ⚠️ **WorkBuddy 特殊**：配置文件可直接编辑，但写入后需在 UI 中手动点击"信任"才能激活（参见 3.2 章节）。

---

## 故障排查

| 问题                   | 可能原因                    | 解决方法                                                         |
|----------------------|-------------------------|--------------------------------------------------------------|
| MCP Server 不出现在列表中   | 配置文件路径错误                | 对照上方速查表确认路径                                                  |
| MCP Server 不出现在列表中   | JSON/YAML/TOML 语法错误     | JSON: `python3 -m json.tool <path>` 验证；YAML: 检查缩进；TOML: 检查语法 |
| MCP Server 不出现在列表中   | 顶层键名错误                  | 确认使用正确的键名（`mcpServers` / `mcp.servers` / `mcp_servers`）      |
| MCP Server 出现但连接失败   | 网络问题                    | 检查能否访问 `https://mxapi.eastmoney.com/mxds/mcp`                |
| MCP Server 出现但连接失败   | API KEY 无效或过期           | 确认 API KEY 正确，重新获取                                           |
| 工具调用返回错误             | 请求头未正确传递                | 检查 `headers` 中 `em_api_key` 是否正确设置                           |
| 重启后仍不生效              | 编辑了错误的配置文件              | 确认全局 vs 项目级路径，Windows 下注意 Hermes 特殊路径                        |
| Hermes MCP 不加载       | Windows 下路径错误           | 确认使用 `%LOCALAPPDATA%\hermes\config.yaml`，不是 `~/.hermes/`     |
| Cursor / Trae 不生效    | 未完全重启 IDE               | **完全退出** IDE（不是只关闭窗口），然后重新打开                                 |
| OpenClaw 配置后无法立即使用   | 需要重启来生效工具 | 引导用户跟 OpenClaw 说：帮我重启网关                                      |
| 妙想Claw 配置后无法立即使用 MCP | 需要重启来生效工具 | 引导用户点击右上角齿轮图标 → "重启妙想Claw"                                   |
| QClaw 调用失败           | 缺少 Accept 请求头           | 确认添加 `Accept: application/json, text/event-stream`           |
| Codex 配置不生效          | 使用了 JSON 格式             | Codex 使用 **TOML 格式**，不是 JSON                                 |
| Agent 仅支持 stdio 传输   | 不支持 HTTP/StreamableHttp | 使用 `mcp-remote` 或 `supergateway` 作为 stdio 代理                 |
| 工具调用超时               | 查询耗时过长                  | 增大 `timeout` 值                                               |

---

## 安全注意事项

1. **API Key 不要硬编码提交到 git** — 在 `.gitignore` 中添加各 Agent 配置目录
2. **API Key 不要打印到终端或日志** — 配置时直接写入文件，避免 echo/print
3. **推荐 `.gitignore` 条目**：

```gitignore
# MCP 配置文件（可能含 API Key）
.claude/
.claude.json
.cursor/mcp.json
.codex/
.openclaw/
.trae/
.qclaw/
.windsurf/
```

4. **Hermes Agent 特殊**：Hermes 自动过滤环境变量，stdio 子进程只收到安全基线变量 + `env` 中显式声明的变量
5. **Claude Code 同理**：只传递 `env` 中声明的变量给 MCP 子进程
