"""
check_ocr_need.py
检查 raw/ 目录下每个PDF是否需要OCR处理。
判断标准：提取前5页文本，若中文字符数 < 50 则认为需要OCR。

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/check_ocr_need.py
    python scripts/check_ocr_need.py --dir raw/past_papers   # 只检查某个子目录

输出：
    屏幕打印报告 + 写入 scripts/ocr_status.json
"""

import argparse
import json
import re
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 的新包名
except ImportError:
    import fitz  # 旧包名 fallback

BASE = Path(__file__).parent.parent.resolve()
SCRIPTS_DIR = Path(__file__).parent.resolve()
STATUS_FILE = SCRIPTS_DIR / "ocr_status.json"

CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff]')
SAMPLE_PAGES = 5        # 抽取前N页
CN_CHAR_THRESHOLD = 50  # 中文字符数低于此值 → 需要OCR


def check_pdf(pdf_path: Path) -> dict:
    result = {
        "path": str(pdf_path.relative_to(BASE)),
        "pages": 0,
        "sampled_pages": 0,
        "cn_char_count": 0,
        "needs_ocr": False,
        "error": None,
    }
    try:
        doc = fitz.open(str(pdf_path))
        result["pages"] = len(doc)
        pages_to_check = min(SAMPLE_PAGES, len(doc))
        result["sampled_pages"] = pages_to_check
        total_cn = 0
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text("text")
            total_cn += len(CHINESE_PATTERN.findall(text))
        result["cn_char_count"] = total_cn
        result["needs_ocr"] = total_cn < CN_CHAR_THRESHOLD
        doc.close()
    except Exception as e:
        result["error"] = str(e)
        result["needs_ocr"] = True  # 无法读取 → 保守处理，标为需要OCR
    return result


def main():
    parser = argparse.ArgumentParser(description="检查PDF是否需要OCR")
    parser.add_argument("--dir", default="raw", help="要扫描的目录（相对于项目根）")
    parser.add_argument("--threshold", type=int, default=CN_CHAR_THRESHOLD,
                        help=f"中文字符阈值（默认{CN_CHAR_THRESHOLD}）")
    args = parser.parse_args()

    scan_dir = BASE / args.dir
    if not scan_dir.exists():
        print(f"[ERROR] 目录不存在: {scan_dir}")
        return

    pdfs = sorted(scan_dir.rglob("*.pdf"))
    if not pdfs:
        print(f"[WARN] {scan_dir} 下没有找到PDF文件")
        return

    print(f"扫描目录: {scan_dir.relative_to(BASE)}")
    print(f"找到 {len(pdfs)} 个PDF文件，每文件抽查前{SAMPLE_PAGES}页，阈值={args.threshold}中文字符\n")

    results = []
    needs_ocr_list = []
    ok_list = []

    for pdf in pdfs:
        r = check_pdf(pdf)
        r["threshold"] = args.threshold
        r["needs_ocr"] = r["cn_char_count"] < args.threshold
        results.append(r)
        if r["needs_ocr"]:
            needs_ocr_list.append(r)
        else:
            ok_list.append(r)

    # 保存 JSON
    STATUS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"结果已保存到: {STATUS_FILE.relative_to(BASE)}\n")

    # 打印摘要
    print("=" * 60)
    print(f"总计: {len(results)} 个文件")
    print(f"  无需OCR: {len(ok_list)} 个")
    print(f"  需要OCR: {len(needs_ocr_list)} 个")
    print("=" * 60)

    if needs_ocr_list:
        print("\n[需要OCR的文件]")
        for r in needs_ocr_list:
            err = f" (ERROR: {r['error']})" if r["error"] else ""
            print(f"  ⚠ {r['path']}  中文字符={r['cn_char_count']}{err}")

    print("\n[无需OCR的文件（前20条）]")
    for r in ok_list[:20]:
        print(f"  ✓ {r['path']}  中文字符={r['cn_char_count']}, 页数={r['pages']}")
    if len(ok_list) > 20:
        print(f"  ... 共{len(ok_list)}个，详见 ocr_status.json")


if __name__ == "__main__":
    main()
