#!/usr/bin/env python3
"""SEC EDGAR 适配器回归测试 — 默认不联网（fixture 驱动）；末尾一条联网冒烟。

背景：XBRL 标签会漂移（Apple 的 Revenues 标签停在 2018 财年），
且同一标签下混有季度值。抽取逻辑必须：优先新标签、只取年跨度、时点型取 10-K/FY。
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sources.sec_edgar as sec  # noqa: E402


def _facts_fixture() -> dict:
    """含标签漂移 + 季度噪音 + 时点/时长混合的最小 companyfacts。"""
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2017-10-01", "end": "2018-09-29", "val": 265595000000,
                             "fy": 2018, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 416161000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                            # 季度噪音：同 form/fp 但跨度 90 天，必须被拒
                            {"start": "2025-06-29", "end": "2025-09-27", "val": 102466000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 112010000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 7.39,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2025-09-27", "val": 359241000000, "fy": 2025, "fp": "FY", "form": "10-K"},
                            {"end": "2025-06-28", "val": 331495000000, "fy": 2025, "fp": "Q3", "form": "10-Q"},
                        ]
                    }
                },
            }
        }
    }


def test_extract_prefers_new_tag_and_annual_period() -> None:
    m = sec.extract_annual(_facts_fixture())
    assert m["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert m["revenue"]["value"] == 416161000000  # 不是 2018 旧标签，也不是季度值
    assert m["revenue"]["end"] == "2025-09-27"
    assert m["net_income"]["value"] == 112010000000
    assert m["eps_diluted"]["unit"] == "USD/shares"
    assert m["assets"]["value"] == 359241000000  # 时点型取 10-K/FY，不取 10-Q


def test_cik_padding_and_ticker_norm() -> None:
    assert sec._cik10(320193) == "0000320193"
    assert sec._cik10("0000320193") == "0000320193"
    assert sec._norm_ticker("brk.b") == "BRK-B"
    idx = sec._ticker_index(
        {"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}
    )
    assert idx["BRK-B"]["cik_str"] == 1067983
    assert idx["BRK.B"]["cik_str"] == 1067983  # 点号写法也命中


def test_quarterly_and_foreign_forms_rejected() -> None:
    rows = sec._annual_rows(
        [{"start": "2025-06-29", "end": "2025-09-27", "val": 1, "form": "10-K", "fp": "FY"}]
    )
    assert rows == []
    rows = sec._annual_rows(
        [{"start": "2024-09-29", "end": "2025-09-27", "val": 1, "form": "20-F", "fp": "FY"}]
    )
    assert rows == []


def test_error_envelope_without_network() -> None:
    def _boom(ticker: str):
        raise RuntimeError("SEC 未收录该 ticker: XXX（仅美股发行人）")

    orig = sec.resolve_cik
    sec.resolve_cik = _boom  # type: ignore[assignment]
    try:
        res = sec.fundamentals("XXX")
        assert res["ok"] is False and res["data"] is None
        assert "未收录" in (res["error"] or "")
        assert res["source"] == "sec_edgar"
    finally:
        sec.resolve_cik = orig  # type: ignore[assignment]


def _facts_extended() -> dict:
    """扩展指标 fixture：多年序列 + 季度噪音 + dei + 现金流（FCF 派生用）。"""
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "fy": 2023, "fp": "FY", "form": "10-K"},
                        {"start": "2024-01-01", "end": "2024-12-31", "val": 1200, "fy": 2024, "fp": "FY", "form": "10-K"},
                        {"start": "2025-01-01", "end": "2025-12-31", "val": 1500, "fy": 2025, "fp": "FY", "form": "10-K"},
                        # 季度噪音：不得进年度序列
                        {"start": "2025-10-01", "end": "2025-12-31", "val": 400, "fy": 2025, "fp": "FY", "form": "10-K"},
                    ]}
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [
                        {"start": "2025-01-01", "end": "2025-12-31", "val": 300, "fy": 2025, "fp": "FY", "form": "10-K"},
                    ]}
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {"USD": [
                        {"start": "2025-01-01", "end": "2025-12-31", "val": 100, "fy": 2025, "fp": "FY", "form": "10-K"},
                    ]}
                },
                "Liabilities": {
                    "units": {"USD": [
                        {"end": "2025-12-31", "val": 700, "fy": 2025, "fp": "FY", "form": "10-K"},
                        {"end": "2026-03-31", "val": 750, "fy": 2026, "fp": "Q1", "form": "10-Q"},
                    ]}
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [
                        {"end": "2025-10-31", "val": 900, "fy": 2025, "fp": "FY", "form": "10-K"},
                        {"end": "2026-04-30", "val": 880, "fy": 2026, "fp": "Q1", "form": "10-Q"},
                    ]}
                }
            },
        }
    }


def test_series_multi_year_and_noise_rejected() -> None:
    s = sec.extract_series(_facts_extended(), years=5)
    assert [r["fy"] for r in s["revenue"]] == [2023, 2024, 2025]
    assert [r["value"] for r in s["revenue"]] == [1000, 1200, 1500]
    assert s["revenue"][-1]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_series_derived_fcf_only_when_period_matches() -> None:
    s = sec.extract_series(_facts_extended(), years=5)
    assert s["free_cash_flow"][0]["value"] == 200  # 300 - 100
    assert s["free_cash_flow"][0]["derived"] is True
    # 期间不一致时不得相减：把 capex 换成别的年份，FCF 必须消失
    facts = _facts_extended()
    facts["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"][0]["end"] = "2024-12-31"
    facts["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"][0]["start"] = "2024-01-01"
    s2 = sec.extract_series(facts, years=5)
    assert "free_cash_flow" not in s2


def test_annual_metrics_include_dei_and_derived() -> None:
    m = sec.extract_annual(_facts_extended())
    assert m["shares_outstanding"]["value"] == 880  # 最近一期（10-Q 也能取）
    assert m["shares_outstanding"]["tag"] == "dei:EntityCommonStockSharesOutstanding"
    assert m["liabilities"]["value"] == 700  # 时点型只认 10-K/FY
    assert m["free_cash_flow"]["value"] == 200
    assert m["free_cash_flow"]["tag"] == "derived:operating_cash_flow-capex"


def test_quarterly_flow_derives_q4() -> None:
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1", "form": "10-Q"},
        {"start": "2025-04-01", "end": "2025-06-30", "val": 110, "fy": 2025, "fp": "Q2", "form": "10-Q"},
        {"start": "2025-07-01", "end": "2025-09-30", "val": 120, "fy": 2025, "fp": "Q3", "form": "10-Q"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 500, "fy": 2025, "fp": "FY", "form": "10-K"},
    ]}}}}}
    q = sec.extract_quarterly(facts)
    rows = q["revenue"]
    assert [r["fp"] for r in rows] == ["Q1", "Q2", "Q3", "Q4"]
    assert rows[-1]["value"] == 170  # 500 - (100+110+120)
    assert rows[-1]["derived"] is True and rows[0]["derived"] is False


def test_quarterly_missing_part_does_not_invent_q4() -> None:
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "fy": 2025, "fp": "Q1", "form": "10-Q"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 500, "fy": 2025, "fp": "FY", "form": "10-K"},
    ]}}}}}
    rows = sec.extract_quarterly(facts)["revenue"]
    assert [r["fp"] for r in rows] == ["Q1"], "缺 Q2/Q3 时不得推导 Q4"


def test_fts_quote_multi_word_becomes_phrase() -> None:
    assert sec._fts_quote("supply commitments") == '"supply commitments"'
    assert sec._fts_quote("iPhone") == "iPhone"
    assert sec._fts_quote('"already quoted"') == '"already quoted"'


def test_parse_form4_fixture() -> None:
    xml = """<?xml version="1.0"?>
    <ownershipDocument>
      <reportingOwner>
        <reportingOwnerId><rptOwnerCik>0001</rptOwnerCik><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>true</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <securityTitle><value>Common Stock</value></securityTitle>
          <transactionDate><value>2026-09-01</value></transactionDate>
          <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>25.5</value></transactionPricePerShare>
          </transactionAmounts>
          <postTransactionAmounts><sharesOwnedFollowingTransaction><value>9000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""
    parsed = sec._parse_form4(xml)
    assert parsed["owner"]["name"] == "Doe Jane"
    assert parsed["owner"]["role"] == "高管"
    tx = parsed["transactions"][0]
    assert tx["code"] == "S" and tx["direction"] == "sell"
    assert tx["shares"] == 1000 and tx["price"] == 25.5 and tx["value"] == 25500.0
    assert tx["shares_after"] == 9000 and tx["is_derivative"] is False


def test_parse_13f_table_with_namespace() -> None:
    xml = """<?xml version="1.0"?>
    <ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <ns1:infoTable>
        <ns1:nameOfIssuer>ACME CORP</ns1:nameOfIssuer>
        <ns1:titleOfClass>COM</ns1:titleOfClass>
        <ns1:cusip>000000000</ns1:cusip>
        <ns1:value>1234567</ns1:value>
        <ns1:shrsOrPrnAmt><ns1:sshPrnamt>1000</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
      </ns1:infoTable>
    </ns1:informationTable>"""
    assert sec._is_info_table(xml) is True
    assert sec._is_info_table("<edgarSubmission><formData/></edgarSubmission>") is False
    rows = sec._parse_13f_table(xml)
    assert rows[0]["issuer"] == "ACME CORP" and rows[0]["value"] == 1234567.0 and rows[0]["shares"] == 1000.0


def test_13f_period_normalizes_us_date(monkeypatch) -> None:
    monkeypatch.setattr(sec, "_cached_text",
                        lambda url, ttl_hours: "<periodOfReport>06-30-2026</periodOfReport>")
    assert sec._13f_period("0001", "accn", ["primary_doc.xml"]) == "2026-06-30"
    monkeypatch.setattr(sec, "_cached_text",
                        lambda url, ttl_hours: "<periodOfReport>2025-12-31</periodOfReport>")
    assert sec._13f_period("0001", "accn", ["primary_doc.xml"]) == "2025-12-31"
    assert sec._13f_period("0001", "accn", []) == ""


def test_ticker_ci_family_only_when_unique(monkeypatch) -> None:
    fake = {
        "0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
        "1": {"cik_str": 1067983, "ticker": "BRK-A", "title": "BERKSHIRE HATHAWAY INC"},
        "2": {"cik_str": 111, "ticker": "AA", "title": "ALCOA"},
        "3": {"cik_str": 222, "ticker": "AB", "title": "OTHER"},
    }
    monkeypatch.setattr(sec, "_cached_json", lambda name, url, ttl_hours: fake)
    assert sec._ticker_ci_family("BRK") == ("0001067983", "BERKSHIRE HATHAWAY INC")
    assert sec._ticker_ci_family("A") is None, "多个不同 CIK 的前缀不得当成类别股"


def test_sec_edgar_new_kinds_have_envelopes() -> None:
    """四个新动作的失败路径必须是标准信封（不联网，靠非法输入触发）。"""
    for res, kind in (
        (sec.filing_search("AAPL", ""), "filing_search"),
        (sec.institutional_holdings(""), "institutional_holdings"),
    ):
        assert res["ok"] is False and res["source"] == "sec_edgar"
        assert res["kind"] == kind and res["data"] is None and res["error"]


def test_fundamentals_without_10k_is_error_not_empty_shell(monkeypatch) -> None:
    """20-F 主体（只有 dei 事实）必须明确报错，不得给一个空壳快照 + rc=0。"""
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-04-30", "val": 100, "fy": 2026, "fp": "FY", "form": "20-F"},
    ]}}}}}
    monkeypatch.setattr(sec, "resolve_cik", lambda t: ("0001046179", "TSM"))
    monkeypatch.setattr(sec, "_cached_json", lambda name, url, ttl_hours: facts)
    res = sec.fundamentals("TSM")
    assert res["ok"] is False
    assert "无可用 10-K" in (res["error"] or "")


def test_filing_search_slices_hits_and_pairs_dates(monkeypatch) -> None:
    """接口忽略 size（实测回 100 条）→ 条数只能本地截断；日期必须成对传。"""
    seen = {}

    def _fake_cached(name, url, ttl_hours):
        seen["url"] = url
        return {"hits": {"total": {"value": 100},
                         "hits": [{"_id": f"0000320193-25-000001:d{i}.htm",
                                   "_source": {"form": "10-K", "file_date": "2025-01-01",
                                               "ciks": ["0000320193"]}} for i in range(100)]}}

    monkeypatch.setattr(sec, "resolve_cik", lambda t: ("0000320193", "Apple Inc."))
    monkeypatch.setattr(sec, "_cached_json", _fake_cached)
    monkeypatch.setattr(sec, "_snippet_for", lambda url, terms: None)
    res = sec.filing_search("AAPL", "capacity", from_ym="2025-01", limit=3)
    assert res["ok"] is True
    assert len(res["data"]["results"]) == 3, "size 参数无效，必须本地截断"
    assert "startdt=2025-01-01" in seen["url"] and "enddt=" in seen["url"], "日期必须成对"
    # 只给 --to 时，startdt 也要补齐（否则整个日期条件被忽略）
    res2 = sec.filing_search("AAPL", "capacity", to_ym="2025-12", limit=1)
    assert res2["ok"] is True
    assert "startdt=2001-01-01" in seen["url"] and "enddt=2025-12-31" in seen["url"]


@pytest.mark.live
def test_fundamentals_live_smoke() -> None:
    """联网冒烟：网络不可用/被限流时跳过；解析类错误必须暴露。"""
    try:
        res = sec.fundamentals("AAPL")
    except Exception:
        return
    if not res.get("ok"):
        err = (res.get("error") or "").lower()
        if "请求失败" in (res.get("error") or "") or "timeout" in err or "超时" in err:
            return
        raise AssertionError(res.get("error"))
    m = res["data"]["metrics"]
    assert m["revenue"]["value"] > 0
    assert m["assets"]["value"] > 0


if __name__ == "__main__":
    test_extract_prefers_new_tag_and_annual_period()
    test_cik_padding_and_ticker_norm()
    test_quarterly_and_foreign_forms_rejected()
    test_error_envelope_without_network()
    test_fundamentals_live_smoke()
    print("test_sec_edgar: OK")
