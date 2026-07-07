"""
organize_raw.py
将现有原材料按类别复制到 raw/ 目录结构中。
- 不移动，只复制（保留原目录不变）
- 已存在的文件跳过（幂等）
- 跳过05无答案版辅导书
- 真题只取2023年及之后（有答案版）

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项
    python scripts/organize_raw.py
"""

import shutil
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
RAW = BASE / "raw"


def copy_file(src: Path, dst_dir: Path, overwrite: bool = False) -> str:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists() and not overwrite:
        return f"  [skip] {src.name} (已存在)"
    shutil.copy2(src, dst)
    return f"  [copy] {src.name}"


def main():
    results = []

    # 1. 教材
    textbook = BASE / "信息系统项目管理师教材-第四版.pdf"
    if textbook.exists():
        results.append(copy_file(textbook, RAW / "textbook"))
    else:
        results.append(f"  [WARN] 教材文件不存在: {textbook}")

    # 2. 辅导书（01-04，跳过05无答案版）
    ref_src = BASE / "01-高项内部辅导书[已更新]"
    if ref_src.exists():
        for pdf in sorted(ref_src.glob("*.pdf")):
            # 跳过05无答案版和购买说明
            name_lower = pdf.name.lower()
            if "05" in pdf.name and "无答案" in pdf.name:
                results.append(f"  [skip] {pdf.name} (无答案版，不进RAG)")
                continue
            if "购买" in pdf.name or "纸质版" in pdf.name:
                results.append(f"  [skip] {pdf.name} (非内容文件)")
                continue
            results.append(copy_file(pdf, RAW / "reference_books"))
    else:
        results.append(f"  [WARN] 辅导书目录不存在: {ref_src}")

    # 3. 章节PPT（第1-24章基础知识）
    ch_ppt_src = BASE / "03-第一阶段基础知识视频配套PPT[已更新]"
    if ch_ppt_src.exists():
        for pdf in sorted(ch_ppt_src.glob("*.pdf")):
            results.append(copy_file(pdf, RAW / "lectures" / "chapter_ppts"))
    else:
        results.append(f"  [WARN] 章节PPT目录不存在: {ch_ppt_src}")

    # 4. 计算专题PPT
    calc_src = BASE / "04_1-第二阶段计算专题视频配套PPT[已更新]"
    if calc_src.exists():
        for pdf in sorted(calc_src.glob("*.pdf")):
            results.append(copy_file(pdf, RAW / "lectures" / "calc_ppts"))
    else:
        results.append(f"  [WARN] 计算专题目录不存在: {calc_src}")

    # 5. 案例分析PPT
    case_src = BASE / "04_2-第二阶段案例分析视频配套PPT[已更新]"
    if case_src.exists():
        for pdf in sorted(case_src.glob("*.pdf")):
            results.append(copy_file(pdf, RAW / "lectures" / "case_ppts"))

    # 6. 历年真题讲解PPT（案例分析2015-2025）
    case_hist_src = BASE / "04_3-第二阶段案例分析历年真题视频配套PPT[已更新]"
    if case_hist_src.exists():
        for pdf in sorted(case_hist_src.glob("*.pdf")):
            results.append(copy_file(pdf, RAW / "lectures" / "case_history_ppts"))

    # 7. 常用学习资料（ITO表格等，PDF格式）
    ref_mat_src = BASE / "02-高项常用学习资料[已更新]"
    if ref_mat_src.exists():
        for pdf in sorted(ref_mat_src.glob("*.pdf")):
            results.append(copy_file(pdf, RAW / "reference_materials"))

    # 8. 真题：只取2023年及之后，有答案版
    past_papers_base = BASE / "野人学习资料" / "2015-2025年高级历年真题合集"

    # 8a. 选择题（2023+有答案版，不含老版教材子目录）
    mcq_src = past_papers_base / "2015-2025年选择题真题"
    if mcq_src.exists():
        for pdf in sorted(mcq_src.glob("*.pdf")):  # 只遍历当前目录，不含老版教材子目录
            name = pdf.name
            # 提取年份
            year_str = name[:4] if name[:4].isdigit() else ""
            if year_str and int(year_str) >= 2023 and "有答案" in name:
                results.append(copy_file(pdf, RAW / "past_papers" / "mcq"))
            elif year_str and int(year_str) < 2023:
                results.append(f"  [skip] {name} (2022年及之前选择题，按策略不进RAG)")
            elif "无答案" in name:
                results.append(f"  [skip] {name} (无答案版)")

    # 8b. 案例分析（2023+有答案版，不含老版教材子目录）
    case_papers_src = past_papers_base / "2015-2025年案例分析历年真题"
    if case_papers_src.exists():
        for pdf in sorted(case_papers_src.glob("*.pdf")):
            name = pdf.name
            year_str = name[:4] if name[:4].isdigit() else ""
            if year_str and int(year_str) >= 2023 and "无答案" not in name:
                results.append(copy_file(pdf, RAW / "past_papers" / "case"))
            elif "无答案" in name:
                results.append(f"  [skip] {name} (无答案版)")
            elif year_str and int(year_str) < 2023:
                results.append(f"  [skip] {name} (2022年及之前)")

    # 8c. 论文写作（2023+，不含老版教材子目录）
    essay_src = past_papers_base / "2015-2025论文写作真题"
    if essay_src.exists():
        for pdf in sorted(essay_src.glob("*.pdf")):
            name = pdf.name
            year_str = name[:4] if name[:4].isdigit() else ""
            if year_str and int(year_str) >= 2023:
                results.append(copy_file(pdf, RAW / "past_papers" / "essay"))
            else:
                results.append(f"  [skip] {name} (2022年及之前)")

    # 打印结果
    copied = [r for r in results if "[copy]" in r]
    skipped = [r for r in results if "[skip]" in r]
    warned = [r for r in results if "[WARN]" in r]

    print("=" * 60)
    print(f"organize_raw.py 完成")
    print(f"  复制: {len(copied)} 个文件")
    print(f"  跳过: {len(skipped)} 个文件")
    print(f"  警告: {len(warned)} 条")
    print("=" * 60)

    if warned:
        print("\n[警告]")
        for w in warned:
            print(w)

    print("\n[复制详情]")
    for r in results:
        print(r)

    print("\n[raw/ 目录统计]")
    for subdir in sorted(RAW.rglob("*")):
        if subdir.is_dir():
            files = list(subdir.glob("*.pdf"))
            if files:
                print(f"  {subdir.relative_to(BASE)}: {len(files)} 个PDF")


if __name__ == "__main__":
    main()
