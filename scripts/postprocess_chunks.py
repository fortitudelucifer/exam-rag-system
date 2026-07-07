"""
postprocess_chunks.py
对 ragflow_upload/ 下的所有 chunk 文件做三项清理：

1. 合并汉字间多余空格
   "项 目 管 理" → "项目管理"
   "可 变 成 本 :" → "可变成本:"
   保留汉字与英文/数字之间的空格（如 "第 10 章" → "第10章" 只合并相邻中文的情况）

2. 删除垃圾 chunk
   中文比例 < TRASH_CN_RATIO 且 有效字符数 < TRASH_MAX_CHARS

3. 检测文件名乱码（OCR 残留特征）
   文件名 slug 部分包含连续随机 ASCII 碎片、下划线占比过高等

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/postprocess_chunks.py            # 预览模式（dry-run）
    python scripts/postprocess_chunks.py --apply    # 实际执行
    python scripts/postprocess_chunks.py --apply --dir ragflow_upload/kb_calculation
"""

import argparse
import re
import shutil
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
RAGFLOW = BASE / "ragflow_upload"

# --- 阈值配置 ---
TRASH_CN_RATIO = 0.15    # 中文比例低于此值视为垃圾
TRASH_MAX_CHARS = 120    # 且有效字符（去掉占位符和空白）低于此值时删除


# ── 工具函数 ────────────────────────────────────────────

def split_frontmatter(text: str) -> tuple[str, str]:
    """分离 YAML front matter 和正文。返回 (front, body)"""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    front = text[:end + 4]   # 包含结尾 ---
    body = text[end + 4:]
    return front, body


_SECTION_NOISE_RE = re.compile(
    r'(?:[公司]{0,2}司添[A-Za-z]?|\[司[A-Za-z0-9]{1,20}\]?|\[Ta(?:o)?\]'
    r'|taobao(?:com|\.(?:com)?)?|bao\.|yeren(?!ruankao)[l1]?\.?)\s*'
)


def clean_frontmatter_section(front: str) -> str:
    """清理 front matter 里 section 字段的汉字空格、括号和 OCR 噪声"""
    def replace_section(m):
        val = m.group(1)
        val = _SECTION_NOISE_RE.sub('', val)
        cleaned = normalize_brackets(merge_cn_spaces(val.strip()))
        return f'section: {cleaned}'
    return re.sub(r'^section:\s*(.+)$', replace_section, front, flags=re.MULTILINE)


def merge_cn_spaces(text: str) -> str:
    """
    合并汉字之间的多余空格（迭代直到稳定）。
    规则：相邻两个汉字之间的空格删除，但汉字与英文/数字之间保留一个空格。
    """
    # 模式1：汉字 空格+ 汉字 → 直接合并（仅水平空白，不跨行）
    pattern = re.compile(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])'
                         r'[ \t]+'
                         r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])')
    prev = None
    while prev != text:
        prev = text
        text = pattern.sub(r'\1\2', text)

    # 模式2：汉字 + 空格 + 标点（如冒号、括号）→ 合并
    text = re.sub(r'([\u4e00-\u9fff])[ \t]+([：:，,。.；;！!？?、])', r'\1\2', text)
    # 模式3：标点 + 空格 + 汉字 → 合并
    text = re.sub(r'([：:，,。.；;！!？?、])[ \t]+([\u4e00-\u9fff])', r'\1\2', text)

    return text


def normalize_brackets(text: str) -> str:
    """统一括号为中文全角 （）"""
    text = text.replace('(', '（').replace(')', '）')
    return text


# OCR 乱码噪声行（PPT页码/水印区域误识别）
_OCR_NOISE_RE = re.compile(
    r'^[国园圆田团困围囱圈][国园圆田团困围囱圈动沥林吴昊明口]*[吴昊明]?\s*$',
    re.MULTILINE
)

# 页码被误识别为 H2（## 0 / ## 1 等纯数字标题）
_PAGE_NUM_H2_RE = re.compile(r'^## \d{1,3}\s*$', re.MULTILINE)

# 内联 OCR 碎片（出现在正文中间的水印/边框误识别）
_INLINE_NOISE_PATTERNS = [
    # PPT 边框水印区域误识别：公司添 / 司添 / 司公司添 等变体
    (re.compile(r'[^\S\n]*[公司]{0,2}[司]添[A-Za-z]?[^\S\n]*'), ''),
    # PPT 边框二维码/水印误识别：[司aM / [司ab / [司aYYo... 等变体
    (re.compile(r'\[司[A-Za-z0-9]{1,20}\]?'), ''),
    # 辅导书水印 yeren.taobao.com 的各种 OCR 截断变体
    # taobao 及其所有变体（taobao / taobao. / taobao.com / taobaocom）
    (re.compile(r'taobao(?:com|\.(?:com)?)?'), ''),
    # [Ta] / [Tao] —— taobao 被跨行 OCR 后残留的括号碎片
    (re.compile(r'\[Ta(?:o)?\]'), ''),
    # yeren（不含点）—— 粘连在句末或句中的水印残余
    # 排除 yerenruankao（网站域名），其余 yeren/yeren./yerenl 均为水印碎片
    (re.compile(r'yeren(?!ruankao)[l1]?\.?'), ''),
    # bao. 粘连在行首（taobao. 被换行截断后的尾部）
    (re.compile(r'^bao\.(?=[^\n])', re.MULTILINE), ''),
    # Com 水印碎片：出现在汉字之间，或跟在 * 之后（如 *Com 不规范。）
    # 用负向前瞻排除 Communication 等合法英文词
    (re.compile(r'(?<=[\u4e00-\u9fff\*\s])[ \t]*\bCom\b[ \t]*(?=[\u4e00-\u9fff\s\d]|$)', re.MULTILINE), ''),
    # 辅导书水印截断碎片（出现在单独行 或 粘连在行首）
    # 单独行：ren. / ren / ao / yer / yeren / bao / eren / com / EM / en 等
    (re.compile(r'^\s*(?:ren\b\.?|ao\b\.?|yer\b|yeren\b\.?|bao\b\.?|eren\b\.?|com\b\.?|EM|en\b|n\b)\s*$', re.MULTILINE), ''),
    # 粘连在行首的水印碎片：ren. / ren / ao. / en. 后紧跟正文内容（数字、汉字、①等）
    (re.compile(r'^(?:ren\.?|ao\.?|yer|en\.)\s*(?=[①-⑳\d\u4e00-\u9fff（【A-Da-d])', re.MULTILINE), ''),
    # OCR 残留的单字 "司" / "司号"（公司 被换页截断后的残余）
    (re.compile(r'^\s*司(?:号)?\s*$', re.MULTILINE), ''),
]

# 推广广告关键词（支持整行和拆行两种情况）
_AD_KEYWORDS = [
    '淘宝扫码购课', '淘宝扫码', '扫码购课', '微信公众号',
    '野人老师抖音', '野人老师小红书', '野人备考',
    '某宝搜索', '淘宝店铺',
    'yerenruankao.com',              # 书籍封面 URL 行
    '内部培训资料，版权所有',           # 版权声明行
]
_AD_LINE_RE = re.compile(
    r'^.*(?:' + '|'.join(re.escape(k) for k in _AD_KEYWORDS) + r').*$',
    re.MULTILINE
)
# 广告被拆行后的孤立单词（^店铺$ / ^老师$ 等只在单行出现）
_AD_FRAGMENT_RE = re.compile(
    r'^\s*(?:店铺|老师|淘|微)\s*$',
    re.MULTILINE
)

# 正文中的答案类 H2（降级为粗体）
_ANSWER_H2_RE = re.compile(
    r'^## ((?:参考)?答案|【答案】.*)$',
    re.MULTILINE
)


def clean_noise_and_ads(text: str) -> tuple[str, int, int, int]:
    """清理 OCR 乱码行、推广广告行、答案H2降级。返回 (cleaned, noise_removed, ads_removed, h2_demoted)"""
    noise_removed = len(_OCR_NOISE_RE.findall(text))
    text = _OCR_NOISE_RE.sub('', text)

    # 页码误识别为 H2（## 0 / ## 1 等）
    text = _PAGE_NUM_H2_RE.sub('', text)

    # 内联 OCR 碎片替换
    for pattern, repl in _INLINE_NOISE_PATTERNS:
        text = pattern.sub(repl, text)

    ads_removed = len(_AD_LINE_RE.findall(text))
    text = _AD_LINE_RE.sub('', text)
    # 广告拆行孤立词
    text = _AD_FRAGMENT_RE.sub('', text)

    h2_demoted = len(_ANSWER_H2_RE.findall(text))
    text = _ANSWER_H2_RE.sub(r'**\1**', text)

    # 清理连续空行（>2行 → 2行）
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text, noise_removed, ads_removed, h2_demoted


def effective_chars(body: str) -> tuple[int, float]:
    """计算有效内容：去掉占位符、空行、纯英文噪声后的中文字符数和中文比例"""
    # 去掉 Markdown 图片/公式占位符
    stripped = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)
    # 去掉 Markdown 语法行（如 |---|---| 表格分隔线）
    stripped = re.sub(r'^[\s\|\-=]+$', '', stripped, flags=re.MULTILINE)
    stripped = stripped.strip()

    total = len(stripped.replace('\n', '').replace(' ', ''))
    chinese = sum(1 for c in stripped if '\u4e00' <= c <= '\u9fff')
    ratio = chinese / max(total, 1)
    return chinese, ratio


def is_trash(body: str) -> bool:
    """判断是否为垃圾 chunk"""
    cn_count, cn_ratio = effective_chars(body)
    return cn_ratio < TRASH_CN_RATIO and cn_count < TRASH_MAX_CHARS


# 文件名乱码特征正则
_GARBLE_PATTERNS = [
    re.compile(r'[A-Za-z]{3,}'),                    # 连续3+个ASCII字母（如 Babee, Esesr, Reno）
    re.compile(r'(?:^|_)[A-Za-z]{1,2}(?:_|$)'),     # 孤立1-2字母碎片（如 _E_, _aS_）
]


def has_garbled_filename(path: Path) -> bool:
    """检测文件名 slug 部分是否含 OCR 乱码特征"""
    name = path.stem
    parts = name.split('__', 1)
    if len(parts) < 2:
        return False
    slug = parts[1]
    idx_match = re.match(r'\d{3}_', slug)
    if idx_match:
        slug = slug[idx_match.end():]

    underscore_ratio = slug.count('_') / max(len(slug), 1)
    if underscore_ratio > 0.45 and len(slug) > 10:
        return True

    ascii_letters = sum(1 for c in slug if c.isascii() and c.isalpha())
    cn_chars = sum(1 for c in slug if '\u4e00' <= c <= '\u9fff')
    if cn_chars > 0 and ascii_letters > cn_chars:
        return True

    return False


def process_file(path: Path, apply: bool) -> dict:
    """处理单个文件，返回操作结果"""
    text = path.read_text(encoding="utf-8")
    front, body = split_frontmatter(text)

    result = {"path": path, "action": "keep", "spaces_fixed": 0, "deleted": False}

    if is_trash(body):
        result["action"] = "delete"
        if apply:
            path.unlink()
            result["deleted"] = True
        return result

    if has_garbled_filename(path):
        result["action"] = "delete_garbled"
        if apply:
            path.unlink()
            result["deleted"] = True
        return result

    # 修复汉字空格 + 统一括号 + 清理噪声/广告/答案H2
    new_body = normalize_brackets(merge_cn_spaces(body))
    new_body, noise_n, ads_n, h2_n = clean_noise_and_ads(new_body)
    new_front = clean_frontmatter_section(front) if front else front

    result["noise_removed"] = noise_n
    result["ads_removed"] = ads_n
    result["h2_demoted"] = h2_n

    if new_body != body or new_front != front:
        result["action"] = "clean"
        result["spaces_fixed"] = len(re.findall(r'[\u4e00-\u9fff] [\u4e00-\u9fff]', body))
        if apply:
            path.write_text(new_front + new_body, encoding="utf-8")

    return result


# ── 主程序 ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="清理 ragflow_upload/ chunk 文件")
    parser.add_argument("--apply", action="store_true", help="实际执行（默认为预览模式）")
    parser.add_argument("--dir", default=None, help="只处理指定子目录（相对于项目根）")
    args = parser.parse_args()

    target = BASE / args.dir if args.dir else RAGFLOW
    if not target.exists():
        print(f"[ERROR] 目录不存在: {target}")
        return

    md_files = sorted(target.rglob("*.md"))
    print(f"{'[DRY-RUN]' if not args.apply else '[APPLY]'} 处理 {len(md_files)} 个文件")
    print(f"垃圾阈值: 中文<{TRASH_CN_RATIO*100:.0f}% 且有效字符<{TRASH_MAX_CHARS}")
    print()

    delete_count = garble_count = clean_count = keep_count = 0
    total_spaces = total_noise = total_ads = total_h2 = 0

    for f in md_files:
        r = process_file(f, args.apply)
        if r["action"] == "delete":
            delete_count += 1
            if not args.apply:
                cn, ratio = effective_chars(f.read_text(encoding="utf-8").split("---", 2)[-1])
                print(f"  [DELETE] {f.name[:70]}  (中文{ratio*100:.0f}% / {cn}字)")
        elif r["action"] == "delete_garbled":
            garble_count += 1
            if not args.apply:
                print(f"  [GARBLE] {f.name[:70]}")
        elif r["action"] == "clean":
            clean_count += 1
            total_spaces += r["spaces_fixed"]
            total_noise += r.get("noise_removed", 0)
            total_ads += r.get("ads_removed", 0)
            total_h2 += r.get("h2_demoted", 0)
        else:
            keep_count += 1

    print()
    print("=" * 60)
    print(f"结果: 垃圾删除={delete_count}  乱码删除={garble_count}  "
          f"清理修复={clean_count}  无需改动={keep_count}")
    print(f"修复汉字间空格: 共约 {total_spaces} 处")
    print(f"删除OCR乱码行: {total_noise} 处")
    print(f"删除推广广告行: {total_ads} 处")
    print(f"答案H2降级为粗体: {total_h2} 处")
    if not args.apply:
        print()
        print("以上为预览。加 --apply 参数实际执行。")
    else:
        print("完成。")
    print("=" * 60)


if __name__ == "__main__":
    main()
