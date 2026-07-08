# 高项知识助手当前运行配置

## 适用范围

本文档记录当前 `高项知识助手` 在 RAGFlow 中已经实测通过的一套运行配置，以及排查过程中发现的三个关键根因和对应修复方案。

解决的问题包括：

- 知识库里明明有内容，但 Assistant 回答"知识库中未检索到相关内容"
- Assistant 输出没有引用材料（`reference: {"chunks": []}`）
- Assistant 输出没有思考过程
- 引用材料一次性放出几十条

## 当前稳定参数

下表是当前已经验证通过的运行时参数：

| 参数 | 当前值 | 说明 |
|------|--------|------|
| `kb_ids` | 17 个知识库全部绑定 | 新 API 更新时必须同时传 `dataset_ids`，否则 `kb_ids` 被清空 |
| `top_k` | 50 | 扩大候选召回，降低大知识库下对比题漏召回概率 |
| `top_n` | 6 | 保持最终送入 LLM 的上下文数量稳定 |
| `similarity_threshold` | 0.12 | 保持召回率，避免相关材料被过早过滤 |
| `temperature` | 0.1 | 低随机性，答案更稳定 |
| `meta_data_filter.method` | `disabled` | 禁止自动元数据过滤干扰检索 |
| `show_quote` | `true` | 保留引用来源展示 |
| `empty_response` | `""`（空字符串） | 清空，避免 RAGFlow 在 LLM 回答前就截断返回固定拒答文本 |
| `rerank_model` | `""` | 当前知识助手已临时禁用 Reranker |
| `reasoning` | `false` | DeepResearcher 模式不适合当前知识库规模，见下方说明 |
| `prompt` 含 `{knowledge}` | 是 | **必须**包含 `{knowledge}` 占位符，否则检索内容不会插入 LLM prompt |

## 排查发现的三个关键根因

### 根因 1：新 API 更新会清空 `kb_ids`

**现象**：通过新 API `PUT /api/v1/chats/{id}` 更新助手 prompt 或其他参数后，助手不再返回任何引用材料，`reference` 为空。

**根因**：新 API 更新逻辑（`E:\ragflow\api\apps\sdk\chat.py:172`）中：

```python
if ids:
    req["kb_ids"] = ids
else:
    req["kb_ids"] = []
```

每次更新时如果不传 `dataset_ids`，`kb_ids` 会被**直接清空**。而 completion 走的是 `dialog.kb_ids`（不是 `dataset_ids`），所以 `kb_ids` 为空时检索不到任何内容。

**修复**：每次通过新 API 更新助手时，**必须同时传入 `dataset_ids`**（所有知识库 ID 列表）。

**反思提醒**：这是最容易踩的坑。如果你只想改一下 prompt 文字，用 `PUT /api/v1/chats/{id}` 传了 `prompt` 但没传 `dataset_ids`，知识库绑定就丢了。**安全做法**：每次更新都带上 `dataset_ids`。

### 根因 2：Prompt 缺少 `{knowledge}` 占位符

**现象**：`kb_ids` 正确、检索也能命中，但 LLM 回答中看不到检索到的内容，仍然拒答。

**根因**：RAGFlow 的检索流程（`E:\ragflow\api\db\services\dialog_service.py:458`）通过 `kwargs["knowledge"]` 将检索到的 chunk 内容注入 prompt：

```python
kwargs["knowledge"] = "\n------\n" + "\n\n------\n\n".join(knowledges)
```

然后通过 `prompt_config["system"].format(**kwargs)` 格式化。如果 system prompt 中没有 `{knowledge}` 占位符，检索到的内容**不会被插入**到发给 LLM 的 prompt 中，LLM 完全看不到知识库内容。

**修复**：在 system prompt 中显式加入 `{knowledge}` 占位符：

```
以下是通过检索得到的知识库内容：
{knowledge}
以上是检索到的知识库内容。
```

**反思提醒**：自定义 prompt 时一定要检查是否包含 `{knowledge}`。没有这个占位符，再多的检索结果也传不到 LLM。

### 根因 3：`reasoning=True` 走 DeepResearcher 不适合当前场景

**现象**：开启 `reasoning=True` 后，Assistant 会做多轮检索，返回 60+ 条 chunk，大量噪声混入，回答质量反而下降。

**根因**：`reasoning=True` 时（`E:\ragflow\api\db\services\dialog_service.py:380`），RAGFlow 走 `DeepResearcher` 路径，会做多轮迭代检索，每次都返回大量 chunk。对于当前 17 个知识库、软考备考场景，这种多轮检索引入的噪声远大于收益。

**修复**：`reasoning=False`，使用普通单轮检索路径。思考过程通过 prompt 中的"一、分析步骤"规则实现。

**反思提醒**：`reasoning=True` 适合小知识库 + 需要多步推理的复杂问题。对于大知识库 + 事实型问答，普通检索 + prompt 级别的分析步骤要求更稳定。

## 为什么当前要禁用 Reranker

本次排查发现：

- 直接调用 `/api/v1/retrieval` 时，`Hadoop / Spark / Storm` 相关材料可以正常排到前面
- 但走 Assistant completion 时，Reranker 会把一些主题无关、但词面相似的"区别类材料"排到前面
- 最终导致正确材料没有进入 Assistant 真正使用的核心上下文
- 模型于是保守回答：`知识库中未检索到相关内容`

因此，当前这套稳定配置中，知识助手临时关闭了 `rerank_model`。

## 当前 Prompt 增补策略

除了基础 System Prompt（含 `{knowledge}` 占位符）外，当前运行时还额外加入了以下策略：

### 1. 输出结构统一

所有回答统一采用以下结构：

- `一、分析步骤`
- `二、结论/答案`
- `三、来源`

### 2. 分析步骤必写

要求使用 3-5 条简洁分点说明判断或解题依据，避免直接只给结论。

### 3. 来源数量收敛

来源最多列 3 条最相关材料，优先合并同一主题来源，避免一次性抛出几十条引用。

### 4. 关键词命中必答

只要检索结果中任何一个 chunk 提到了问题中的核心关键词（如 Hadoop、Spark、Storm、挣值、PERT 等），就必须基于该 chunk 内容作答，不得拒答。

### 5. 部分相关先回答

只要检索结果中包含部分直接相关内容，就先基于已检索内容作答，而不是直接拒答。

### 6. 对比题强制按维度作答

当问题出现以下表述时：

- `有什么区别`
- `区别`
- `联系`
- `对比`
- `分别是什么`

必须先将问题转成"按若干维度分别说明"，优先使用以下维度整理答案：

- 定义
- 处理方式
- 适用场景
- 实时性
- 优缺点

### 7. 仅在完全无关时拒答

只有当所有检索结果都与问题主题完全无关、且没有任何 chunk 提到问题中的关键词时，才输出：

`知识库中未检索到相关内容`

## 已验证案例

### 案例 1：Hadoop是什么？

修复前（`kb_ids` 被清空 + 无 `{knowledge}` 占位符）：

- `reference: {"chunks": []}`，返回 0 个 chunk
- Assistant 回答：`知识库中未检索到相关内容`

修复后（`kb_ids` 恢复 + prompt 含 `{knowledge}`）：

- `reference` 返回 6 个 chunk，包含分布式计算相关内容
- Assistant 正确回答：Hadoop 是主流分布式计算系统，用于离线大数据处理
- 回答格式完整：分析步骤（4 条）→ 结论/答案 → 来源标注 `[ID:2]`

### 案例 2：Hadoop、Spark和Storm有什么区别？

修复前：

- 检索层能命中正确材料
- Assistant 仍然返回：`知识库中未检索到相关内容`

修复后：

- Assistant 能正常输出对比答案
- 回答格式为：`分析步骤 → 结论/答案 → 来源`
- 能正确区分：
  - `Hadoop`：离线批处理
  - `Spark`：内存计算，批处理 + 微批流处理
  - `Storm`：低延迟实时流处理

## 新旧 API 字段映射

通过新 API `PUT /api/v1/chats/{id}` 更新助手时，`prompt` 对象使用的字段名与数据库内部 `prompt_config` 不同。关键映射关系（源码 `chat.py:64`）：

| 新 API 字段 | 数据库 `prompt_config` 字段 | 说明 |
|-------------|---------------------------|------|
| `prompt` | `system` | System prompt 文本，**必须含 `{knowledge}`** |
| `variables` | `parameters` | 参数列表，至少含 `[{"key": "knowledge", "optional": true}]` |
| `show_quote` | `quote` | 是否显示引用 |
| `opener` | `prologue` | 开场白 |
| `rerank_model` | `rerank_id` | Reranker 模型标识 |
| `keywords_similarity_weight` | `vector_similarity_weight` | 向量/关键词权重 |

**反思提醒**：新 API 更新时 `prompt` 是一个嵌套对象，不是纯字符串。传纯字符串会报 `ValueError`。

## 推荐使用建议

### 适合的问法

优先使用更明确的问法：

- `教材中 Hadoop、Spark 和 Storm 分别适用于什么场景？`
- `Hadoop、Spark 和 Storm 的主要区别是什么？请按处理方式和适用场景回答。`

### 不稳定的问法

在大知识库场景下，过于短促的“区别类”问法更容易引入噪声，例如：

- `它们有什么区别？`
- `区别是什么？`

如果必须支持这类问法，应保留当前文档中的对比题增补策略。

## 安全更新助手的操作清单

每次通过 API 更新助手配置时，务必检查以下事项：

1. **必须传 `dataset_ids`**：否则 `kb_ids` 被清空，检索完全失效
2. **`prompt` 必须是嵌套对象**：`{"prompt": "...", "variables": [...], "show_quote": true, ...}`，不是纯字符串
3. **`prompt.prompt` 必须含 `{knowledge}`**：否则检索内容不会注入 LLM
4. **`empty_response` 设为空字符串**：避免 RAGFlow 在 LLM 回答前截断
5. **更新后用旧 API `/v1/dialog/list` 验证**：确认 `kb_ids` 数量和 `system` 中是否包含 `{knowledge}`

## 后续恢复 Reranker 的建议

后续如果重新启用 Reranker，建议先单独验证：

- 对比题是否仍能把正确主题排在前 6 条
- 是否再次出现"检索到了但仍拒答"

如果重启后再次出现该问题，应优先回退到本文件记录的当前稳定配置。

## 后续尝试 `reasoning=True` 的建议

如果未来知识库规模缩小或问题类型变为需要多步推理的复杂分析题，可以尝试开启 `reasoning=True`。验证要点：

- 单轮检索是否能覆盖问题所需的所有维度
- 多轮检索引入的噪声是否可控
- `reference` 是否仍能正常返回

如果开启后引用材料异常增多或回答质量下降，应立即回退到 `reasoning=False`。
