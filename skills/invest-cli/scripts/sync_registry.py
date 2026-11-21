#!/usr/bin/env python3
"""把命令注册表与 data-sources.yaml 生成插件侧产物。

用法：
    python scripts/sync_registry.py          # 写入/更新
    python scripts/sync_registry.py --check  # 只校验是否为最新（CI/check.py）

产物两处，都是「生成物，不手改」：
  1. packages/dsh-plugin/dsh/registry.generated.js —— ESM 模块，index.js 直接 import；
  2. client.js 内 `>>> generated: registry` 标记块 —— ModuleLoader 是 lazy-CJS，
     拿不到 ESM import，只能内联同一份 JSON。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from command_registry import (  # noqa: E402
    DEFAULTS,
    OUTPUT_LIMITS,
    SOURCE_EN,
    SOURCE_KEYS,
    SOURCE_KEYLESS,
    TIMEOUTS,
    categories_with_commands,
    command_ids,
)
from sources import load_registry  # noqa: E402

PLUGIN = HERE.parent / "packages" / "dsh-plugin" / "dsh"
GENERATED_JS = PLUGIN / "registry.generated.js"
CLIENT_JS = PLUGIN / "client.js"

BEGIN = "// >>> generated: registry (scripts/sync_registry.py) — do not edit by hand"
END = "// <<< generated: registry"


def _sources() -> list[dict]:
    """yaml → 插件数据源面板。只补英文名与免密标记（展示层）。"""
    out = []
    for sid, conf in load_registry().items():
        files = (conf.get("detect") or {}).get("files") or []
        ref = str(
            conf.get("env_var")
            or (conf.get("detect") or {}).get("env_var")
            or (files[0] if files else "")
            or ""
        )
        out.append({
            "id": sid,
            "nameZh": str(conf.get("name") or sid),
            "nameEn": SOURCE_EN.get(sid, sid),
            "priority": int(conf.get("priority") or 0),
            "coverage": ", ".join(conf.get("coverage") or []),
            "kind": str(conf.get("kind") or ""),
            "ref": ref,
            "keyless": sid in SOURCE_KEYLESS,
        })
    out.sort(key=lambda s: (-s["priority"], s["id"]))
    return out


def _plugin_commands() -> list[dict]:
    """分类下的命令只保留展示字段；direct_source 是运行时概念，不进 UI。"""
    return [
        {
            **cat,
            "commands": [
                {k: c[k] for k in ("id", "zh", "en", "desc") if k in c}
                for c in cat["commands"]
            ],
        }
        for cat in categories_with_commands()
    ]


def build() -> dict:
    return {
        "categories": _plugin_commands(),
        "commands": command_ids(),
        "timeouts": TIMEOUTS,
        "outputLimits": OUTPUT_LIMITS,
        "defaults": DEFAULTS,
        "sources": _sources(),
        "sourceKeys": SOURCE_KEYS,
    }


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _generated_js(data: dict) -> str:
    return (
        "// 生成物：scripts/sync_registry.py 从 command_registry.py 与 data-sources.yaml 生成。\n"
        "// 不要手改；加命令先改注册表，再跑 sync_registry.py。\n"
        f"export const REGISTRY = Object.freeze({_json(data)})\n"
    )


def _client_block(data: dict) -> str:
    return (
        f"{BEGIN}\n"
        f"    const REGISTRY = {_json(data)};\n"
        "    const COMMAND_CATEGORIES = REGISTRY.categories;\n"
        "    const COMMANDS = REGISTRY.commands;\n"
        "    const DATA_SOURCES = REGISTRY.sources;\n"
        "    const DATA_SOURCE_KEYS = REGISTRY.sourceKeys;\n"
        "    const DEFAULTS = REGISTRY.defaults;\n"
        f"    {END}"
    )


def _replace_block(text: str, block: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(f"client.js 缺少生成块标记：{BEGIN!r} / {END!r}")
    return text[:start] + block + text[end + len(END):]


def main(argv: list[str]) -> int:
    data = build()
    expected_js = _generated_js(data)
    client = CLIENT_JS.read_text(encoding="utf-8")
    try:
        expected_client = _replace_block(client, _client_block(data))
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    if "--check" in argv:
        stale = []
        if not GENERATED_JS.is_file() or GENERATED_JS.read_text(encoding="utf-8") != expected_js:
            stale.append(GENERATED_JS)
        if client != expected_client:
            stale.append(CLIENT_JS)
        if stale:
            print("注册表产物过期：" + "、".join(str(p) for p in stale), file=sys.stderr)
            print("修复：python scripts/sync_registry.py", file=sys.stderr)
            return 1
        print("registry artifacts: OK")
        return 0

    GENERATED_JS.write_text(expected_js, encoding="utf-8")
    if client != expected_client:
        CLIENT_JS.write_text(expected_client, encoding="utf-8")
    print(f"已生成 {GENERATED_JS}")
    print(f"已同步 {CLIENT_JS} 的注册表块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
