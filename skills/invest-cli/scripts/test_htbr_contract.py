#!/usr/bin/env python3
"""htbr 透传层契约测试（全部离线；上游未安装时存在性断言自动跳过）。

三个契约（对应研究报告 dim-agent/research/htbr-etf-skill-研究.md 的已验证事实）：

1. 别名表的每个目标 api_id 必须真实存在于上游 references/apis/。上游会改名/
   下线接口（0.9.6 删过 fund-benchmark-trend；1.0.8 暂停一组单指标接口且
   changelog 一字未提）——「别名指向存在」是对上游的信念，必须逐条机械验证，
   不能照着任何版本的文档抄。
2. 暂停接口不得进别名表：合并版 fund-return-risk 才是正路，导航指路到暂停
   接口等于主动制造失败调用（初版别名表的真实事故，已剔除断言钉住）。
3. 信封语义：空结果 ok=True + empty 标记 + 不落缓存（错口径静默回 0 行，
   30 分钟 TTL 会把口径错误钉住）；quota/scope/degraded 类错误带 error_kind，
   供上层决定重试节奏而不是盲目重烧配额。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources import htbr as htbr_src

_UPSTREAM = htbr_src.skill_dir()

# catalog:88-95 声明「暂停保留」的单指标接口（catalog 自称 7 个、实际列举 11 个，
# 以列举为准；合并版 fund-return-risk 是唯一正路）
PAUSED_ENDPOINTS = {
    "fund-stage-performance", "fund-monthly-return", "fund-quarterly-return",
    "fund-yearly-return", "fund-return-sum", "fund-max-dd",
    "fund-sharpe", "fund-calmar", "fund-info-ratio",
    "fund-annual-return", "fund-annual-risk",
}

_SKIP = pytest.mark.skipif(_UPSTREAM is None, reason="未安装 htbr-etf-skill，别名存在性无从验证")


@_SKIP
def test_alias_targets_exist_upstream() -> None:
    apis = _UPSTREAM / "references" / "apis"
    missing = [t for t in sorted(set(htbr_src.API_ALIASES.values()))
               if not (apis / f"{t}.md").is_file()]
    assert not missing, f"别名指向不存在的上游接口（上游可能已改名/下线）：{missing}"


@_SKIP
def test_manager_family_fully_covered() -> None:
    """基金经理 20 接口是 1.0.8 的核心增量、也是本源对既有源的独有能力面：
    导航不给全等于白接（初版只覆盖 8/20，13 个新接口里 11 个打不出来）。"""
    apis = _UPSTREAM / "references" / "apis"
    targets = set(htbr_src.API_ALIASES.values())
    manager = {p.stem for p in apis.glob("fund-manager-*.md")}
    missing = sorted(manager - targets)
    assert not missing, f"上游经理接口未进导航别名表：{missing}"


@_SKIP
def test_index_family_fully_covered() -> None:
    apis = _UPSTREAM / "references" / "apis"
    targets = set(htbr_src.API_ALIASES.values())
    index = {p.stem for p in apis.glob("index-*.md")}
    missing = sorted(index - targets)
    assert not missing, f"上游指数接口未进导航别名表：{missing}"


def test_no_paused_endpoint_aliased() -> None:
    leaked = PAUSED_ENDPOINTS & set(htbr_src.API_ALIASES.values())
    assert not leaked, f"导航指路到上游暂停接口（正路是合并版 return-risk）：{leaked}"


# ---------- 信封语义（自包含：临时目录伪造上游 + 打桩 subprocess.run） ----------


class _FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_upstream(tmp_path, monkeypatch):
    d = tmp_path / "htbr-etf-skill"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "api_client.py").write_text("# fake client\n", encoding="utf-8")
    monkeypatch.setenv("HTBR_SKILL_DIR", str(d))
    # 缓存改为内存 store（真实读写语义），与真实缓存目录隔离
    import _common

    store: dict = {}
    writes: list[tuple] = []
    monkeypatch.setattr(_common, "cache_get", lambda ns, key, ttl=None: store.get((ns, key)))
    monkeypatch.setattr(_common, "cache_set",
                        lambda ns, key, value: (store.__setitem__((ns, key), value),
                                                writes.append((ns, key))))
    return writes


def test_empty_result_flagged_and_not_cached(fake_upstream, monkeypatch) -> None:
    monkeypatch.setattr(
        htbr_src.subprocess, "run",
        lambda *a, **k: _FakeResult(stdout=json.dumps({"success": True, "data": []})))
    res = htbr_src.call("fund-basic-info", params={"fundCode": "510300"})
    assert res["ok"] is True and res.get("empty") is True
    assert "口径" in (res.get("hint") or "")
    assert fake_upstream == [], "空结果不得落缓存（口径错误会被 30 分钟 TTL 钉住）"


def test_nonempty_result_cached(fake_upstream, monkeypatch) -> None:
    monkeypatch.setattr(
        htbr_src.subprocess, "run",
        lambda *a, **k: _FakeResult(stdout=json.dumps({"success": True, "data": {"a": 1}})))
    res = htbr_src.call("fund-basic-info", params={"fundCode": "510300"})
    assert res["ok"] is True and "empty" not in res
    assert len(fake_upstream) == 1


def test_quota_error_carries_kind(fake_upstream, monkeypatch) -> None:
    msg = "今日调用配额已用尽（每日 500 次），请明日再试或联系管理员提升配额；当日请勿继续调用。"
    monkeypatch.setattr(
        htbr_src.subprocess, "run",
        lambda *a, **k: _FakeResult(returncode=1, stderr=msg))
    res = htbr_src.call("fund-basic-info", params={})
    assert res["ok"] is False and res.get("error_kind") == "quota"


def test_scope_and_not_found_and_degraded_kinds(fake_upstream, monkeypatch) -> None:
    cases = {
        "当前 Key 无权访问该接口（缺少 scope: fund-manager-image），请联系管理员开通授权，请勿尝试绕过。": "scope_denied",
        "接口不存在: fund-nope。请检查 api_id 是否正确，以及 BASE_URL 是否指向本冲刺网关环境。": "api_not_found",
        "服务暂不可用，请稍后重试；如持续失败请联系管理员并提供 trace_id: t123": "degraded",
    }
    for msg, kind in cases.items():
        monkeypatch.setattr(
            htbr_src.subprocess, "run",
            lambda *a, m=msg, **k: _FakeResult(returncode=1, stderr=m))
        res = htbr_src.call("fund-nope", params={})
        assert res["ok"] is False and res.get("error_kind") == kind, msg


def test_need_key_envelope(fake_upstream, monkeypatch) -> None:
    monkeypatch.setattr(
        htbr_src.subprocess, "run",
        lambda *a, **k: _FakeResult(returncode=3, stdout="引导文案", stderr="[NEED_KEY] 凭证不可用"))
    res = htbr_src.call("fund-basic-info", params={})
    assert res["ok"] is False and res.get("need_key") is True


def test_params_json_and_params_dict_agree(fake_upstream, monkeypatch) -> None:
    """params dict 与 params_json 两种入参生成同一缓存键（同一口径才命中）。"""
    seen: list[str] = []

    def fake_run(url, *a, **k):
        seen.append(url)
        return _FakeResult(stdout=json.dumps({"success": True, "data": {"x": len(seen)}}))

    monkeypatch.setattr(htbr_src.subprocess, "run", fake_run)
    r1 = htbr_src.call("fund-basic-info", params={"fundCode": "510300"})
    r2 = htbr_src.call("fund-basic-info", params_json=json.dumps({"fundCode": "510300"}))
    assert len(seen) == 1, "同参数两种入参必须命中同一缓存，实付两次上游调用"
    assert r1["data"] == r2["data"] and r2.get("cached") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
