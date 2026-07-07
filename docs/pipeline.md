# 处理流水线

## 完整流程

```
原始 PDF 材料
     │
     ▼
Step 1: 原材料整理 ─────── organize_raw.py
     │  按 PDF 类型分类到 raw/ 目录
     ▼
Step 2: OCR 解析 ────────── ppstructv3_parse.py
     │  PP-StructureV3 逐页渲染 → 版面分析 + OCR
     │  表格 → HTML <table>，公式 → LaTeX
     │  输出: ppstructv3_out/markdown/*.md
     ▼
Step 3: 预处理清洗 ──────── preprocess_ppstructv3.py
     │  删除页码注释、分隔线、噪声标题、浮动文字
     │  输出: ppstructv3_out/markdown_cleaned/*.md
     ▼
Step 4: 切片 + 标注 ─────── slice_and_tag.py
     │  按 H2 标题切分为独立 chunk
     │  注入 YAML 元数据（chapter / section）
     │  父级上下文注入 + 正文 H2 标题
     │  输出: ragflow_upload/<domain>/*.md
     ▼
Step 5: 后处理清洗 ──────── postprocess_chunks.py
     │  修复汉字间空格、统一括号
     │  删除 OCR 乱码、广告、垃圾 chunk
     │  答案 H2 降级为粗体
     ▼
Step 6: 质量检查 ────────── quality_check.py
     │  检查中文比例、标题结构、chunk 大小
     ▼
Step 7: 上传 RAGFlow ────── upload_to_ragflow.py
     │  创建 Dataset → 批量上传 → 触发向量化
     ▼
Step 8: 配置 Assistant ──── RAGFlow API / Web UI
     │  绑定知识库、配置模型、调优参数
     ▼
  智能问答 / 出题自测
```

## 脚本说明

| 脚本 | 用途 | 关键参数 |
|------|------|----------|
| `organize_raw.py` | 整理原材料到 `raw/` 目录 | 无 |
| `check_ocr_need.py` | 检测 PDF 是否有文字层（判断是否需要 OCR） | 无 |
| `ppstructv3_parse.py` | **核心**：PDF → Markdown（PP-StructureV3 GPU） | `--input <dir>`, `--test N`, `--dpi 200` |
| `preprocess_ppstructv3.py` | 清洗 PP-StructureV3 特有噪声 | `--apply`, `--file <单文件>` |
| `slice_and_tag.py` | 切片 + YAML 元数据 + 父级上下文注入 | `--input`, `--use-map`, `--force`, `--clean` |
| `postprocess_chunks.py` | 清理空格 + 垃圾 chunk + OCR 噪声 + 广告 | `--apply`, `--dir <目录>` |
| `quality_check.py` | 质量检查（chunk 大小 / 中文比例） | 无 |
| `split_textbook.py` | 拆分大 PDF 为章节 | `--auto` |
| `upload_to_ragflow.py` | 批量上传到 RAGFlow | `--api-key KEY`, `--domain <域>`, `--all`, `--replace` |
| `chapter_domain_map.json` | 文件名 → 知识域映射配置 | — |

## 标准处理命令

```bash
# ① OCR 解析（需 PaddleOCR GPU 环境）
python scripts/ppstructv3_parse.py --input raw/lectures/chapter_ppts

# ② 预处理清洗
python scripts/preprocess_ppstructv3.py --apply

# ③ 切片 + 标注
python scripts/slice_and_tag.py --input ppstructv3_out/markdown_cleaned --use-map --force --clean

# ④ 后处理清洗
python scripts/postprocess_chunks.py --apply

# ⑤ 质量检查
python scripts/quality_check.py

# ⑥ 上传到 RAGFlow
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --all
```

## Chunk 设计

### 切片原则

- 按 **H2 标题**切分（一个"节"一个 chunk）
- 最小 80 字，小于此合并到上一个 chunk
- 真题按 `【单选题】`、`第X题` 等正则切分

### Chunk 文件格式

```markdown
---
chapter: 第1章 信息化发展
section: 车联网 > 1.体系框架
---
## 车联网 > 1.体系框架

车联网（Internet of Vehicles, IoV）系统是一个"端、管、云"三层体系...
```

### 三重检索优化

基于 Anthropic Contextual Retrieval 策略：

1. **正文 H2 标题**：关键词直接进入向量 embedding 和 BM25 索引
2. **精简 YAML**：仅保留 `chapter` + `section`（中文字段），对 BM25 有正向增益
3. **文件名含父级 slug**：如 `__028_车联网_掌握_1_体系框架.md`，来源可读性好

### 后处理规则

| 规则 | 作用 |
|------|------|
| 合并汉字间多余空格 | `"项 目 管 理"` → `"项目管理"` |
| 统一半角括号为全角 | `(1）` → `（1）` |
| 删除 OCR 乱码噪声行 | PPT 装饰图案误识别的汉字 |
| 删除推广广告行 | 培训机构推广内容 |
| 答案 H2 降级为粗体 | `## 答案` → `**答案**`，防止 chunk 分裂 |
| 删除中文比例 < 15% 的垃圾 chunk | 过滤无意义内容 |

## OCR 工具选型

经过三种方案实测对比：

| 方案 | 准确率 | 表格 | 公式 | OOM | 结论 |
|------|--------|------|------|-----|------|
| OCRmyPDF + Tesseract | ~90% | 损坏 | 丢失 | 无 | 错字率高，已废弃 |
| Docling + RapidOCR | ~98% | 压成一行 | 占位符 | 有 | 表格/公式全损，已废弃 |
| **PP-StructureV3** | **~99%** | **结构化 HTML** | **LaTeX** | **无** | **当前主力** |

PP-StructureV3 优势：
- 逐页渲染策略（PyMuPDF dpi=200 → PNG → 解析），零 OOM
- 表格输出为 `<table><tr><td>` 结构化 HTML
- 公式通过 PP-FormulaNet-L 直接输出 LaTeX
- GPU 推理约 7 秒/页
