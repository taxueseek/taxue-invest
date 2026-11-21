#!/usr/bin/env python3
"""invest-cli report —— 基金定期报告 PDF（季报/半年报/年报，东方财富源）。

为什么需要这条命令：invest-fund 三关审查要读报告原文（经理报告/持仓明细/费率
结构），人工路径是「开天天基金 F10 → 基金公告 → 定期报告 → 逐份点下载」，且附件
链接藏在一层 JS 异步接口后面。本命令把「公告清单 + PDF 直链」收敛成一次调用；
`--latest 4` 一条命令拿齐最近四季，可直接喂 report-reader 做原文分析。

链路（2026-10-05 实测，两步）:
  1. GET https://api.fund.eastmoney.com/f10/JJGG?fundcode=<代码>&type=3
     必须带 Referer: https://fundf10.eastmoney.com/jjgg_<代码>.html，否则空响应——
     这是东财公告 API 唯一的门槛。
  2. GET https://pdf.dfcfw.com/pdf/H2_<公告ID>_1.pdf
     CDN 直链，无 Referer/指纹校验，裸 urllib 即可（对照：openstd 国标站按 TLS
     指纹风控、需 curl_cffi——站点穿透三步定性法的实测结论，勿混淆两站策略）。

用法:
    invest-cli report 005827                  列出定期报告（最近 10 期）
    invest-cli report 005827 --latest 4       下载最新 4 期（四季是体检的常用跨度）
    invest-cli report 005827 --year 2025      下载 2025 年发布的全部报告
    invest-cli report 005827 --all            下载全部历史（005827 为 52 期）
    invest-cli report 005827 --out DIR        输出目录（默认 state 目录 reports/<代码>/）

文件名 `{发布日}_{报告全名}.pdf`（非法字符净化），按时间自然排序；PDF 以 %PDF-
头校验，小于 50KB 告警——半截文件比下载失败更危险，宁可让调用方复核。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sources._http import USER_AGENT, guarded_open

KIND = "fund_reports"


def _default_out(code: str) -> Path:
    """默认输出目录：state 目录（~/.config/invest-cli/reports/<代码>/）。

    为什么不再是 `Path.cwd() / "fund_reports"`：CLI 常在仓库目录被调用，
    产物落 CWD 会把几十 MB 的 PDF 堆进 skill 目录（2026-10-25 体检实锤
    1.7M 未跟踪产物）。报告是用户数据，跟 watchlist 一样归 state_root
    （INVEST_CLI_STATE_DIR 可整体覆盖），删缓存不丢报告。
    """
    from _common import state_root

    return state_root() / "reports" / code
_API_HOST = "api.fund.eastmoney.com"
_PDF_HOST = "pdf.dfcfw.com"
_LIST_REFERER = "https://fundf10.eastmoney.com/jjgg_{code}.html"
_MIN_VALID_PDF_BYTES = 50_000
_CODE_RE = re.compile(r"^\d{6}$")
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def fetch_reports(code: str, page_size: int = 50) -> list[dict]:
    """拉定期报告清单（type=3：季报/半年报/年报），返回 [{id, title, date}]，新→旧。

    清单是结构类数据（定期报告以月/季计），与 cn 的公告同一类：5min 缓存，
    重复列出不再重付一次 API 往返（实测 ~200ms/次）。
    """
    ckey = f"list|{code}|{page_size}"
    try:
        from _common import CACHE_TTL_MARKET, cache_get

        hit = cache_get("report", ckey, CACHE_TTL_MARKET)
        if isinstance(hit, list) and hit:
            return hit
    except Exception:  # 缓存不可用不该影响取数
        pass
    url = (f"https://{_API_HOST}/f10/JJGG?fundcode={code}"
           f"&pageIndex=1&pageSize={page_size}&type=3")
    import urllib.request

    req = urllib.request.Request(url, headers={
        "Referer": _LIST_REFERER.format(code=code),
        "User-Agent": USER_AGENT,
    })
    with guarded_open(req, timeout=15, allowed_host=_API_HOST) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    reports = [{"id": it["ID"], "title": it["TITLE"], "date": it["PUBLISHDATEDesc"]}
               for it in (data.get("Data") or []) if it.get("ID")]
    if reports:
        try:
            from _common import cache_set

            cache_set("report", ckey, reports)
        except Exception:
            pass
    return reports


def _is_complete_pdf(path: Path) -> bool:
    """目标文件是否已是一份**完整** PDF（%PDF 头 + 不小于告警阈值）。"""
    try:
        if not path.is_file() or path.stat().st_size < _MIN_VALID_PDF_BYTES:
            return False
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def download_one(item: dict, out_dir: Path) -> dict:
    """下载单份 PDF 到 out_dir，返回该条的落地结果（ok/file/size/warning/error）。

    重跑补齐的前提是**不重下已齐的**：目标已存在且像份完整 PDF 就直接跳过——
    重跑同一命令曾把已成功的全部重新下载，与「可重跑同一命令补齐」的提示
    自相矛盾。头部校验防的是上次留下的半截文件被当成已下载。
    """
    safe_name = _UNSAFE.sub("_", item["title"])
    target = out_dir / f"{item['date']}_{safe_name}.pdf"
    if _is_complete_pdf(target):
        return {**item, "ok": True, "file": str(target),
                "size": target.stat().st_size, "warning": None, "error": None,
                "skipped": True}
    url = f"https://{_PDF_HOST}/pdf/H2_{item['id']}_1.pdf"
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with guarded_open(req, timeout=60, allowed_host=_PDF_HOST) as resp:
            content = resp.read()
    except Exception as e:
        return {**item, "ok": False, "file": None, "size": 0,
                "warning": None, "error": f"{type(e).__name__}: {e}"}
    if content[:5] != b"%PDF-":
        return {**item, "ok": False, "file": None, "size": len(content),
                "warning": None, "error": f"响应非 PDF（{len(content)} 字节）"}
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    warning = None
    if len(content) < _MIN_VALID_PDF_BYTES:
        warning = f"文件仅 {len(content)} 字节，请人工核对是否完整"
    return {**item, "ok": True, "file": str(target), "size": len(content),
            "warning": warning, "error": None}


def _select(reports: list[dict], latest: int, year: int, all_reports: bool) -> list[dict]:
    """按 --latest/--year/--all 圈定下载集合；三者都未给时返回空（仅列出）。"""
    if all_reports:
        return list(reports)
    if year:
        return [r for r in reports if r["date"].startswith(str(year))]
    if latest > 0:
        return reports[:latest]
    return []


def run(code: str, latest: int = 0, year: int = 0, all_reports: bool = False,
        out_dir: str = "", limit: int = 10, as_json: bool = False) -> int:
    code = (code or "").strip()
    if not _CODE_RE.match(code):
        print("错误: 基金代码须为 6 位数字，如 005827", file=sys.stderr)
        return 1
    if latest < 0 or limit < 0:
        print("错误: --latest/--limit 不能为负", file=sys.stderr)
        return 1
    if year and not 1990 <= year <= 2100:
        print("错误: --year 须为合理年份", file=sys.stderr)
        return 1

    # --all/--year 需要全量清单：005827 实测 52 期，pageSize=100 一次拉全；
    # 只列出或 --latest 时 50 期足够（覆盖全部在售基金的定期报告）。
    page_size = 100 if (all_reports or year) else 50
    try:
        reports = fetch_reports(code, page_size=page_size)
    except Exception as e:
        res = {"source": "eastmoney", "kind": KIND, "ok": False, "data": None,
               "error": f"公告清单拉取失败: {type(e).__name__}: {e}"}
        if as_json:
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        else:
            print(res["error"], file=sys.stderr)
        return 1

    selected = _select(reports, latest, year, all_reports)
    dest = Path(out_dir).expanduser() if out_dir else _default_out(code)
    if not selected:
        results = []
    elif len(selected) == 1:
        results = [download_one(selected[0], dest)]
    else:
        # 并发下载：PDF 之间互不依赖，串行时 --all（实测 005827 有 52 期）墙钟
        # 时间 = 各份之和；4 路并发 ≈ 压到 1/4。pool.map 保序，结果与输入对齐。
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as pool:
            results = list(pool.map(lambda it: download_one(it, dest), selected))

    ok_n = sum(1 for r in results if r["ok"])
    data = {
        "fundcode": code,
        "total_reports": len(reports),
        "selected": len(selected),
        "downloaded": ok_n,
        "failed": len(results) - ok_n,
        "out_dir": str(dest) if selected else None,
        "reports": results if selected else reports[:limit],
    }
    ok = not results or ok_n == len(results)
    if as_json:
        print(json.dumps({"source": "eastmoney", "kind": KIND, "ok": ok,
                          "data": data, "error": None if ok else "部分下载失败"},
                         ensure_ascii=False, indent=2, default=str))
        return 0 if ok else 1

    if not selected:
        print(f"  定期报告清单（{code}，共 {len(reports)} 期，显示前 {min(limit, len(reports))} 期）")
        print("  下载示例：invest-cli report " + code + " --latest 4")
        for i, r in enumerate(reports[:limit], 1):
            print(f"  {i}. [{r['date']}] {r['title']}")
        return 0

    print(f"  目标目录：{dest}")
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        line = f"  {mark} [{r['date']}] {r['title']}"
        if r["ok"]:
            line += f" — {r['size']} 字节"
            if r.get("skipped"):
                line += "（已存在，跳过）"
            if r["warning"]:
                line += f"（⚠ {r['warning']}）"
        else:
            line += f" — {r['error']}"
        print(line)
    print(f"  完成：{ok_n}/{len(results)} 成功" + ("（部分失败，可重跑同一命令补齐）" if ok_n < len(results) else ""))
    return 0 if ok else 1


def main() -> None:  # 便于 `python3 cmd_report.py` 直接调试
    import argparse

    p = argparse.ArgumentParser(description="基金定期报告 PDF（东方财富源）")
    p.add_argument("code", help="6 位基金代码，如 005827")
    p.add_argument("--latest", type=int, default=0, help="下载最新 N 期（默认 0=仅列出）")
    p.add_argument("--year", type=int, default=0, help="下载指定年份发布的报告")
    p.add_argument("--all", dest="all_reports", action="store_true", help="下载全部历史")
    p.add_argument("--out", default="", help="输出目录（默认 state 目录 reports/<代码>/）")
    p.add_argument("--limit", type=int, default=10, help="仅列出时的条数（默认 10）")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    sys.exit(run(a.code, latest=a.latest, year=a.year, all_reports=a.all_reports,
                 out_dir=a.out, limit=a.limit, as_json=a.json))


if __name__ == "__main__":
    main()
