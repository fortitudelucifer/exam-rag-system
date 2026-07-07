# Demo

本目录包含一套可运行的 demo 数据，使用软考办官方公开 PDF 作为输入，演示完整的处理流水线。

## 数据来源

| 文件 | 来源 | 大小 |
|------|------|------|
| `1.考生模拟练习平台操作指南.pdf` | 软考办官方公开 | 607 KB |
| `2.考生常见操作说明.pdf` | 软考办官方公开 | 2.5 MB |
| `3.软考模拟练习平台常见问题.pdf` | 软考办官方公开 | 410 KB |

> 这些 PDF 来自 [中国计算机技术职业资格网](https://www.ruankao.org.cn/) 公开发布的考试操作指南，可自由传播。

## 快速开始

### 前置条件

1. 已安装 PP-StructureV3 OCR 环境（见 [docs/ocr-setup.md](../docs/ocr-setup.md)）
2. 已激活 Python 虚拟环境

### 运行完整流水线

```bash
# ① OCR 解析（约 1-2 分钟，取决于 GPU）
python scripts/ppstructv3_parse.py --input demo/raw

# ② 预处理清洗
python scripts/preprocess_ppstructv3.py --apply

# ③ 切片 + 标注（使用 demo 专用映射）
python scripts/slice_and_tag.py \
  --input ppstructv3_out/markdown_cleaned \
  --map demo/domain_map.json \
  --force --clean

# ④ 后处理清洗
python scripts/postprocess_chunks.py --apply

# ⑤ 质量检查
python scripts/quality_check.py
```

### 上传到 RAGFlow

```bash
python scripts/upload_to_ragflow.py \
  --api-key YOUR_API_KEY \
  --domain kb_demo_exam_guide kb_demo_faq
```

## 预期输出

```
demo/
├── raw/                           ← 输入 PDF（3 个）
├── domain_map.json                ← demo 专用映射
└── README.md                      ← 本文件

ppstructv3_out/                    ← OCR 输出（运行后生成）
├── markdown/                      ← 3 个 .md 文件
├── markdown_cleaned/              ← 清洗后的 .md
└── images/                        ← 逐页 PNG

ragflow_upload/                    ← 切片输出（运行后生成）
├── kb_demo_exam_guide/            ← 操作指南 chunks
└── kb_demo_faq/                   ← 常见问题 chunks
```

## 注意事项

- demo PDF 是文字型 PDF（非扫描件），PP-StructureV3 仍会逐页渲染并 OCR，速度比扫描件快
- 如果没有 GPU，可以使用 `--dpi 150` 降低渲染分辨率加速
- demo 产生的 chunks 数量较少（约 10-30 个），适合验证流水线是否正常工作
