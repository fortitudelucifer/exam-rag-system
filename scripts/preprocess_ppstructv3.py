"""
preprocess_ppstructv3.py
清理 PP-StructureV3 输出 Markdown 中的特有噪声，输出到 markdown_cleaned/。

PPStructV3 特有的需清理元素：
  1. <!-- page N --> 页码注释
  2. 独立的 --- 页分隔线（PPT 逐页分隔，非 Markdown 语义分隔线）
  3. 页 1 噪声标题：## 野人软考学院 / # 信息系统项目管理师 / ## 信息系统项目管理师
  4. 空 H2 标题：## （无文字）
  5. 单符号噪声 H2：## · 等
  6. 中心浮动文字 div（仅含纯文本，无 HTML 子标签）→ 删除（与相邻 H2 重复）
     保留：含 <table>/<img> 的中心 div

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/preprocess_ppstructv3.py              # 预览模式（打印统计）
    python scripts/preprocess_ppstructv3.py --apply      # 实际写文件
    python scripts/preprocess_ppstructv3.py --apply --file 第10章-项目进度管理.md
"""

import argparse
import re
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
INPUT_DIR = BASE / "ppstructv3_out" / "markdown"
OUTPUT_DIR = BASE / "ppstructv3_out" / "markdown_cleaned"


# ── 正则规则 ───────────────────────────────────────────────

# 1. <!-- page N --> 注释
_RE_PAGE_COMMENT = re.compile(r'<!--\s*page\s*\d+\s*-->', re.IGNORECASE)

# 2. 独立 --- 分隔线（前后都是空行，或在文档头/尾）
_RE_HR = re.compile(r'(?:^|\n)\n---\n(?:\n|$)')

# 3. 页 1 噪声标题（完整行匹配）
_NOISE_TITLES = [
    '野人软考学院',
    '信息系统项目管理师',
]
_RE_NOISE_HEADING = re.compile(
    r'^#{1,3}\s*(?:' + '|'.join(re.escape(t) for t in _NOISE_TITLES) + r')\s*$',
    re.MULTILINE
)

# 4. 空 H1/H2/H3（# 后无文字，或只有空白）
_RE_EMPTY_HEADING = re.compile(r'^#{1,3}\s*$', re.MULTILINE)

# 5. 单符号噪声标题（·、•、-、* 等）
_RE_SYMBOL_HEADING = re.compile(r'^#{1,3}\s*[·•\-\*]\s*$', re.MULTILINE)

# 6. 中心浮动文字 div（div 内容为纯文本，不含 HTML 子标签）
#    匹配：<div style="text-align: center;">文字内容</div>
#    不匹配：包含 <table>/<img>/<html> 等子标签的 div
_RE_CENTER_TEXT_DIV = re.compile(
    r'<div style="text-align: center;">([^<]+)</div>',
    re.IGNORECASE
)


def clean_text(text: str) -> dict:
    """对单个文件内容执行所有清理，返回清理后内容和统计"""
    stats = {
        'page_comments': 0,
        'hr_removed': 0,
        'noise_headings': 0,
        'empty_headings': 0,
        'symbol_headings': 0,
        'center_divs': 0,
    }

    # 1. 删除 <!-- page N --> 注释
    new, n = _RE_PAGE_COMMENT.subn('', text)
    stats['page_comments'] = n
    text = new

    # 2. 删除独立 --- 分隔线（用双换行替换，保持段落间距）
    # 逐步替换直到稳定（应对连续多个 ---）
    prev = None
    count = 0
    while prev != text:
        prev = text
        new, n = _RE_HR.subn('\n\n', text)
        text = new
        count += n
    stats['hr_removed'] = count

    # 3. 删除页 1 噪声标题
    new, n = _RE_NOISE_HEADING.subn('', text)
    stats['noise_headings'] = n
    text = new

    # 4. 删除空 H2/H3（## 后无文字）
    new, n = _RE_EMPTY_HEADING.subn('', text)
    stats['empty_headings'] = n
    text = new

    # 5. 删除单符号噪声标题
    new, n = _RE_SYMBOL_HEADING.subn('', text)
    stats['symbol_headings'] = n
    text = new

    # 6. 删除中心浮动文字 div（仅纯文本，非 HTML）
    new, n = _RE_CENTER_TEXT_DIV.subn('', text)
    stats['center_divs'] = n
    text = new

    # 7. 清理连续空行（>2行 → 2行）
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 8. 去掉首尾多余空白
    text = text.strip() + '\n'

    return text, stats


def process_file(src: Path, dst: Path, apply: bool) -> dict:
    text = src.read_text(encoding='utf-8')
    cleaned, stats = clean_text(text)
    changed = cleaned != text

    if apply and changed:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(cleaned, encoding='utf-8')
    elif apply and not changed:
        # 无变化也复制过去（确保 markdown_cleaned 目录完整）
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(cleaned, encoding='utf-8')

    stats['changed'] = changed
    return stats


def main():
    parser = argparse.ArgumentParser(description='清理 PPStructV3 Markdown 输出噪声')
    parser.add_argument('--apply', action='store_true', help='实际写入 markdown_cleaned/（默认预览）')
    parser.add_argument('--file', default=None, help='只处理单个文件（文件名，不含路径）')
    args = parser.parse_args()

    if args.file:
        srcs = [INPUT_DIR / args.file]
        if not srcs[0].exists():
            print(f'[ERROR] 文件不存在: {srcs[0]}')
            return
    else:
        srcs = sorted(INPUT_DIR.glob('*.md'))

    if not srcs:
        print(f'[WARN] {INPUT_DIR} 下没有 .md 文件')
        return

    mode = '[APPLY]' if args.apply else '[DRY-RUN]'
    print(f'{mode} 处理 {len(srcs)} 个文件')
    print(f'输入: {INPUT_DIR.relative_to(BASE)}')
    print(f'输出: {OUTPUT_DIR.relative_to(BASE)}')
    print()

    total = {k: 0 for k in ['page_comments', 'hr_removed', 'noise_headings',
                              'empty_headings', 'symbol_headings', 'center_divs']}
    changed_count = 0

    for src in srcs:
        dst = OUTPUT_DIR / src.name
        stats = process_file(src, dst, args.apply)
        if stats['changed']:
            changed_count += 1
            parts = []
            if stats['page_comments']: parts.append(f"页注释×{stats['page_comments']}")
            if stats['hr_removed']:    parts.append(f"分隔线×{stats['hr_removed']}")
            if stats['noise_headings']:parts.append(f"噪声标题×{stats['noise_headings']}")
            if stats['empty_headings']:parts.append(f"空标题×{stats['empty_headings']}")
            if stats['symbol_headings']:parts.append(f"符号标题×{stats['symbol_headings']}")
            if stats['center_divs']:   parts.append(f"浮动文字×{stats['center_divs']}")
            print(f'  {src.name[:60]}  [{", ".join(parts)}]')
        for k in total:
            total[k] += stats[k]

    print()
    print('=' * 60)
    print(f'修改文件数: {changed_count}/{len(srcs)}')
    print(f'删除页码注释: {total["page_comments"]}')
    print(f'删除页分隔线: {total["hr_removed"]}')
    print(f'删除噪声标题: {total["noise_headings"]}')
    print(f'删除空标题:   {total["empty_headings"]}')
    print(f'删除符号标题: {total["symbol_headings"]}')
    print(f'删除浮动文字: {total["center_divs"]}')
    if not args.apply:
        print()
        print('以上为预览。加 --apply 实际写入文件。')
    else:
        print(f'输出目录: {OUTPUT_DIR}')
    print('=' * 60)


if __name__ == '__main__':
    main()
