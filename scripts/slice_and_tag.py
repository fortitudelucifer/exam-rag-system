"""
slice_and_tag.py
将 Docling 输出的 Markdown 按标题层级切片，并为每个切片添加 YAML front matter 元数据。
切片后的文件输出到 ragflow_upload/<domain>/ 目录，可直接上传到 RAGFlow。

切片策略：
  - 教材/辅导书/PPT：按 H2 切分（一个"节"一个chunk），保留完整语境
  - 真题：按题目正则切分（【单选题】、第X题）
  - 每个切片最小字符数：MIN_CHUNK_CHARS（默认80），过小的合并到上一个

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/slice_and_tag.py --input docling_out/markdown_cleaned --use-map --force --clean
    python scripts/slice_and_tag.py --input docling_out/markdown_cleaned --domain kb_schedule
    python scripts/slice_and_tag.py --input docling_out/markdown_cleaned --use-map

输出：
    ragflow_upload/<domain>/<source_stem>__<idx>_<slug>.md
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

try:
    import yaml
except ImportError:
    import json as yaml  # fallback

BASE = Path(__file__).parent.parent.resolve()
SCRIPTS_DIR = Path(__file__).parent.resolve()
DOMAIN_MAP_FILE = SCRIPTS_DIR / "chapter_domain_map.json"
RAGFLOW_UPLOAD = BASE / "ragflow_upload"

MIN_CHUNK_CHARS = 80  # 低于此字符数的chunk合并到上一个
MAX_CHUNK_CHARS = 8000  # 超过此字符数的chunk警告（RAGFlow建议chunk不超过10k）


def load_domain_map() -> dict:
    if not DOMAIN_MAP_FILE.exists():
        return {}
    data = json.loads(DOMAIN_MAP_FILE.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {item["filename_stem"]: item for item in data if "filename_stem" in item}
    return data


def get_domain_info(md_path: Path, domain_map: dict, fallback_domain: str = None) -> dict:
    stem = md_path.stem
    if stem in domain_map:
        return domain_map[stem]
    for key, val in domain_map.items():
        if key in stem or stem in key:
            return val
    return {
        "domain": fallback_domain or "kb_unknown",
        "chapter": stem,
        "source_type": "lecture",
    }


def slugify(text: str, max_len: int = 50) -> str:
    """将标题转为合法文件名片段，同时清理 OCR 残留碎片"""
    text = re.sub(r'[（(](\d+)[）)]', r'\1', text)
    text = re.sub(r'\b[A-Za-z]{1,2}\b', '', text)
    text = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    if not text:
        return "untitled"
    return text[:max_len]


def detect_source_type(filename: str) -> str:
    name = filename.lower()
    if "真题" in filename or re.search(r'\d{4}年', filename):
        return "past_paper"
    if "论文" in filename:
        return "essay"
    if "ppt" in name or "章" in filename:
        return "lecture"
    if "辅导" in filename or "一本通" in filename:
        return "reference_book"
    if "教材" in filename:
        return "textbook"
    return "lecture"


def has_formula(text: str) -> bool:
    # LaTeX公式、数学符号、EVM相关
    formula_patterns = [r'\$.*?\$', r'\\[a-zA-Z]+\{', r'EV[MC]', r'[ACPBS][PVC][\s=]', r'CV\s*=', r'SPI\s*=', r'CPI\s*=']
    return any(re.search(p, text) for p in formula_patterns)


def has_table(text: str) -> bool:
    return '|' in text and re.search(r'\|.*\|.*\|', text) is not None


def split_by_heading(content: str, heading_level: int = 2) -> list[tuple[str, str]]:
    """
    按指定标题级别切分Markdown。
    返回 [(heading_title, chunk_content)] 列表，第一个可能是 ("", frontmatter_or_intro)
    """
    pattern = re.compile(r'^(#{' + str(heading_level) + r'})\s+(.+)$', re.MULTILINE)
    chunks = []
    last_pos = 0
    last_title = ""

    for m in pattern.finditer(content):
        chunk_text = content[last_pos:m.start()].strip()
        if chunk_text or last_title:
            chunks.append((last_title, chunk_text))
        last_title = m.group(2).strip()
        last_pos = m.end() + 1

    # 最后一段
    remaining = content[last_pos:].strip()
    if remaining or last_title:
        chunks.append((last_title, remaining))

    return chunks


def split_by_questions(content: str) -> list[tuple[str, str]]:
    """
    按题目标志切分（用于真题）。
    识别：【单选题】、【多选题】、第X题、（XX）等。
    """
    # 多种题目分隔符
    pattern = re.compile(
        r'(?=【(?:单选|多选|判断|填空|简答|案例)题】|^第\s*\d+\s*题[^章节]|^\(\d+\)|^（\d+）)',
        re.MULTILINE
    )
    parts = pattern.split(content)
    chunks = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        # 提取题号作为标题
        m = re.match(r'((?:【.*?】|第\s*\d+\s*题|\(\d+\)|（\d+）))', part)
        title = m.group(1) if m else f"题目{i+1}"
        chunks.append((title, part))
    return chunks if len(chunks) > 1 else [("", content)]


# ── 父级上下文追踪 ─────────────────────────────────────────

_SUB_HEADING_RE = re.compile(
    r'^(?:'
    r'\d[.、．](?!\d)'       # 1.体系框架 (排除 1.33, 10.1 等章节编号)
    r'|[（(]\d+[）)]\s*\S'   # （1）网络是基础, (3)效率类
    r')'
)


def is_sub_heading(title: str) -> bool:
    """判断 H2 标题是否为编号子标题（需要注入父级上下文）"""
    if not title:
        return False
    return bool(_SUB_HEADING_RE.match(title.strip()))


def build_parent_map(chunks: list[tuple[str, str]]) -> dict[int, str]:
    """
    遍历 chunk 列表，追踪"当前父级主题"。
    返回 {chunk_index: parent_title}，仅包含需要注入父级的子标题。
    """
    parent_map: dict[int, str] = {}
    current_parent = ""

    for idx, (title, _text) in enumerate(chunks):
        if not title:
            continue
        if is_sub_heading(title):
            if current_parent:
                parent_map[idx] = current_parent
        else:
            current_parent = title

    return parent_map


def merge_small_chunks(chunks: list[tuple[str, str]], min_chars: int = MIN_CHUNK_CHARS) -> list[tuple[str, str]]:
    """合并过小的chunk到前一个"""
    if not chunks:
        return chunks
    merged = [chunks[0]]
    for title, text in chunks[1:]:
        if len(text) < min_chars and merged:
            prev_title, prev_text = merged[-1]
            merged[-1] = (prev_title, prev_text + "\n\n" + (f"## {title}\n" if title else "") + text)
        else:
            merged.append((title, text))
    return merged


def build_front_matter(
    chapter: str,
    section_title: str,
) -> str:
    """精简 YAML：只保留对 RAGFlow 检索有正向增益的中文字段"""
    lines = ["---"]
    for k, v in [("chapter", chapter), ("section", section_title)]:
        if ":" in v or "#" in v:
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def process_markdown(md_path: Path, out_dir: Path, domain_info: dict,
                     force: bool = False) -> list[Path]:
    content = md_path.read_text(encoding="utf-8")
    source_type = domain_info.get("source_type") or detect_source_type(md_path.name)

    # 选择切分策略
    if source_type == "past_paper":
        chunks = split_by_questions(content)
    else:
        # 先尝试H2，不够则用H3
        chunks = split_by_heading(content, heading_level=2)
        if len(chunks) <= 1:
            chunks = split_by_heading(content, heading_level=3)
        if len(chunks) <= 1:
            # 文件本身就是一个chunk
            chunks = [("", content)]

    chunks = merge_small_chunks(chunks)
    parent_map = build_parent_map(chunks)

    out_dir.mkdir(parents=True, exist_ok=True)
    created = []

    chapter = domain_info.get("chapter", "")

    for idx, (title, text) in enumerate(chunks):
        if not text.strip():
            continue

        section_title = title
        parent_title = ""
        if idx in parent_map:
            parent_title = parent_map[idx]
            section_title = f"{parent_title} > {title}"

        # 文件名：子标题加入父级 slug 提升可读性
        if parent_title:
            parent_slug = slugify(parent_title, max_len=20)
            child_slug = slugify(title) if title else f"part{idx:03d}"
            slug = f"{parent_slug}_{child_slug}"
        else:
            slug = slugify(title) if title else f"part{idx:03d}"
        out_filename = f"{md_path.stem}__{idx:03d}_{slug}.md"
        out_path = out_dir / out_filename

        if out_path.exists() and not force:
            created.append(out_path)
            continue

        front = build_front_matter(chapter=chapter, section_title=section_title)

        # 正文：始终以 H2 标题开头，确保 BM25 和向量搜索都能命中关键词
        if section_title:
            body = f"\n## {section_title}\n\n{text}"
        else:
            body = f"\n{text}"

        out_path.write_text(front + body, encoding="utf-8")
        created.append(out_path)

    return created


def clean_target_dirs(domain_map: dict, fallback_domain: str = None):
    """清空 ragflow_upload/ 下所有 kb_* 目录中的 .md 文件"""
    deleted = 0
    for d in sorted(RAGFLOW_UPLOAD.iterdir()):
        if d.is_dir():
            for f in d.glob("*.md"):
                f.unlink()
                deleted += 1
    print(f"[CLEAN] 已删除 ragflow_upload/ 下 {deleted} 个旧 .md 文件")


def main():
    parser = argparse.ArgumentParser(description="切片Markdown并添加YAML元数据")
    parser.add_argument("--input", default="docling_out/markdown_cleaned",
                        help="Markdown目录（相对于项目根，默认使用预处理后的版本）")
    parser.add_argument("--domain", default=None, help="强制指定知识域")
    parser.add_argument("--use-map", action="store_true", help="按 chapter_domain_map.json 推断知识域")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出文件")
    parser.add_argument("--clean", action="store_true",
                        help="切片前清空 ragflow_upload/ 下所有 .md 文件（防止旧文件残留）")
    parser.add_argument("--file", default=None,
                        help="仅处理单个Markdown文件（用于轻量测试，路径相对于 --input 目录）")
    parser.add_argument("--test-dir", default=None,
                        help="测试输出目录（指定后输出到此目录而非 ragflow_upload/）")
    args = parser.parse_args()

    input_dir = BASE / args.input
    if not input_dir.exists():
        print(f"[ERROR] 目录不存在: {input_dir}")
        return

    if args.file:
        single = input_dir / args.file
        if not single.exists():
            print(f"[ERROR] 文件不存在: {single}")
            return
        mds = [single]
    else:
        mds = sorted(input_dir.rglob("*.md"))

    if not mds:
        print(f"[WARN] {input_dir} 下没有Markdown文件")
        return

    domain_map = load_domain_map() if args.use_map else {}

    if args.clean:
        clean_target_dirs(domain_map, args.domain)

    print(f"输入: {input_dir.relative_to(BASE)}  ({len(mds)} 个文件)")

    test_base = Path(args.test_dir) if args.test_dir else None

    total_chunks = 0
    for md in mds:
        info = get_domain_info(md, domain_map, fallback_domain=args.domain or "kb_unknown")
        domain = info.get("domain", "kb_unknown")
        out_dir = (test_base / domain) if test_base else (RAGFLOW_UPLOAD / domain)
        created = process_markdown(md, out_dir, info, force=args.force)
        total_chunks += len(created)
        print(f"  {md.name} → {out_dir.relative_to(BASE) if str(out_dir).startswith(str(BASE)) else out_dir}/  ({len(created)} chunks)")

    print(f"\n完成！共生成 {total_chunks} 个chunk文件")
    if test_base:
        print(f"测试输出目录: {test_base}")
    else:
        print(f"输出目录: {RAGFLOW_UPLOAD.relative_to(BASE)}")
    if not test_base:
        print("\n下一步:")
        print("  1. python scripts/postprocess_chunks.py --apply")
        print("  2. python scripts/quality_check.py")
        print("  3. 将 ragflow_upload/<domain>/ 下的文件上传到 RAGFlow 对应 dataset")


if __name__ == "__main__":
    main()
