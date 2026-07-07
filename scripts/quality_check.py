"""
quality_check.py
对 docling_out/markdown/ 或 ragflow_upload/ 中的Markdown文件进行质量抽查。

检测项：
  - 文件非空
  - 中文字符占比（低于30%可能是解析质量差）
  - 标题结构（是否有H2/H3）
  - 乱码特征（连续□、连续?, 非打印字符密集）
  - 超长chunk（>8000字符）
  - 前3个chunk的内容预览

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/quality_check.py                          # 检查 docling_out/markdown/
    python scripts/quality_check.py --input ragflow_upload   # 检查所有upload目录
    python scripts/quality_check.py --input ragflow_upload/kb_schedule  # 只检查进度管理
    python scripts/quality_check.py --sample 5              # 每目录抽5个文件
"""

import argparse
import re
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()

CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff]')
GARBLE_PATTERN = re.compile(r'[□▪\ufffd]{3,}|[\?]{5,}')
NON_PRINT_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
MIN_CN_RATIO = 0.10  # 中文字符占比低于10%警告
MAX_CHUNK_CHARS = 8000


def analyze_file(path: Path) -> dict:
    result = {
        "path": str(path.relative_to(BASE)),
        "size_bytes": path.stat().st_size,
        "char_count": 0,
        "cn_char_count": 0,
        "cn_ratio": 0.0,
        "has_h2": False,
        "has_h3": False,
        "garble_hits": 0,
        "nonprint_hits": 0,
        "issues": [],
    }

    if path.stat().st_size == 0:
        result["issues"].append("空文件")
        return result

    content = path.read_text(encoding="utf-8", errors="replace")
    result["char_count"] = len(content)
    cn_chars = CHINESE_PATTERN.findall(content)
    result["cn_char_count"] = len(cn_chars)
    result["cn_ratio"] = len(cn_chars) / max(len(content), 1)
    result["has_h2"] = bool(re.search(r'^##\s', content, re.MULTILINE))
    result["has_h3"] = bool(re.search(r'^###\s', content, re.MULTILINE))
    result["garble_hits"] = len(GARBLE_PATTERN.findall(content))
    result["nonprint_hits"] = len(NON_PRINT_PATTERN.findall(content))

    # 判断问题
    if result["cn_ratio"] < MIN_CN_RATIO and result["char_count"] > 200:
        result["issues"].append(f"中文比例低({result['cn_ratio']:.1%})")
    if result["garble_hits"] > 0:
        result["issues"].append(f"疑似乱码({result['garble_hits']}处)")
    if result["nonprint_hits"] > 5:
        result["issues"].append(f"非打印字符({result['nonprint_hits']}个)")
    if result["char_count"] > MAX_CHUNK_CHARS:
        result["issues"].append(f"chunk过大({result['char_count']}字符)")
    if result["char_count"] < 100:
        result["issues"].append(f"内容极短({result['char_count']}字符)")

    return result


def preview_file(path: Path, lines: int = 8) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        preview_lines = content.strip().split('\n')[:lines]
        return '\n'.join('    ' + l for l in preview_lines)
    except Exception as e:
        return f"    [读取失败: {e}]"


def main():
    parser = argparse.ArgumentParser(description="检查Markdown解析质量")
    parser.add_argument("--input", default="docling_out/markdown", help="要检查的目录")
    parser.add_argument("--sample", type=int, default=3, help="每目录抽查文件数（0=全部）")
    parser.add_argument("--show-preview", action="store_true", help="显示文件内容预览")
    args = parser.parse_args()

    input_dir = BASE / args.input
    if not input_dir.exists():
        print(f"[ERROR] 目录不存在: {input_dir}")
        return

    all_mds = sorted(input_dir.rglob("*.md"))
    if not all_mds:
        print(f"[WARN] 没有找到Markdown文件: {input_dir.relative_to(BASE)}")
        return

    print(f"检查目录: {input_dir.relative_to(BASE)}")
    print(f"找到 {len(all_mds)} 个Markdown文件")

    # 按子目录分组
    by_dir: dict[Path, list[Path]] = {}
    for md in all_mds:
        by_dir.setdefault(md.parent, []).append(md)

    all_results = []
    problem_files = []

    for dir_path, files in sorted(by_dir.items()):
        sample = files if args.sample == 0 else files[:args.sample]
        print(f"\n[{dir_path.relative_to(BASE)}]  {len(files)}个文件，抽查{len(sample)}个")

        for f in sample:
            r = analyze_file(f)
            all_results.append(r)

            status = "✓" if not r["issues"] else "⚠"
            print(f"  {status} {f.name}")
            print(f"    {r['char_count']}字符 | 中文{r['cn_ratio']:.0%} | H2={'有' if r['has_h2'] else '无'} H3={'有' if r['has_h3'] else '无'}")
            if r["issues"]:
                print(f"    [问题] {' | '.join(r['issues'])}")
                problem_files.append(r)
            if args.show_preview:
                print(preview_file(f))

    # 汇总
    print("\n" + "=" * 60)
    print(f"抽查总计: {len(all_results)} 个文件")
    ok = [r for r in all_results if not r["issues"]]
    warn = [r for r in all_results if r["issues"]]
    print(f"  通过: {len(ok)}")
    print(f"  有问题: {len(warn)}")

    if warn:
        print("\n[需要关注的文件]")
        for r in warn:
            print(f"  {r['path']}")
            print(f"    问题: {' | '.join(r['issues'])}")

    print("\n[建议]")
    garble_count = sum(1 for r in warn if any("乱码" in i for i in r["issues"]))
    low_cn_count = sum(1 for r in warn if any("中文比例低" in i for i in r["issues"]))
    large_count = sum(1 for r in warn if any("过大" in i for i in r["issues"]))

    if garble_count > 0:
        print(f"  - {garble_count}个文件有乱码 → 检查OCRmyPDF是否安装chi_sim语言包")
    if low_cn_count > 0:
        print(f"  - {low_cn_count}个文件中文比例低 → 检查Docling是否配置了ch_sim")
    if large_count > 0:
        print(f"  - {large_count}个chunk过大 → 考虑调小切片粒度（H3级别切分）")
    if not warn:
        print("  质量良好！可以继续下一步上传到RAGFlow。")


if __name__ == "__main__":
    main()
