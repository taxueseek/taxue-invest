#!/usr/bin/env python3
"""DSH 插件的数据源拓扑必须与 `data-sources.yaml` 同源（跨语言漂移门禁）。

插件运行在浏览器设置页里，不能读 yaml；第十轮起它也不再手写副本，而是消费
`dsh/registry.generated.js`（`sync_registry.py` 生成）。本测试直接解析生成物，
断言源 id 集合与 priority 逐项等于 yaml——生成物过期由 `sync_registry.py
--check` 另有一道门禁，这里锁的是「生成物内容确实来自 yaml」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_GENERATED = _SCRIPTS.parent / "packages" / "dsh-plugin" / "dsh" / "registry.generated.js"


def _plugin_sources() -> dict[str, int]:
    text = _GENERATED.read_text(encoding="utf-8")
    start = text.index("Object.freeze(") + len("Object.freeze(")
    payload = json.loads(text[start:text.rindex(")")])
    return {s["id"]: int(s["priority"]) for s in payload["sources"]}


def test_plugin_sources_match_config_truth() -> None:
    from sources import load_registry

    registry = load_registry()
    plugin = _plugin_sources()
    assert plugin, "未从注册表生成物解析到任何源"
    assert set(plugin) == set(registry), (
        f"插件与 yaml 源集合不一致：只在插件 = {sorted(set(plugin) - set(registry))}；"
        f"只在 yaml = {sorted(set(registry) - set(plugin))}"
    )
    mismatched = {
        sid: (plugin[sid], conf.get("priority"))
        for sid, conf in registry.items()
        if plugin[sid] != conf.get("priority")
    }
    assert not mismatched, f"优先级漂移（插件, yaml）：{mismatched}"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
