#!/usr/bin/env python3
"""render_card.py — 将 HTML 单页卡片通过 WeasyPrint 与 PyMuPDF 导出为高清晰度 PNG 与 PDF。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# 确保在 macOS 下动态库能正常被 cffi / WeasyPrint 找到
if sys.platform == "darwin" and Path("/opt/homebrew/lib").is_dir():
    current_dyld = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if "/opt/homebrew/lib" not in current_dyld:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"/opt/homebrew/lib:{current_dyld}".rstrip(":")


def _resolve_render_python() -> str:
    env_py = os.environ.get("KAMI_PYTHON", "").strip()
    if env_py:
        p = Path(env_py).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    kami_python = Path.home() / ".agents" / "skills" / "kami" / ".venv" / "bin" / "python"
    if kami_python.is_file() and os.access(kami_python, os.X_OK):
        return str(kami_python)
    return sys.executable


def render_html_to_artifacts(html_file: Path, pdf_out: Path, png_out: Path, dpi: int = 200) -> bool:
    # 路径与 dpi 通过 sys.argv 传入，避免字符串插值带来的引号转义与注入隐患
    script_code = """
import sys
import fitz
from weasyprint import HTML

html_p, pdf_p, png_p, dpi = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
HTML(filename=html_p).write_pdf(pdf_p)
doc = fitz.open(pdf_p)
if len(doc) > 0:
    pix = doc[0].get_pixmap(dpi=dpi)
    pix.save(png_p)
print(f"OK: Rendered {len(doc)} page(s)")
"""

    python_bin = _resolve_render_python()
    env = os.environ.copy()
    if sys.platform == "darwin" and Path("/opt/homebrew/lib").is_dir():
        cur = env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if "/opt/homebrew/lib" not in cur:
            env["DYLD_FALLBACK_LIBRARY_PATH"] = f"/opt/homebrew/lib:{cur}".rstrip(":")

    res = subprocess.run(
        [python_bin, "-c", script_code, str(html_file.resolve()), str(pdf_out.resolve()), str(png_out.resolve()), str(int(dpi))],
        capture_output=True, text=True, env=env, check=False,
    )
    if res.returncode != 0:
        print(f"ERROR during render: {res.stderr}", file=sys.stderr)
        return False

    print(f"PDF generated: {pdf_out}")
    print(f"PNG generated: {png_out}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Render HTML to PDF and PNG image")
    parser.add_argument("html_file", help="Path to input HTML file")
    parser.add_argument("--pdf-out", help="Output PDF path")
    parser.add_argument("--png-out", help="Output PNG path")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for raster image (default 200)")
    parser.add_argument("--open", action="store_true", help="Open generated image in default viewer")
    args = parser.parse_args()

    html_p = Path(args.html_file).resolve()
    if not html_p.exists():
        print(f"File not found: {html_p}", file=sys.stderr)
        sys.exit(1)

    pdf_p = Path(args.pdf_out).resolve() if args.pdf_out else html_p.with_suffix(".pdf")
    png_p = Path(args.png_out).resolve() if args.png_out else html_p.with_suffix(".png")

    ok = render_html_to_artifacts(html_p, pdf_p, png_p, dpi=args.dpi)
    if not ok:
        sys.exit(2)

    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(png_p)], check=False)


if __name__ == "__main__":
    main()
