# Assistant 配置

## 概述

RAGFlow 的 Assistant（助手）是连接知识库和 LLM 的桥梁。配置一个优秀的 Assistant 需要关注三件事：**知识库绑定**、**参数调优**、**System Prompt 设计**。

## 知识库绑定（关键）

### 两套 API 的区别

RAGFlow 有两套 API 用于更新 Assistant 配置，行为不同：

| API | 路径 | 知识库字段 | 实际控制检索？ |
|-----|------|-----------|--------------|
| 新版 SDK API | `PUT /api/v1/chats/{id}` | `dataset_ids` | **否**（仅更新前端展示） |
| 旧版内部 API | `POST /v1/dialog/set` | `kb_ids` | **是**（真正控制检索引擎） |

> **重要**：通过新版 API 绑定的知识库只更新前端显示，检索引擎实际读取的是 `kb_ids`。如果 `kb_ids` 为空，检索永远为空，LLM 会从训练知识"瞎编"答案。

### 诊断方法

```bash
# 检查 kb_ids 是否为空
curl -s "http://127.0.0.1/v1/dialog/list" \
  -H "Authorization: Bearer YOUR_API_KEY" | \
  python -c "import json,sys;d=json.load(sys.stdin);[print(x['name'],'kb_ids:',x.get('kb_ids',[])) for x in d.get('data',[])]"
```

### 修复方法

用旧版 API 绑定知识库：

```bash
curl -s -X POST "http://127.0.0.1/v1/dialog/set" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "dialog_id": "YOUR_DIALOG_ID",
    "kb_ids": ["kb_id_1", "kb_id_2", "..."],
    "name": "知识问答助手",
    "llm_id": "YOUR_LLM_MODEL",
    "prompt_config": {
      "system": "YOUR_SYSTEM_PROMPT",
      "prologue": "Hi! What can I do for you?",
      "parameters": [{"key": "knowledge", "optional": true}]
    }
  }'
```

> **注意**：`/v1/dialog/set` 的 `prompt_config` 必须同时包含 `system`、`prologue`、`parameters` 等全部字段，漏传任意字段会导致后台 KeyError，前端显示 "Something went wrong"。

## 参数调优

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `similarity_threshold` | 0.12 | 低阈值保证召回率 |
| `vector_similarity_weight` | 0.5 | 向量与 BM25 各占 50% |
| `top_k` | 100-200 | 候选 chunk 数（送 Reranker 精排）。本地部署 Reranker 可调至 500-1024，云端 API 建议不超过 200 |
| `top_n` | 6 | 最终送入 LLM 的 chunk 数 |
| `temperature` | 0.1 | 低随机性，计算题答案稳定 |
| `meta_data_filter` | disabled | 禁用元数据过滤（auto 模式会干扰检索） |
| `show_quote` | true | 显示引用来源 |

### top_n 对比测试

对 4 道跨域问题测试 top_n = 4 / 6 / 8：

| top_n | score 最低分 | 简单题表现 | 复杂题表现 | 结论 |
|-------|------------|-----------|-----------|------|
| 4 | ~0.325 | 正常 | 可能漏信息 | 不足 |
| **6** | **~0.301** | **正常** | **引用充分** | **最优** |
| 8 | ~0.246 | 噪声混入，LLM 迷失 | 引用过多 | 过载 |

## System Prompt 设计

### 知识问答助手

```
你是"知识问答助手"，专门回答考试相关问题。

【知识库范围】
本助手知识库包含以下资料，回答必须且只能来自这些资料：
- 章节讲义 PPT（各知识域）
- 计算专题 PPT
- 案例分析讲义 + 历年真题讲解
- 近年真题
- 论文写作资料
- 辅导书
- 教材

【严格规则】
1. 只使用检索到的内容作答，不使用训练知识补充。
2. 若检索结果不足以回答，明确说明"知识库中未检索到相关内容"。
3. 禁止融入知识库以外的知识。

【按题型作答格式】
- 计算题：写出公式 → 代入数值 → 逐步计算 → 给出结论
- 案例分析：逐条列举要点，不扩充不改写
- 选择/判断题：直接给答案，附引用原文判据
- 论文写作：提供结构框架，引用资料中的要点
- 知识点解释：定义 → 示例 → 来源标注

所有回答末尾须标注来源。
```

### 出题助手

```
你是"出题助手"，根据知识库内容出题供自测练习。

【出题规则】
1. 每次出 1 道题，题型随机（选择/判断/填空/计算/案例简答）。
2. 题目必须基于检索到的知识库内容，不得凭空编造。
3. 用户回答后，核对答案并给出解析 + 来源标注。

【题型说明】
- 选择题：单选，4 个选项（A/B/C/D）
- 判断题：对/错 + 理由
- 填空题：关键术语/公式填写
- 计算题：给定数据，逐步列公式计算
- 案例简答：不足点分析或改进建议
```

### 出题助手参数差异

| 参数 | 知识助手 | 出题助手 |
|------|---------|---------|
| `top_n` | 6 | 3（聚焦单一知识点） |
| `temperature` | 0.1 | 0.3（题目有变化） |
| `refine_multiturn` | false | true（答题→解析连贯） |

## 日常使用

### 知识问答助手

| 提问方式 | 示例 |
|---------|------|
| 计算题 | `EV=800，AC=1000，PV=900，BAC=5000，求 CPI、SPI、EAC` |
| ITO 查询 | `规划进度管理的输入、工具技术与输出分别是什么？` |
| 案例分析 | `2024年上半年案例分析第1题，在采购管理方面有哪些不足？` |
| 论文框架 | `写一篇关于项目整合管理的论文框架` |

### 出题助手

| 输入 | 效果 |
|------|------|
| `出题` | 随机题型，随机知识域 |
| `出5道计算题` | 指定题型和数量 |
| `出进度管理的题` | 指定知识域 |
| `继续` | 下一题 |
| 直接回答 | 助手核对并给出解析 |
