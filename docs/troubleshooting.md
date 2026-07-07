# 故障排查

## 常见问题速查

### RAGFlow 部署

| 症状 | 原因 | 解决方法 |
|------|------|---------|
| 网页打不开 | Docker 未启动或启动中 | `docker compose up -d`，等待 60 秒 |
| `es01` 显示 `(health: starting)` | Elasticsearch 启动较慢 | 再等 30 秒 |
| Docker 镜像拉取卡住 | 网络问题 | 配置国内镜像加速器（见 [ragflow-deploy.md](ragflow-deploy.md)） |
| 容器崩溃 | 内存/显存不足 | 先 `docker compose down` 再 `up -d` |

### OCR 处理

| 症状 | 原因 | 解决方法 |
|------|------|---------|
| `CUDA out of memory` | 显存不足 | 降低 `--dpi`（200→150），或加 `--no-chart` |
| 解析卡住 | GPU 资源被占用 | 关闭其他 GPU 程序，单文件重跑 |
| 中文乱码/错字多 | 使用了旧方案（Tesseract/Docling） | 改用 PP-StructureV3 |
| 表格压成一行 | 使用了 Docling | 改用 PP-StructureV3（输出结构化 HTML） |
| 公式丢失 | 使用了 Docling | 改用 PP-StructureV3（PP-FormulaNet-L 输出 LaTeX） |

### Chunk 质量

| 症状 | 原因 | 解决方法 |
|------|------|---------|
| 汉字间多余空格 | PPT 文字是独立文本框 | `postprocess_chunks.py --apply` |
| PPT 水印/广告变成 chunk | 固定元素被识别为内容 | `preprocess_ppstructv3.py --apply` 清洗后重新切片 |
| 推广广告混入知识 chunk | PPT 含培训机构推广内容 | `postprocess_chunks.py` 自动删除 |
| 答案被切成独立 chunk | `## 答案` 被当作 H2 标题切分 | `postprocess_chunks.py` 降级为粗体 |
| chunk 数量膨胀 | 旧 OCR 残留文件 | `slice_and_tag.py --clean` 清空后再生成 |

### 检索与问答

| 症状 | 原因 | 解决方法 |
|------|------|---------|
| 回答「知识库中未检索到」 | 问题超出知识库范围 | 换个问法，或确认该知识点在资料中 |
| 回答不准确/幻觉 | top_n 召回到错误 chunk | 换更具体的问法，加入关键词 |
| 回答很慢（>30 秒） | LLM API 限流或网络波动 | 等待或稍后重试 |
| 答案末尾没有来源标注 | System Prompt 被修改 | 检查 system prompt 是否完整 |

## 关键 Bug 修复记录

### 1. 零召回 Bug（reference: {}）

**现象**：UI 显示已绑定知识库，但 `reference` 字段为空，LLM 从训练知识作答。

**根本原因**：RAGFlow 新版 SDK API（`PUT /api/v1/chats`）的 `dataset_ids` 只更新前端展示字段，内部检索引擎读取的 `kb_ids` 始终为空。

**修复**：用旧版 API `POST /v1/dialog/set` 写入 `kb_ids`。详见 [assistant-config.md](assistant-config.md)。

### 2. meta_data_filter 干扰检索

**现象**：检索被跳过，直接调用 LLM。

**原因**：`meta_data_filter.method: "auto"` 会先调 LLM 生成过滤条件，空 metadata 下导致检索流程被跳过。

**修复**：
```bash
curl -X PUT "http://127.0.0.1/api/v1/chats/YOUR_DIALOG_ID" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"meta_data_filter": {"method": "disabled"}}'
```

### 3. empty_response 导致全部"未检索到"

**现象**：所有回答都变成"未检索到相关内容"。

**原因**：`kb_ids` 为空时永远零召回，触发 `empty_response` 固定文本。

**修复**：删除 `empty_response`（设为 `""`），改用 system prompt 指令控制。

### 4. 新建对话报 "Something went wrong"

**现象**：创建或更新 Assistant 后，新建对话立即报错。

**原因**：`/v1/dialog/set` 的 `prompt_config` 漏传 `prologue` / `parameters` / `system` 等必填字段，后台 KeyError。

**修复**：调用 `/v1/dialog/set` 时必须同时传入 `system`、`prompt`、`prologue`、`opener`、`parameters`、`variables` 全部字段。

### 5. rerank_id 格式错误

**现象**：Reranker 不生效。

**原因**：新版 API 的 `rerank_id` 字段在此版本不读取。

**修复**：Reranker 在 `prompt_config.rerank_model` 中设置，格式为 `{model_name}@{provider}`。

### 6. 引用卡片显示 HTML 原始代码

**现象**：引用卡片中 HTML 表格显示为 `<table><tr><td>` 原始代码。

**原因**：RAGFlow 引用卡片是纯文本截断预览，不渲染 HTML。LLM 主回答区正常渲染。

**修复**：前端限制，无法通过 API 配置修改。如需彻底修复，将 chunk 中 HTML 表格转为 Markdown 表格后重新上传。

## 诊断命令

```bash
# 检查容器状态
docker ps --format "table {{.Names}}\t{{.Status}}"

# 检查 Web UI
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1
# 应返回 200

# 检查 kb_ids 是否为空
curl -s "http://127.0.0.1/v1/dialog/list" \
  -H "Authorization: Bearer YOUR_API_KEY" | \
  python -c "import json,sys;d=json.load(sys.stdin);[print(x['name'],'kb_ids:',x.get('kb_ids',[])) for x in d.get('data',[])]"

# 查看 RAGFlow 后台日志
docker logs ragflow-server --tail 50

# 查看 Elasticsearch 日志
docker logs es01 --tail 30
```
