"""
upload_to_ragflow.py
将 ragflow_upload/<domain>/ 下的 chunk 文件批量上传到 RAGFlow。

流程：
  1. 登录 RAGFlow 获取 token
  2. 获取或创建指定名称的 Dataset
  3. 批量上传 .md 文件
  4. 触发解析（parsing）
  5. 轮询等待解析完成

用法：
    cd e:/BaiduSyncdisk/项目学习/中汇/软考高项

    # 上传单个域（测试）
    python scripts/upload_to_ragflow.py --email YOUR@EMAIL --password YOUR_PW --domain kb_schedule

    # 上传多个域
    python scripts/upload_to_ragflow.py --email YOUR@EMAIL --password YOUR_PW --domain kb_schedule kb_cost kb_risk

    # 上传全部域
    python scripts/upload_to_ragflow.py --email YOUR@EMAIL --password YOUR_PW --all

    # 如果已有 API key（在 RAGFlow UI → 右上角头像 → API Key 获取）
    python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --domain kb_schedule

    # 替换模式：先删除旧文档，再上传新文档（用于重新清理后的再上传）
    python scripts/upload_to_ragflow.py --api-key YOUR_API_KEY --all --replace
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent.parent.resolve()
RAGFLOW_UPLOAD = BASE / "ragflow_upload"
RAGFLOW_URL = "http://127.0.0.1"
DEFAULT_EMBEDDING_PROVIDER = os.getenv("RAGFLOW_EMBEDDING_PROVIDER", "VLLM")
DEFAULT_EMBEDDING_MODEL = os.getenv("RAGFLOW_EMBEDDING_MODEL", f"Qwen3-Embedding-4B___{DEFAULT_EMBEDDING_PROVIDER}@{DEFAULT_EMBEDDING_PROVIDER}")
RAGFLOW_CONTAINER = os.getenv("RAGFLOW_CONTAINER", "docker-ragflow-cpu-1")
SDK_API_PREFIX = "/api/v1"

ALL_DOMAINS = [
    # 基础知识域（章节PPT + 计算专题，已上传）
    "kb_schedule", "kb_cost", "kb_risk",
    "kb_scope_quality", "kb_procurement",
    "kb_resource_comm_stakeholder",
    "kb_integration", "kb_informatization",
    "kb_calculation",
    # Phase D 新增域
    "kb_case_analysis",   # 案例分析讲义PPT
    "kb_case_history",    # 历年案例分析真题讲解PPT（2015-2025）
    "kb_essay",           # 论文写作
    "papers_2023",        # 2023年真题
    "papers_2024",        # 2024年真题
    "papers_2025",        # 2025年真题
    "ref_books",          # 辅导书01-04（综合知识/计算案例/论文写作/章节练习）
    "kb_textbook",        # 教材第四版（745页）
]

# RAGFlow 每次上传文件数上限
UPLOAD_BATCH = 20


def encrypt_password_for_ragflow(password: str) -> str:
    """借用正在运行的 RAGFlow 容器中的 crypt() 对明文密码加密。"""
    cmd = [
        "docker", "exec", RAGFLOW_CONTAINER,
        "python", "-c",
        (
            "from api.utils.crypt import crypt; "
            "import sys; "
            "print(crypt(sys.argv[1]))"
        ),
        password,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"加密 RAGFlow 密码失败: {err}")
    encrypted = proc.stdout.strip().splitlines()
    if not encrypted:
        raise RuntimeError("加密 RAGFlow 密码失败: 无输出")
    return encrypted[-1].strip()


def login(email: str, password: str) -> str:
    """登录 RAGFlow，返回 authorization token"""
    encrypted_password = encrypt_password_for_ragflow(password)
    resp = requests.post(
        f"{RAGFLOW_URL}/v1/user/login",
        json={"email": email, "password": encrypted_password},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"登录失败: {data.get('message')}")
    token = data["data"].get("access_token") or data["data"].get("token")
    if not token:
        raise RuntimeError(f"登录响应中无 token: {data}")
    print(f"[LOGIN] 登录成功")
    return token


def normalize_embedding_model(embedding_model: str) -> str:
    """补齐 RAGFlow 要求的 <model>@<provider> 格式。"""
    if "@" in embedding_model:
        return embedding_model
    return f"{embedding_model}@{DEFAULT_EMBEDDING_PROVIDER}"


def get_or_create_dataset(session: requests.Session, name: str, embedding_model: str) -> str:
    """获取已有 Dataset 或创建新的，返回 dataset_id"""
    embedding_model = normalize_embedding_model(embedding_model)
    # 列出已有 datasets
    resp = session.get(f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets", timeout=60)
    resp.raise_for_status()
    datasets = resp.json().get("data", []) or []
    for ds in datasets:
        if ds.get("name") == name:
            print(f"  [DATASET] 已存在: {name} (id={ds['id'][:8]}...)")
            return ds["id"]

    # 创建新 dataset
    # chunk_method=naive 表示"按已有分块上传"，不让 RAGFlow 再切片
    resp = session.post(
        f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets",
        json={
            "name": name,
            "chunk_method": "naive",
            "embedding_model": embedding_model,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"创建 Dataset 失败: {data.get('message')}")
    ds_id = data["data"]["id"]
    print(f"  [DATASET] 已创建: {name} (id={ds_id[:8]}...)")
    return ds_id


def upload_files(session: requests.Session, dataset_id: str, files: list[Path]) -> list[str]:
    """批量上传文件，返回 document_id 列表"""
    doc_ids = []
    for i in range(0, len(files), UPLOAD_BATCH):
        batch = files[i: i + UPLOAD_BATCH]
        file_tuples = [("file", (f.name, f.read_bytes(), "text/markdown")) for f in batch]
        resp = session.post(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/documents",
            files=file_tuples,
            headers={"Content-Type": None},  # 让 requests 自动设 multipart boundary
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            print(f"  [WARN] 上传批次 {i//UPLOAD_BATCH+1} 返回错误: {data.get('message')}")
            continue
        batch_ids = [doc["id"] for doc in (data.get("data") or [])]
        doc_ids.extend(batch_ids)
        print(f"  [UPLOAD] 批次 {i//UPLOAD_BATCH+1}: {len(batch_ids)}/{len(batch)} 个文件上传成功")
    return doc_ids


PARSE_BATCH = 200   # 每次触发解析的文档数（过多时 POST 会超时）


def parse_documents(session: requests.Session, dataset_id: str, doc_ids: list[str]):
    """触发文档解析（向量化），分批触发避免超时"""
    total = 0
    for i in range(0, len(doc_ids), PARSE_BATCH):
        batch = doc_ids[i: i + PARSE_BATCH]
        resp = session.post(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/chunks",
            json={"document_ids": batch},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            print(f"  [WARN] 触发解析失败（批次{i//PARSE_BATCH+1}）: {data.get('message')}")
        else:
            total += len(batch)
    print(f"  [PARSE] 已触发 {total} 个文件的向量化解析")


def wait_for_parsing(session: requests.Session, dataset_id: str, expected: int, timeout_s: int = 7200):
    """轮询等待解析完成"""
    print(f"  [WAIT] 等待向量化完成（最长 {timeout_s}s）...", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        resp = session.get(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 1},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        total = data.get("total", 0)
        # 检查是否有正在 parsing 的文档
        docs_resp = session.get(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 100},
            timeout=60,
        )
        docs = docs_resp.json().get("data", {}).get("docs", []) or []
        pending = sum(1 for d in docs if d.get("run") == "1" or d.get("progress", 1) < 1.0)
        if pending == 0:
            elapsed = time.time() - t0
            print(f" 完成！({elapsed:.0f}s)")
            return
        print(".", end="", flush=True)
        time.sleep(10)
    print(" 超时（解析可能仍在后台运行）")


DELETE_BATCH = 200   # 每次删除的文档数（过大会超时）


def delete_all_documents(session: requests.Session, dataset_id: str):
    """删除 dataset 中所有已有文档（分批，用于 --replace 模式）"""
    total_deleted = 0
    while True:
        # 每次只取第一页（被删掉后下一批仍是第一页）
        resp = session.get(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": DELETE_BATCH},
            timeout=60,
        )
        resp.raise_for_status()
        docs = resp.json().get("data", {}).get("docs", []) or []
        if not docs:
            break

        ids = [d["id"] for d in docs]
        del_resp = session.delete(
            f"{RAGFLOW_URL}{SDK_API_PREFIX}/datasets/{dataset_id}/documents",
            json={"ids": ids},
            timeout=120,
        )
        del_resp.raise_for_status()
        data = del_resp.json()
        if data.get("code") != 0:
            print(f"  [WARN] 删除批次失败: {data.get('message')}")
            break
        total_deleted += len(ids)
        print(f"  [REPLACE] 已删除 {total_deleted} 个旧文档...", end="\r")
        if len(docs) < DELETE_BATCH:
            break  # 最后一批，不需要再查

    if total_deleted:
        print(f"  [REPLACE] 共删除 {total_deleted} 个旧文档          ")
    else:
        print(f"  [REPLACE] 无已有文档，跳过删除")


def process_domain(session: requests.Session, domain: str, embedding_model: str,
                   dry_run: bool = False, replace: bool = False):
    domain_dir = RAGFLOW_UPLOAD / domain
    if not domain_dir.exists():
        print(f"[SKIP] {domain}: 目录不存在")
        return

    files = sorted(domain_dir.glob("*.md"))
    if not files:
        print(f"[SKIP] {domain}: 无 .md 文件")
        return

    print(f"\n[{domain}] {len(files)} 个文件")
    if dry_run:
        print(f"  [DRY-RUN] 跳过实际上传")
        return

    ds_id = get_or_create_dataset(session, domain, embedding_model)
    if replace:
        delete_all_documents(session, ds_id)
    doc_ids = upload_files(session, ds_id, files)
    if doc_ids:
        parse_documents(session, ds_id, doc_ids)
        wait_for_parsing(session, ds_id, len(doc_ids))
    print(f"  [DONE] {domain} 完成")


def main():
    global RAGFLOW_URL
    parser = argparse.ArgumentParser(description="批量上传 chunk 到 RAGFlow")
    parser.add_argument("--email", help="RAGFlow 登录邮箱")
    parser.add_argument("--password", help="RAGFlow 登录密码")
    parser.add_argument("--api-key", help="RAGFlow API Key（替代邮箱/密码）")
    parser.add_argument("--domain", nargs="+", help="指定上传的域（可多个）")
    parser.add_argument("--all", action="store_true", help="上传所有域")
    parser.add_argument("--url", default=RAGFLOW_URL, help=f"RAGFlow 地址（默认 {RAGFLOW_URL}）")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help=f"创建 Dataset 时使用的 embedding 模型（默认 {DEFAULT_EMBEDDING_MODEL}）")
    parser.add_argument("--dry-run", action="store_true", help="只列出文件数，不实际上传")
    parser.add_argument("--replace", action="store_true", help="上传前先删除 dataset 中所有旧文档（替换模式）")
    args = parser.parse_args()

    RAGFLOW_URL = args.url.rstrip("/")

    # 建立 session
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    if args.api_key:
        session.headers.update({"Authorization": f"Bearer {args.api_key}"})
        print(f"[AUTH] 使用 API Key 认证")
    elif args.email and args.password:
        token = login(args.email, args.password)
        session.headers.update({"Authorization": f"Bearer {token}"})
    else:
        print("[ERROR] 需要 --api-key 或 --email + --password")
        sys.exit(1)

    # 确定要处理的域
    if args.all:
        domains = ALL_DOMAINS
    elif args.domain:
        domains = args.domain
    else:
        print("[ERROR] 需要 --domain <域名> 或 --all")
        sys.exit(1)

    print(f"目标域: {domains}")
    print(f"RAGFlow: {RAGFLOW_URL}")
    print(f"Embedding model: {args.embedding_model}")
    print()

    for d in domains:
        try:
            process_domain(session, d, args.embedding_model,
                           dry_run=args.dry_run, replace=args.replace)
        except Exception as e:
            print(f"  [ERROR] {d}: {e}")

    print("\n全部完成。")
    print("下一步: 在 RAGFlow UI 中创建 Assistant，选择对应 Dataset，做检索测试。")


if __name__ == "__main__":
    main()
