#!/usr/bin/env python3
"""fetch_market.py — 为复盘卡片拉取结构化市场行情。

优先调用本机已装的 invest-cli，自动识别交易日并拉取大盘核心数据。
绝不静默返回写死的假数据；取数失败时保留 None 并写明 fetch_error。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _cli_prefix() -> list[str] | None:
    env_bin = os.environ.get("INVEST_CLI_BIN", "").strip()
    if env_bin:
        p = Path(env_bin).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return [str(p)]
    candidate = shutil.which("invest-cli")
    if candidate:
        return [candidate]
    local_path = Path.home() / ".local" / "bin" / "invest-cli"
    if local_path.is_file() and os.access(local_path, os.X_OK):
        return [str(local_path)]
    cli_root = Path(__file__).resolve().parents[2] / "invest-cli"
    cli_script = cli_root / "scripts" / "invest_cli.py"
    if cli_script.is_file():
        venv_py = cli_root / ".venv" / "bin" / "python"
        py_bin = str(venv_py) if venv_py.is_file() and os.access(venv_py, os.X_OK) else sys.executable
        return [py_bin, str(cli_script)]
    return None


def find_invest_cli() -> str | None:
    prefix = _cli_prefix()
    return prefix[0] if prefix else None


def get_target_date(target_spec: str) -> datetime.date:
    today = datetime.date.today()
    if target_spec in ("today", "current"):
        return today
    if target_spec == "yesterday":
        if today.weekday() == 0:
            return today - datetime.timedelta(days=3)
        if today.weekday() == 6:
            return today - datetime.timedelta(days=2)
        return today - datetime.timedelta(days=1)
    try:
        return datetime.datetime.strptime(target_spec, "%Y-%m-%d").date()
    except ValueError:
        return today


def _unwrap_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        rows = data.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _unwrap_quotes(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [q for q in payload if isinstance(q, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        quotes = data.get("quotes")
        if isinstance(quotes, list):
            return [q for q in quotes if isinstance(q, dict)]
    return []


def _fmt_pct(val: Any) -> str | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return f"{val:+.2f}%"
    s = str(val).strip()
    return s if s.endswith("%") else f"{s}%"


def _fetch_kline_bar(prefix: list[str], symbol: str, target_str: str) -> dict | None:
    res = subprocess.run(
        [*prefix, "kline", symbol, "--period", "day", "--limit", "15", "--json"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if res.returncode != 0:
        return None
    rows = _unwrap_rows(json.loads(res.stdout))
    for idx, item in enumerate(rows):
        row_date = str(item.get("date") or item.get("time") or "")
        if row_date == target_str or row_date.startswith(target_str):
            bar = dict(item)
            if idx > 0 and rows[idx - 1].get("close") and item.get("close") is not None:
                prev_close = float(rows[idx - 1]["close"])
                close_p = float(item["close"])
                if prev_close > 0:
                    bar["change"] = round(close_p - prev_close, 2)
                    bar["change_pct"] = round((close_p - prev_close) / prev_close * 100, 2)
            return bar
    return None


def fetch_market_data(target_date: datetime.date) -> dict:
    cli_prefix = _cli_prefix()
    today = datetime.date.today()
    is_today = target_date == today
    weekday_map = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}

    data: dict[str, Any] = {
        "date": target_date.strftime("%Y-%m-%d"),
        "weekday": weekday_map[target_date.weekday()],
        "is_today": is_today,
        "sh_index": {"close": None, "change": None, "change_pct": None, "high": None, "low": None},
        "sz_index": {"close": None, "change_pct": None},
        "cy_index": {"close": None, "change_pct": None},
        "turnover_total": None,
        "resistance": None,
        "up_count": None,
        "down_count": None,
    }

    if not cli_prefix:
        data["fetch_error"] = "invest-cli 未安装或不可执行"
        return data

    errors: list[str] = []
    target_str = target_date.strftime("%Y-%m-%d")

    try:
        # 1. 拉取对应交易日 K 线（历史日期覆盖三大指数，当日补齐上证高低点）
        kline_targets = [("sh000001", "sh_index")] if is_today else [
            ("sh000001", "sh_index"),
            ("sz399001", "sz_index"),
            ("sz399006", "cy_index"),
        ]
        for sym, key in kline_targets:
            try:
                bar = _fetch_kline_bar(cli_prefix, sym, target_str)
                if bar:
                    if bar.get("close") is not None:
                        data[key]["close"] = float(bar["close"])
                    if bar.get("change_pct") is not None:
                        data[key]["change_pct"] = _fmt_pct(bar["change_pct"])
                    if key == "sh_index":
                        if bar.get("high") is not None:
                            data["sh_index"]["high"] = float(bar["high"])
                        if bar.get("low") is not None:
                            data["sh_index"]["low"] = float(bar["low"])
                        if bar.get("change") is not None:
                            data["sh_index"]["change"] = float(bar["change"])
            except Exception as exc:
                errors.append(f"kline({sym}): {exc}")

        # 2. 当日通过 quote 实时获取三大指数及成交额
        if is_today:
            res = subprocess.run(
                [*cli_prefix, "quote", "sh000001,sz399001,sz399006", "--json"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if res.returncode == 0:
                try:
                    quotes = _unwrap_quotes(json.loads(res.stdout))
                    sh_amt, sz_amt = None, None
                    for item in quotes:
                        code = item.get("symbol") or item.get("code")
                        price = item.get("price")
                        pct = _fmt_pct(item.get("change_pct") if item.get("change_pct") is not None else item.get("change_percent"))
                        if code == "sh000001":
                            if price is not None:
                                data["sh_index"]["close"] = float(price)
                            if item.get("change") is not None:
                                data["sh_index"]["change"] = float(item["change"])
                            if pct is not None:
                                data["sh_index"]["change_pct"] = pct
                            if item.get("high") is not None:
                                data["sh_index"]["high"] = float(item["high"])
                            if item.get("low") is not None:
                                data["sh_index"]["low"] = float(item["low"])
                            if isinstance(item.get("amount"), (int, float)):
                                sh_amt = float(item["amount"])
                        elif code == "sz399001":
                            if price is not None:
                                data["sz_index"]["close"] = float(price)
                            if pct is not None:
                                data["sz_index"]["change_pct"] = pct
                            if isinstance(item.get("amount"), (int, float)):
                                sz_amt = float(item["amount"])
                        elif code == "sz399006":
                            if price is not None:
                                data["cy_index"]["close"] = float(price)
                            if pct is not None:
                                data["cy_index"]["change_pct"] = pct
                    if sh_amt is not None and sz_amt is not None and (sh_amt + sz_amt) > 0:
                        data["turnover_total"] = f"{(sh_amt + sz_amt) / 1e12:.2f} 万亿"
                except Exception as exc:
                    errors.append(f"quote parse: {exc}")
            else:
                errors.append(f"quote rc={res.returncode}: {(res.stderr or '').strip()}")

        # 3. 当日尝试从 westock 获取市场概览（历史日期不混用当日概览）
        if is_today:
            res_ov = subprocess.run(
                [*cli_prefix, "westock", "market-overview"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if res_ov.returncode == 0 and "两市成交额" in res_ov.stdout:
                for line in res_ov.stdout.splitlines():
                    if "两市成交额" in line and "：" in line:
                        data["turnover_total"] = line.split("：", 1)[1].split("（")[0].strip()
                        break
    except Exception as exc:
        errors.append(str(exc))

    if errors:
        data["fetch_error"] = "; ".join(errors)

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch structured market data for recap card")
    parser.add_argument("--date", default="today", help="today | yesterday | YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Output JSON directly")
    args = parser.parse_args()

    target_date = get_target_date(args.date)
    market = fetch_market_data(target_date)

    if args.json:
        print(json.dumps(market, ensure_ascii=False, indent=2))
    else:
        sh_close = market["sh_index"].get("close")
        cy_close = market["cy_index"].get("close")
        print(f"日期: {market['date']} ({market['weekday']})")
        print(f"上证: {sh_close if sh_close is not None else '--'} ({market['sh_index'].get('change_pct') or '--'})")
        print(f"创业板: {cy_close if cy_close is not None else '--'} ({market['cy_index'].get('change_pct') or '--'})")
        print(f"量能: {market.get('turnover_total') or '--'}")
        if market.get("fetch_error"):
            print(f"警告: {market['fetch_error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
