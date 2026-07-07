# RAGFlow 部署指南

## 前置条件

| 组件 | 要求 |
|------|------|
| Docker Desktop | ≥ 24.0.0 |
| Docker Compose | ≥ v2.26.1 |
| WSL2 | `vm.max_map_count = 262144` |
| RAM | ≥ 16 GB |
| 磁盘 | ≥ 50 GB |

### 设置 WSL2 参数

```powershell
wsl -d docker-desktop sysctl -w vm.max_map_count=262144
```

## 部署步骤

### Step 1：获取 RAGFlow

```bash
git clone https://github.com/infiniflow/ragflow.git
cd ragflow/docker
```

### Step 2：配置 .env

```bash
# 镜像源（国内加速）
RAGFLOW_IMAGE=registry.cn-hangzhou.aliyuncs.com/infiniflow/ragflow:v0.24.0

# HuggingFace 镜像（用于下载 embedding 模型）
HF_ENDPOINT=https://hf-mirror.com

# 运行模式：先 CPU 跑通闭环，再切 GPU
DEVICE=cpu
```

### Step 3：启动容器

```bash
docker compose up -d
```

等待约 60 秒，检查容器状态：

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

应看到 5 个容器全部 `Up`：

| 容器 | 作用 |
|------|------|
| ragflow-server | RAGFlow 主服务 |
| es01 | Elasticsearch（向量库） |
| mysql | MySQL（元数据） |
| minio | MinIO（文件存储） |
| redis | Redis（缓存） |

### Step 4：验证 Web UI

浏览器打开 `http://127.0.0.1`，注册管理员账号并登录。

## 模型配置

在 RAGFlow Web UI → **Settings → Model Providers** 中配置：

### Chat 模型

| 配置项 | 值 |
|--------|-----|
| Provider | 按需选择（通义千问 / DeepSeek / OpenAI 兼容等） |
| Model | 如 `qwen3-max` |
| API Key | 你的 API Key |

> 也可使用本地 OpenAI 兼容代理，Base URL 设为 `http://host.docker.internal:<port>/v1`。

### Embedding 模型

两种方式，按需选择：

**方式 A：RAGFlow 内置模型（最简单）**

在 Model Providers 中选择 RAGFlow 内置的 Embedding 模型（如 `BAAI/bge-large-zh-v1.5`），无需额外部署，开箱即用。

**方式 B：VLLM 本地部署**

| 配置项 | 值 |
|--------|-----|
| Provider | VLLM |
| Base URL | `http://host.docker.internal:8011/v1` |
| Model | `Qwen3-Embedding-4B` |

> **注意**：RAGFlow 运行在 Docker 容器内，访问宿主机上的 VLLM 服务需使用 `host.docker.internal`，不能用 `127.0.0.1` 或 `localhost`。Linux 原生 Docker 需添加 `--add-host=host.docker.internal:host-gateway`。

### Reranker 模型

同样两种方式：

**方式 A：RAGFlow 内置模型**

选择 RAGFlow 内置的 Reranker 模型（如 `BAAI/bge-reranker-v2-m3`）。

**方式 B：VLLM 本地部署**

| 配置项 | 值 |
|--------|-----|
| Provider | VLLM |
| Base URL | `http://host.docker.internal:8012/v1` |
| Model | `Qwen3Reranker4B` |

> Embedding 和 Reranker 的 VLLM 部署方式见 [VLLM 文档](https://docs.vllm.ai/)。

## 获取 API Key

RAGFlow UI → 右上角头像 → **API** → 复制 API Key。

后续脚本上传使用此 Key：

```bash
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --all
```

## 上传知识库

```bash
# 上传单个知识域
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --domain kb_schedule

# 上传全部
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --all

# 替换模式（先删旧文档再上传）
python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --all --replace
```

脚本自动完成：创建 Dataset → 批量上传 .md 文件 → 触发解析向量化。

## CPU vs GPU 模式

| 维度 | CPU | GPU |
|------|-----|-----|
| .env 配置 | `DEVICE=cpu` | `DEVICE=gpu` |
| 文档导入速度 | ~2.3 页/秒 | ~8.7 页/秒 |
| 向量检索延迟 | ~320ms | ~45ms |
| 推荐场景 | 先跑通闭环 | 日常高频使用 |

切换方式：修改 `.env` 中 `DEVICE=gpu`，然后 `docker compose down && docker compose up -d`。

## 国内镜像加速

Docker Hub 拉取慢时，在 Docker Desktop → Settings → Docker Engine 中添加：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://mirror.aliyuncs.com"
  ]
}
```

重启 Docker Desktop 生效。
