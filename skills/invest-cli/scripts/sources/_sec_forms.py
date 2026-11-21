"""SEC EDGAR Form 4 / 13F XML 解析纯函数集（从 sec_edgar.py 拆出）。"""
from __future__ import annotations

from typing import Any, Optional

from ._http import safe_xml_fromstring

_TRANSACTION_LABELS: dict[str, str] = {
    "P": "公开市场买入", "S": "公开市场卖出", "A": "授予（薪酬/激励）",
    "M": "期权行权", "F": "代扣税款（股票交割）", "G": "赠与",
    "C": "衍生品转换", "D": "处置", "E": "到期", "I": "自主计划交易",
    "J": "其他", "K": "权益互换", "L": "小额", "U": "要约收购",
    "W": "继承/遗嘱", "X": "价内行权", "Z": "投票信托",
}
_BUY_CODES = {"P", "A", "M", "C", "X"}
_SELL_CODES = {"S", "F", "D"}


def _direction(code: str) -> str:
    if code in _BUY_CODES:
        return "buy"
    if code in _SELL_CODES:
        return "sell"
    return "other"


def _strip_ns(root: Any) -> None:
    """就地剥掉 XML 命名空间（13F 的 informationTable 带默认命名空间）。"""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(node: Any, path: str) -> str:
    """按相对路径取文本，缺失返回空串。"""
    if node is None:
        return ""
    found = node.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _to_number(text: str) -> Optional[float]:
    if text in ("", None):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_form4(xml_text: str) -> dict[str, Any]:
    """解析一份 Form 4 XML → {owner…, transactions[]}。纯函数，供离线测试。"""
    import xml.etree.ElementTree as ET

    try:
        root = safe_xml_fromstring(xml_text)
    except (ET.ParseError, ValueError) as e:
        raise RuntimeError(f"Form 4 XML 解析失败: {e}") from e
    _strip_ns(root)
    owner = {
        "name": _text(root, "reportingOwner/reportingOwnerId/rptOwnerName"),
        "cik": _text(root, "reportingOwner/reportingOwnerId/rptOwnerCik"),
        "is_officer": _text(root, "reportingOwner/reportingOwnerRelationship/isOfficer") == "true",
        "is_director": _text(root, "reportingOwner/reportingOwnerRelationship/isDirector") == "true",
        "is_ten_pct": _text(root, "reportingOwner/reportingOwnerRelationship/isTenPercentOwner") == "true",
        "title": _text(root, "reportingOwner/reportingOwnerRelationship/officerTitle"),
    }
    role_bits = [b for b, on in (
        ("高管", owner["is_officer"]), ("董事", owner["is_director"]), ("10%以上股东", owner["is_ten_pct"]),
    ) if on]
    owner["role"] = "、".join(role_bits) or "申报人"
    transactions: list[dict[str, Any]] = []
    for tag, is_deriv in (("nonDerivativeTable/nonDerivativeTransaction", False),
                          ("derivativeTable/derivativeTransaction", True)):
        for tx in root.findall(tag):
            code = _text(tx, "transactionCoding/transactionCode")
            security = _text(tx, "securityTitle/value")
            if not security:
                security = _text(tx, "underlyingSecurity/underlyingSecurityTitle/value")
            shares = _text(tx, "transactionAmounts/transactionShares/value")
            price = _text(tx, "transactionAmounts/transactionPricePerShare/value")
            n_shares, n_price = _to_number(shares), _to_number(price)
            transactions.append({
                "date": _text(tx, "transactionDate/value"),
                "code": code,
                "code_label": _TRANSACTION_LABELS.get(code, f"代码 {code}" if code else ""),
                "direction": _direction(code),
                "security": security,
                "shares": n_shares,
                "price": n_price,
                "value": round(n_shares * n_price, 2) if n_shares is not None and n_price is not None else None,
                "shares_after": _to_number(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "ownership": _text(tx, "ownershipNature/directOrIndirectOwnership/value"),
                "is_derivative": is_deriv,
            })
    return {"owner": owner, "transactions": transactions}


def _is_info_table(text: str) -> bool:
    """判断一份 XML 是不是 13F 持仓表。"""
    import xml.etree.ElementTree as ET

    try:
        root = safe_xml_fromstring(text)
        return str(root.tag).split("}")[-1] == "informationTable"
    except (ET.ParseError, ValueError):
        return "informationTable" in text


def _parse_13f_table(xml_text: str) -> list[dict[str, Any]]:
    """解析 13F information table → 持仓行。纯函数，供离线测试。"""
    import xml.etree.ElementTree as ET

    try:
        root = safe_xml_fromstring(xml_text)
    except (ET.ParseError, ValueError) as e:
        raise RuntimeError(f"13F XML 解析失败: {e}") from e
    _strip_ns(root)
    rows: list[dict[str, Any]] = []
    for t in root.findall("infoTable"):
        rows.append({
            "issuer": _text(t, "nameOfIssuer"),
            "class": _text(t, "titleOfClass"),
            "cusip": _text(t, "cusip"),
            "value": _to_number(_text(t, "value")),
            "shares": _to_number(_text(t, "shrsOrPrnAmt/sshPrnamt")),
            "share_type": _text(t, "shrsOrPrnAmt/sshPrnamtType"),
            "put_call": _text(t, "putCall"),
            "discretion": _text(t, "investmentDiscretion"),
        })
    return rows
