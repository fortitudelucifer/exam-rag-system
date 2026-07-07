# 使用指南

## 每日启动

### 1. 启动 Docker Desktop

按 `Win + S` 搜索「Docker Desktop」并打开，等待右下角图标变为绿色。

### 2. 启动 RAGFlow 容器

```powershell
cd <your-ragflow-path>/docker
docker compose up -d
```

等待约 30-60 秒，检查容器状态：

```powershell
docker ps
```

5 个容器均为 `Up` 即正常。

### 3. 验证服务

浏览器打开 `http://127.0.0.1`，能看到 RAGFlow 登录页即可。

### 4. 停止服务（不用时）

```powershell
cd <your-ragflow-path>/docker
docker compose down
```

## 知识问答助手

### 打开方式

RAGFlow Web UI → 左侧菜单「Chat」→ 选择你的知识问答助手。

### 提问示例

**计算题（会逐步列公式）：**
```
某项目 EV=800，AC=1000，PV=900，BAC=5000，求 CPI、SPI、EAC、ETC、VAC。
```

**ITO 三要素查询：**
```
规划进度管理的输入、工具技术与输出分别是什么？
```

**知识点解释：**
```
挣值分析中 EAC 的三种计算公式分别在什么情况下使用？
```

**案例分析不足点：**
```
2024年上半年案例分析第1题，张经理在采购管理方面有哪些不足？
```

**论文框架：**
```
写一篇关于项目整合管理的论文框架，包括主要论点和段落结构。
```

### 回答说明

- 每条回答末尾有来源标注（如「来自：计算专题-成本类 §挣值分析」）
- 若回答「知识库中未检索到相关内容」→ 说明该问题超出知识库范围，属正常
- 助手只使用知识库中的内容，不会融入训练知识瞎编

### 提问技巧

1. **使用考试术语**：用"挣值分析"而非"EVM"
2. **带上数字/年份**：帮助定位真题（如"2024年上半年第1批"）
3. **拆分复杂问题**：先问"有哪些过程"，再问"每个过程的 ITO 是什么"
4. **计算题给全已知量**：提供 EV/AC/PV/BAC 等具体数值

## 出题助手

### 打开方式

RAGFlow Web UI →「Chat」→ 选择你的出题助手。

### 使用方式

| 输入 | 效果 |
|------|------|
| `出题` | 随机题型，随机知识域 |
| `出5道计算题` | 出 5 道挣值/PERT 类计算题 |
| `出案例分析题，关于风险管理` | 针对风险管理出案例题 |
| `继续` | 在上一题基础上追加出题 |
| 直接回答答案 | 助手核对并给出解析 |

### 题型说明

- **选择题**：单选，4 个选项（A/B/C/D）
- **判断题**：对/错 + 理由
- **填空题**：关键术语/公式填写
- **计算题**：给定数据，逐步列公式计算
- **案例简答**：不足点分析或改进建议

## 更新知识库

当有新的学习资料需要加入时：

```bash
# 1. OCR 解析
python scripts/ppstructv3_parse.py --input raw/new_materials

# 2. 预处理
python scripts/preprocess_ppstructv3.py --apply

# 3. 切片 + 标注
python scripts/slice_and_tag.py --input ppstructv3_out/markdown_cleaned --use-map --force

# 4. 后处理
python scripts/postprocess_chunks.py --apply

# 5. 上传到 RAGFlow
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --domain kb_target_domain
```

上传后，如需将新 Dataset 绑定到已有 Assistant，使用旧版 API：

```bash
curl -X POST http://127.0.0.1/v1/dialog/set \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dialog_id":"YOUR_DIALOG_ID","kb_ids":["旧kb_id1","旧kb_id2","新kb_id"]}'
```

> 详见 [assistant-config.md](assistant-config.md) 中的「知识库绑定」章节。

## 更换模型

### 更换 LLM（零代价）

不需要重新上传文档，直接通过 API 或 UI 更新：

```bash
curl -X POST http://127.0.0.1/v1/dialog/set \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dialog_id":"YOUR_DIALOG_ID","llm_id":"新模型@Provider"}'
```

或在 RAGFlow UI → Chat → 编辑助手 → 修改 Chat Model。

### 更换 Reranker（零代价）

同上，修改 `prompt_config.rerank_model` 字段。

### 更换 Embedding（高代价）

必须重新上传全部文档：

1. RAGFlow UI → Knowledge Base → 每个 Dataset → 删除所有文档
2. 修改 Dataset 的 Embedding Model
3. 重新运行 `upload_to_ragflow.py --all`
4. 等待向量化完成
5. 重新绑定 `kb_ids`
