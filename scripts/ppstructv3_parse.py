"""
ppstructv3_parse.py
使用 PaddleOCR PP-StructureV3 解析 PDF 为 Markdown（含 LaTeX 公式）。
策略：逐页渲染为 PNG → 喂给 PP-StructureV3，避免整 PDF 传入导致耗时过长。
需要在安装了 paddleocr>=3.0 + paddlepaddle-gpu + pymupdf 的环境中运行。

用法：
    python scripts/ppstructv3_parse.py --input raw/lectures/calc_ppts --test 1
    python scripts/ppstructv3_parse.py --input raw/lectures/calc_ppts          # 全量
    python scripts/ppstructv3_parse.py --input raw/lectures/chapter_ppts       # 章节PPT
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import fitz  # pymupdf

# 跳过模型源检查，加速启动
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

BASE = Path(__file__).parent.parent.resolve()
OUTPUT_DIR = BASE / "ppstructv3_out"

# LaTeX 后处理：清理 PP-FormulaNet 常见冗余空格
_RE_LATEX_EXTRA_SPACES = re.compile(r'\{\\[\s\\]+\}')
_RE_LATEX_SUBSCRIPT_SPACES = re.compile(r'_\{(?:\\[ ]+)+\}')


def clean_latex(md_text: str) -> str:
    """清理 PP-FormulaNet 输出中常见的 LaTeX 冗余空格。"""
    md_text = _RE_LATEX_EXTRA_SPACES.sub('{}', md_text)
    md_text = _RE_LATEX_SUBSCRIPT_SPACES.sub('_{}', md_text)
    # 清理 \, \; \  等多余间距命令
    md_text = re.sub(r'\\[,;!]\s*', ' ', md_text)
    return md_text


def parse_one_pdf(pipeline, pdf_path: Path, out_dir: Path, dpi: int = 200) -> dict:
    """逐页渲染 PDF 为图片，再用 PP-StructureV3 解析每页。"""
    stem = pdf_path.stem
    md_out = out_dir / "markdown" / f"{stem}.md"
    img_out = out_dir / "images" / stem
    md_out.parent.mkdir(parents=True, exist_ok=True)
    img_out.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"PDF: {pdf_path.name}")

    t0 = time.time()
    try:
        doc = fitz.open(str(pdf_path))
        total_pages = doc.page_count
        print(f"  共 {total_pages} 页，dpi={dpi}")

        all_page_md = []
        page_times = []

        for page_idx in range(total_pages):
            # 渲染页面为 PNG
            pix = doc[page_idx].get_pixmap(dpi=dpi)
            tmp_img = img_out / f"p{page_idx:03d}.png"
            pix.save(str(tmp_img))

            # PP-StructureV3 处理
            pt0 = time.time()
            page_md = ""
            for res in pipeline.predict(str(tmp_img)):
                md_dict = res.markdown if hasattr(res, 'markdown') else {}
                if isinstance(md_dict, dict):
                    # 只取 markdown_texts，忽略 input_path / markdown_images 等
                    page_md = md_dict.get("markdown_texts", "")
                    if not isinstance(page_md, str):
                        page_md = str(page_md)
                elif isinstance(md_dict, str):
                    page_md = md_dict
                else:
                    page_md = str(md_dict)

            # 清理 LaTeX
            page_md = clean_latex(page_md)

            pt_elapsed = time.time() - pt0
            page_times.append(pt_elapsed)
            status_char = "." if page_md.strip() else "x"
            print(f"  [{page_idx+1:3d}/{total_pages}] {pt_elapsed:5.1f}s {status_char}", end="", flush=True)
            if (page_idx + 1) % 10 == 0:
                print()

            all_page_md.append(f"<!-- page {page_idx + 1} -->\n\n{page_md}")

        doc.close()
        print()

        # 合并所有页面
        full_md = "\n\n---\n\n".join(all_page_md)
        md_out.write_text(full_md, encoding="utf-8")

        elapsed = time.time() - t0
        avg_page = sum(page_times) / len(page_times) if page_times else 0
        print(f"  完成: {total_pages}页, 总耗时 {elapsed:.0f}s, 平均 {avg_page:.1f}s/页")
        return {
            "file": pdf_path.name, "status": "ok",
            "pages": total_pages, "time": round(elapsed, 1),
            "avg_page_time": round(avg_page, 1),
        }

    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n  ERROR ({elapsed:.1f}s): {e}")
        import traceback; traceback.print_exc()
        return {"file": pdf_path.name, "status": "error", "error": str(e)[:300], "time": round(elapsed, 1)}


def main():
    parser = argparse.ArgumentParser(description="PP-StructureV3 解析 PDF → Markdown (含 LaTeX 公式)")
    parser.add_argument("--input", required=True, help="PDF 目录（相对于项目根）")
    parser.add_argument("--output", default=None, help="输出目录（默认 ppstructv3_out）")
    parser.add_argument("--test", type=int, default=0, help="只处理前 N 个文件（0=全部）")
    parser.add_argument("--dpi", type=int, default=200, help="页面渲染 DPI（默认 200）")
    parser.add_argument("--formula-model", default="PP-FormulaNet-L",
                        help="公式识别模型 (PP-FormulaNet-L / PP-FormulaNet-S)")
    parser.add_argument("--no-chart", action="store_true", help="关闭图表识别（省 VRAM）")
    args = parser.parse_args()

    input_dir = BASE / args.input
    if not input_dir.exists():
        print(f"[ERROR] 目录不存在: {input_dir}")
        sys.exit(1)

    out_dir = Path(args.output) if args.output else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(input_dir.rglob("*.pdf"))
    if not pdfs:
        print(f"[WARN] {input_dir} 下没有 PDF 文件")
        sys.exit(1)

    if args.test > 0:
        pdfs = pdfs[:args.test]

    print(f"输入: {input_dir.relative_to(BASE)}")
    print(f"输出: {out_dir}")
    print(f"PDF 数量: {len(pdfs)}")
    print(f"DPI: {args.dpi}")
    print(f"公式模型: {args.formula_model}")
    print(f"图表识别: {'关闭' if args.no_chart else '开启'}")
    print()

    print("初始化 PP-StructureV3 ...", flush=True)
    from paddleocr import PPStructureV3

    pipeline_kwargs = {
        "formula_recognition_model_name": args.formula_model,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
    }
    if args.no_chart:
        pipeline_kwargs["use_chart_recognition"] = False

    pipeline = PPStructureV3(**pipeline_kwargs)
    print("PP-StructureV3 就绪\n")

    results = []
    ok = err = 0
    total_pages = 0
    for pdf in pdfs:
        r = parse_one_pdf(pipeline, pdf, out_dir, dpi=args.dpi)
        results.append(r)
        if r["status"] == "ok":
            ok += 1
            total_pages += r.get("pages", 0)
        else:
            err += 1

    # 保存日志
    log_file = out_dir / f"parse_log_{int(time.time())}.json"
    log_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"完成: PDF {ok}/{ok+err} 成功, 共 {total_pages} 页")
    print(f"日志: {log_file}")
    print(f"Markdown 输出: {out_dir / 'markdown'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
