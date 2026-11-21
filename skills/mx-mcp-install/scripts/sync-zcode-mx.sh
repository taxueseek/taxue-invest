#!/usr/bin/env bash
# 从环境变量 EM_API_KEY 同步妙想 MCP 配置到 ZCode（config.json）
# 环境变量是 key 的唯一真源；本脚本把它写进 ZCode 需要的字面量字段。
# 用法：EM_API_KEY=em_xxx bash sync-zcode-mx.sh   （或已 export 时直接运行）
set -euo pipefail

CONFIG="${ZCODE_CONFIG:-$HOME/.zcode/cli/config.json}"
KEY="${EM_API_KEY:-}"

if [ -z "$KEY" ]; then
  echo "错误：未设置 EM_API_KEY 环境变量" >&2
  exit 1
fi
[ -f "$CONFIG" ] || { echo "错误：找不到 $CONFIG" >&2; exit 1; }

cp "$CONFIG" "$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"

python3 - "$CONFIG" "$KEY" <<'PY'
import json, sys
cfg, key = sys.argv[1], sys.argv[2]
d = json.load(open(cfg))
servers = d.setdefault("mcp", {}).setdefault("servers", {})
servers["mx-ds-mcp"] = {
    "type": "http",
    "url": "https://mxapi.eastmoney.com/mxds/mcp",
    "headers": {"em_api_key": key},
    "enabled": True,
}
json.dump(d, open(cfg, "w"), ensure_ascii=False, indent=2)
print("已同步 mx-ds-mcp ->", cfg)
PY
