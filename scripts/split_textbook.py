"""
split_textbook.py
用 PyMuPDF 读取教材PDF的书签（目录），按章节拆分成独立PDF文件。

自动模式（推荐）：从PDF书签自动提取章节边界
手动模式：若书签提取失败，可以手动编辑 textbook_chapter_map.json 再运行

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/split_textbook.py                   # 自动模式
    python scripts/split_textbook.py --dry-run         # 只打印书签，不拆分
    python scripts/split_textbook.py --manual          # 从 textbook_chapter_map.json 读取手动配置

输出：
    ocr_pdf/textbook_chapters/<章节名>.pdf
    scripts/textbook_chapter_map.json  （自动生成，可手动修改后用 --manual 重跑）
"""

import argparse
import json
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

BASE = Path(__file__).parent.parent.resolve()
SCRIPTS_DIR = Path(__file__).parent.resolve()

TEXTBOOK_PATH = BASE / "raw" / "textbook" / "信息系统项目管理师教材-第四版.pdf"
OUT_DIR = BASE / "ocr_pdf" / "textbook_chapters"
MAP_FILE = SCRIPTS_DIR / "textbook_chapter_map.json"

# 判断是否是"章节级"书签的关键词（只取第X章，跳过节级别）
CHAPTER_KEYWORDS = ["第", "章"]


def extract_bookmarks(doc) -> list[dict]:
    """提取PDF书签，返回 [{title, page_0indexed}] 列表"""
    toc = doc.get_toc(simple=True)  # [(level, title, page_1indexed), ...]
    bookmarks = []
    for level, title, page in toc:
        bookmarks.append({"level": level, "title": title.strip(), "page": page - 1})
    return bookmarks


def filter_chapter_bookmarks(bookmarks: list[dict]) -> list[dict]:
    """
    从所有书签中筛选出章节级书签（第X章）。
    策略：取 level=1 的书签，若不够则取含"第"和"章"的书签。
    """
    # 优先：level 1 且标题含"章"
    chapters = [b for b in bookmarks if b["level"] == 1 and "章" in b["title"]]
    if len(chapters) >= 10:
        return chapters

    # 备选：所有含"第X章"模式的书签（任意level）
    import re
    pattern = re.compile(r'第[0-9一二三四五六七八九十百]+章')
    chapters = [b for b in bookmarks if pattern.search(b["title"])]
    if chapters:
        return chapters

    # 最后备选：所有 level=1 书签
    chapters = [b for b in bookmarks if b["level"] == 1]
    return chapters


def build_chapter_map(bookmarks: list[dict], total_pages: int) -> list[dict]:
    """为每个章节计算起止页（0-indexed）"""
    chapters = []
    for i, bm in enumerate(bookmarks):
        start = bm["page"]
        end = bookmarks[i + 1]["page"] - 1 if i + 1 < len(bookmarks) else total_pages - 1
        chapters.append({
            "chapter_name": bm["title"],
            "start_page": start,      # 0-indexed
            "end_page": end,          # 0-indexed, inclusive
            "page_count": end - start + 1,
        })
    return chapters


def sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符"""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()


def split_pdf(doc, chapter_map: list[dict], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for ch in chapter_map:
        name = sanitize_filename(ch["chapter_name"])
        out_path = out_dir / f"{name}.pdf"
        if out_path.exists():
            print(f"  [skip] {out_path.name} (已存在)")
            created.append(str(out_path))
            continue
        # 提取页面范围
        start = ch["start_page"]
        end = ch["end_page"]
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start, to_page=end)
        new_doc.save(str(out_path))
        new_doc.close()
        print(f"  [done] {out_path.name}  (p.{start+1}–{end+1}, {ch['page_count']}页)")
        created.append(str(out_path))
    return created


def main():
    parser = argparse.ArgumentParser(description="拆分教材PDF为章节PDF")
    parser.add_argument("--dry-run", action="store_true", help="只打印书签，不拆分")
    parser.add_argument("--manual", action="store_true",
                        help="从 textbook_chapter_map.json 读取手动配置（不自动检测）")
    parser.add_argument("--input", default=str(TEXTBOOK_PATH), help="教材PDF路径")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        # 尝试在 raw/ 里找
        alt = BASE / "raw" / "textbook" / pdf_path.name
        if alt.exists():
            pdf_path = alt
        else:
            print(f"[ERROR] 教材PDF不存在: {pdf_path}")
            print("请先运行 organize_raw.py 将教材复制到 raw/textbook/")
            return

    print(f"打开: {pdf_path.relative_to(BASE)}")
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    print(f"总页数: {total_pages}")

    if args.manual:
        if not MAP_FILE.exists():
            print(f"[ERROR] 手动模式需要先存在 {MAP_FILE}")
            return
        chapter_map = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        print(f"从 {MAP_FILE.name} 加载 {len(chapter_map)} 个章节配置")
    else:
        # 自动模式
        all_bookmarks = extract_bookmarks(doc)
        print(f"\n提取到 {len(all_bookmarks)} 个书签")

        chapter_bms = filter_chapter_bookmarks(all_bookmarks)
        print(f"章节级书签: {len(chapter_bms)} 个")

        if args.dry_run:
            print("\n[书签列表（dry-run，不执行拆分）]")
            for bm in all_bookmarks[:50]:
                marker = "★" if bm in chapter_bms else " "
                print(f"  {marker} L{bm['level']} p.{bm['page']+1:4d}  {bm['title']}")
            if len(all_bookmarks) > 50:
                print(f"  ... 共{len(all_bookmarks)}条，仅显示前50条")
            doc.close()
            return

        if not chapter_bms:
            print("\n[WARN] 未找到章节级书签！")
            print("教材可能没有书签，需要手动编辑 textbook_chapter_map.json")
            print("格式示例:")
            sample = [
                {"chapter_name": "第1章 信息化发展", "start_page": 0, "end_page": 29, "page_count": 30},
                {"chapter_name": "第2章 信息技术发展", "start_page": 30, "end_page": 59, "page_count": 30},
            ]
            print(json.dumps(sample, ensure_ascii=False, indent=2))
            MAP_FILE.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n已创建示例文件: {MAP_FILE.relative_to(BASE)}")
            print("请手动填写正确的页码后运行: python scripts/split_textbook.py --manual")
            doc.close()
            return

        chapter_map = build_chapter_map(chapter_bms, total_pages)

        # 保存章节映射供后续使用
        MAP_FILE.write_text(
            json.dumps(chapter_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n章节映射已保存: {MAP_FILE.relative_to(BASE)}")

    # 打印章节列表
    print(f"\n[章节列表] 共{len(chapter_map)}章")
    for ch in chapter_map:
        print(f"  p.{ch['start_page']+1:4d}–{ch['end_page']+1:4d} ({ch['page_count']:3d}页)  {ch['chapter_name']}")

    # 执行拆分
    print(f"\n输出目录: {OUT_DIR.relative_to(BASE)}")
    created = split_pdf(doc, chapter_map, OUT_DIR)
    doc.close()

    print(f"\n完成！共生成 {len(created)} 个章节PDF")
    print(f"下一步: python scripts/batch_docling.py --input ocr_pdf/textbook_chapters")


if __name__ == "__main__":
    main()
