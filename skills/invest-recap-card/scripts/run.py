#!/usr/bin/env python3
"""run.py — invest-recap-card 一键全流程入口脚本。

用法:
    python3 scripts/run.py [--date today|yesterday|YYYY-MM-DD] [--out-dir DIR] [--open]
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
SCRIPTS_DIR = SKILL_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
from fetch_market import fetch_market_data, get_target_date
from render_card import render_html_to_artifacts


def _esc(value: Any) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def _parse_pct(pct_str: str | None) -> float | None:
    if not pct_str:
        return None
    cleaned = str(pct_str).strip().replace("%", "").replace("+", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_list_items(items: Any) -> str:
    if isinstance(items, str):
        lines = [line.strip() for line in items.splitlines() if line.strip()]
        return "\n      ".join(f"<li>{_esc(line)}</li>" for line in lines)
    if isinstance(items, list):
        out: list[str] = []
        for item in items:
            if isinstance(item, dict):
                label = _esc(item.get("label", ""))
                text = _esc(item.get("text", ""))
                if label:
                    out.append(f"<li><strong>{label}：</strong>{text}</li>")
                else:
                    out.append(f"<li>{text}</li>")
            else:
                out.append(f"<li>{_esc(item)}</li>")
        return "\n      ".join(out)
    return ""


def _classify_session(
    sh_pct: float | None,
    sz_pct: float | None,
    cy_pct: float | None,
    sh_close: float | None,
    sh_high: float | None,
    sh_low: float | None,
) -> tuple[str, str]:
    """根据真实指数涨跌幅与日内位置归类当日盘面特征。"""
    is_pullback = (
        sh_close is not None
        and sh_high is not None
        and sh_low is not None
        and sh_high > sh_low
        and (sh_high - sh_close) > (sh_high - sh_low) * 0.6
        and sh_high - sh_close > 5
    )
    if is_pullback and (sh_pct is None or sh_pct < 0.3):
        return "冲高回落", "盘中冲高遇阻后回落整固，短线追高资金承接偏弱"
    if sh_pct is not None and cy_pct is not None:
        if sh_pct >= 0.6 and cy_pct >= 0.6:
            return "共振走强", "主要指数同步收红，场内风险偏好与承接力度较稳"
        if sh_pct <= -0.6 and cy_pct <= -0.6:
            return "震荡回调", "主要指数集体承压下行，短线防守情绪占优"
        if (sh_pct >= 0 and cy_pct < 0) or (sh_pct < 0 and cy_pct >= 0):
            return "结构分化", "权重与成长风格出现明显分化，资金在板块间轮动"
    if sz_pct is not None and sz_pct < 0 and (sh_pct or 0) >= 0:
        return "沪强深弱", "权重相对稳健而中小盘承压，盘面以结构轮动为主"
    return "窄幅震荡", "指数波动区间有限，场内资金保持存量轮动节奏"


def build_card_html(
    market_data: dict,
    title: str | None = None,
    content_overrides: dict[str, Any] | None = None,
) -> str:
    template_path = TEMPLATES_DIR / "card_template.html"
    template_str = template_path.read_text(encoding="utf-8")
    overrides = content_overrides or {}

    dt_str = str(market_data["date"])
    weekday = str(market_data["weekday"])
    is_today = bool(market_data.get("is_today"))
    sh = market_data.get("sh_index") or {}
    sz = market_data.get("sz_index") or {}
    cy = market_data.get("cy_index") or {}
    turnover = market_data.get("turnover_total") or "待补充"

    sh_close = sh.get("close")
    sh_high = sh.get("high")
    sh_low = sh.get("low")
    cy_close = cy.get("close")
    sh_pct_str = sh.get("change_pct") or "--"
    sz_pct_str = sz.get("change_pct") or "--"
    cy_pct_str = cy.get("change_pct") or "--"

    sh_pct = _parse_pct(sh.get("change_pct"))
    sz_pct = _parse_pct(sz.get("change_pct"))
    cy_pct = _parse_pct(cy.get("change_pct"))
    regime_tag, regime_note = _classify_session(sh_pct, sz_pct, cy_pct, sh_close, sh_high, sh_low)

    mm_dd = ".".join(dt_str.split("-")[1:3]) if len(dt_str.split("-")) == 3 else dt_str

    raw_title = title or overrides.get("title") or f"{weekday}复盘：{regime_tag}，节奏比方向更重要"
    eyebrow = overrides.get("eyebrow") or f"{weekday}收盘复盘 · 策略观察"
    subtitle = overrides.get("subtitle") or f"{weekday}（{mm_dd}）{regime_note}"
    time_str = overrides.get("time_str") or ("盘中跟踪" if is_today else "盘后复盘")

    # 指标卡
    m1_val = f"{sh_close:.2f}" if sh_close is not None else "--"
    m1_lbl = f"上证指数 ({_esc(weekday)} {_esc(sh_pct_str)})"

    m2_val = f"{cy_close:.2f}" if cy_close is not None else "--"
    m2_lbl = f"创业板指 ({_esc(weekday)} {_esc(cy_pct_str)})"

    m3_val = _esc(turnover)
    m3_lbl = "两市成交额 (沪深合计)"

    if sh_high is not None and sh_low is not None:
        m4_val = f"{sh_low:.0f}-{sh_high:.0f}"
        m4_lbl = f"{_esc(weekday)}上证日内高低区间"
    elif sh_high is not None:
        m4_val = f"{sh_high:.0f}"
        m4_lbl = f"{_esc(weekday)}上证盘中高点"
    else:
        m4_val = "--"
        m4_lbl = f"{_esc(weekday)}上证波动区间"

    # 导语：完全由真实行情字段拼接
    if overrides.get("lead"):
        lead = _esc(overrides["lead"])
    else:
        range_part = (
            f"盘中上证波动于 {sh_low:.2f}–{sh_high:.2f} 区间；"
            if sh_high is not None and sh_low is not None
            else (f"盘中上证最高触及 {sh_high:.2f}；" if sh_high is not None else "")
        )
        turnover_part = (
            f'两市合计成交额 <span class="hl">{_esc(turnover)}</span>。'
            if turnover != "待补充"
            else "两市合计成交额数据待补充。"
        )
        lead = (
            f"{_esc(weekday)}（{_esc(mm_dd)}）A股整体呈现「{_esc(regime_tag)}」走势。"
            f'上证指数收报 <span class="hl">{_esc(m1_val)}</span>（{_esc(sh_pct_str)}），'
            f"深证成指 {_esc(sz_pct_str)}，创业板指收报 {_esc(m2_val)}（{_esc(cy_pct_str)}）。"
            f"{range_part}{turnover_part}"
        )

    # 两栏内容（可根据自定义 JSON 覆盖，否则按当期真实盘面生成）
    col1_title = overrides.get("col1_title") or f"{weekday}盘面拆解"
    default_col1 = [
        {"label": "指数表现", "text": f"上证 {sh_pct_str}、深证 {sz_pct_str}、创业板 {cy_pct_str}，日内呈现{regime_tag}特征。"},
        {"label": "日内振幅", "text": f"上证波动区间 {m4_val}，高位与低位之间的承接力度决定短线强弱边界。"},
        {"label": "量能信号", "text": f"两市成交额 {turnover}，量价配合程度直接决定后续反弹或突破的持续性。"},
    ]
    col1_items = _format_list_items(overrides.get("col1_items") or default_col1)

    col2_title = overrides.get("col2_title") or "观察重点与纪律"
    default_col2 = [
        {"label": "关注承接强度", "text": f"围绕上证 {m4_val} 区间观察资金承接情况，不凭单根日内K线情绪化追涨杀跌。"},
        {"label": "区分风格强弱", "text": "对比主板与成长板块的强弱切换，优先顺应量能有持续跟随的主线方向。"},
        {"label": "控制节奏仓位", "text": "在量能未出现明确趋势放大前保持仓位弹性，留足回旋余地等待确认信号。"},
    ]
    col2_items = _format_list_items(overrides.get("col2_items") or default_col2)

    callout_title = overrides.get("callout_title") or f"策略应对：{regime_tag}市况下的操作纪律"
    callout_content = overrides.get("callout_content") or (
        f"当前上证报 {m1_val}（{sh_pct_str}），创业板报 {m2_val}（{cy_pct_str}），两市成交 {turnover}。"
        "操作上坚持不追高脉冲、不恐慌杀跌的原则，重点跟踪日内高低点与量能变化，"
        "等关键支撑企稳或主线放量确认后再择机加减仓。"
    )
    wish_text = overrides.get("wish_text") or "理性复盘，严守纪律。"
    description = overrides.get("description") or f"{dt_str} {weekday} A股复盘：上证 {m1_val}（{sh_pct_str}），成交 {turnover}。"

    replacements = {
        "{{TITLE}}": _esc(raw_title),
        "{{DESCRIPTION}}": _esc(description),
        "{{EYEBROW}}": _esc(eyebrow),
        "{{SUBTITLE}}": _esc(subtitle),
        "{{DATE_STR}}": _esc(f"{dt_str} ({weekday})"),
        "{{TIME_STR}}": _esc(time_str),
        "{{METRIC_1_VAL}}": _esc(m1_val),
        "{{METRIC_1_LBL}}": m1_lbl,
        "{{METRIC_2_VAL}}": _esc(m2_val),
        "{{METRIC_2_LBL}}": m2_lbl,
        "{{METRIC_3_VAL}}": m3_val,
        "{{METRIC_3_LBL}}": _esc(m3_lbl),
        "{{METRIC_4_VAL}}": _esc(m4_val),
        "{{METRIC_4_LBL}}": m4_lbl,
        "{{LEAD_CONTENT}}": lead,
        "{{COL1_TITLE}}": _esc(col1_title),
        "{{COL1_ITEMS}}": col1_items,
        "{{COL2_TITLE}}": _esc(col2_title),
        "{{COL2_ITEMS}}": col2_items,
        "{{CALLOUT_TITLE}}": _esc(callout_title),
        "{{CALLOUT_CONTENT}}": _esc(callout_content),
        "{{WISH_TEXT}}": _esc(wish_text),
    }

    html_out = template_str
    for k, v in replacements.items():
        html_out = html_out.replace(k, v)

    return html_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Kami investment recap card image")
    parser.add_argument("--date", default="today", help="today | yesterday | YYYY-MM-DD")
    parser.add_argument("--title", help="Custom card title")
    parser.add_argument("--content-json", help="Optional JSON file overriding narrative/list fields")
    parser.add_argument("--out-dir", default=str(Path.cwd() / "tmp"), help="Output directory")
    parser.add_argument("--open", dest="auto_open", action="store_true", default=False, help="Open generated image in macOS viewer")
    parser.add_argument("--no-open", dest="auto_open", action="store_false", help="Do not open automatically")
    args = parser.parse_args()

    content_overrides: dict[str, Any] = {}
    if args.content_json:
        content_path = Path(args.content_json).expanduser().resolve()
        content_overrides = json.loads(content_path.read_text(encoding="utf-8"))
        if not isinstance(content_overrides, dict):
            print("[!] --content-json 顶层必须是 JSON 对象", file=sys.stderr)
            sys.exit(2)

    target_dt = get_target_date(args.date)
    print(f"[*] 正在获取 {target_dt} ({args.date}) 市场行情数据...")
    market = fetch_market_data(target_dt)
    if market["sh_index"].get("close") is None:
        err = market.get("fetch_error") or "未获取到有效上证指数行情"
        print(f"[!] 行情取数失败，拒绝渲染空/假卡片: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 正在灌装 Kami 单页排版模板...")
    filled_html = build_card_html(market, title=args.title, content_overrides=content_overrides)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    date_tag = target_dt.strftime("%Y%m%d")
    html_file = out_dir / f"recap_card_{date_tag}.html"
    pdf_file = out_dir / f"recap_card_{date_tag}.pdf"
    png_file = out_dir / f"recap_card_{date_tag}.png"

    html_file.write_text(filled_html, encoding="utf-8")
    print(f"[*] 已生成 HTML: {html_file}")

    print(f"[*] 正在调用 WeasyPrint + PyMuPDF 渲染高清单页图片...")
    ok = render_html_to_artifacts(html_file, pdf_file, png_file, dpi=200)
    if not ok:
        print("[!] 渲染失败", file=sys.stderr)
        sys.exit(1)

    print(f"[+] 渲染成功！图片路径: {png_file}")

    if args.auto_open and sys.platform == "darwin":
        print("[*] 正在调用 macOS 预览打开图片...")
        subprocess.run(["open", str(png_file)], check=False)


if __name__ == "__main__":
    main()
