"""命令注册表收口门禁：注册表 = parser = dispatch = 插件产物。

这四者过去各存一份，加命令时靠人记得改齐；本文件把它们钉成同一个集合。
插件侧（index.js / client.js）由 Node 测试再校验一次运行时消费。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import command_registry as reg  # noqa: E402
import invest_cli  # noqa: E402
import sync_registry  # noqa: E402
from command_registry import CATEGORIES, COMMANDS  # noqa: E402
from sources import load_registry  # noqa: E402


def test_command_ids_unique_and_categorized() -> None:
    ids = reg.command_ids()
    assert len(ids) == len(set(ids)), f"命令 id 重复：{ids}"
    cat_ids = {c["id"] for c in CATEGORIES}
    assert all(c["category"] in cat_ids for c in COMMANDS), "命令引用了不存在的分类"
    assert set(reg.categories_with_commands()[0]) >= {"id", "nameZh", "nameEn", "commands"}


def test_parser_and_dispatch_equal_registry() -> None:
    """build_parser 的 choices 与 dispatch 的键都必须等于注册表。"""
    parser = invest_cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert set(sub.choices) == set(reg.command_ids())
    for name in reg.command_ids():
        fn = getattr(invest_cli, f"cmd_{name.replace('-', '_')}", None)
        assert callable(fn), f"注册表有 {name}，invest_cli 缺 cmd_{name.replace('-', '_')}"


def test_budget_tables_only_reference_real_commands() -> None:
    ids = set(reg.command_ids())
    assert set(reg.TIMEOUTS) <= ids and set(reg.OUTPUT_LIMITS) <= ids


def test_direct_sources_are_declared() -> None:
    declared = set(load_registry())
    for cmd, sid in reg.direct_sources().items():
        assert cmd in set(reg.command_ids()), f"直取命令 {cmd} 不在注册表"
        assert sid in declared, f"直取源 {sid} 未在 data-sources.yaml 声明"


def test_source_presentation_covers_yaml() -> None:
    ids = set(load_registry())
    assert set(reg.SOURCE_EN) == ids, f"英文名与 yaml 不同步：{ids ^ set(reg.SOURCE_EN)}"
    assert reg.SOURCE_KEYLESS <= ids, f"免密标记引用了未声明源：{reg.SOURCE_KEYLESS - ids}"


def test_source_keys_reference_yaml_env_vars() -> None:
    env_vars = {
        str(conf.get("env_var") or (conf.get("detect") or {}).get("env_var"))
        for conf in load_registry().values()
        if conf.get("env_var") or (conf.get("detect") or {}).get("env_var")
    }
    for item in reg.SOURCE_KEYS:
        assert item["ref"] in env_vars, f"凭据面板的 {item['ref']} 不是 yaml 里的 env_var"


def test_research_limit_defaults_are_scene_specific() -> None:
    assert invest_cli._research_limit("fund-rank", None) == 200
    assert invest_cli._research_limit("etf-rank", None) == 50
    assert invest_cli._research_limit("etf-rank", 12) == 12


def test_generated_artifacts_are_current() -> None:
    data = sync_registry.build()
    expected = sync_registry._generated_js(data)
    assert sync_registry.GENERATED_JS.read_text(encoding="utf-8") == expected, (
        "registry.generated.js 过期：跑 python scripts/sync_registry.py"
    )
    client = sync_registry.CLIENT_JS.read_text(encoding="utf-8")
    assert sync_registry._replace_block(client, sync_registry._client_block(data)) == client, (
        "client.js 注册表块过期：跑 python scripts/sync_registry.py"
    )


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_registry: OK")
