# PP-StructureV3 OCR 环境安装

## 硬件要求

| 组件 | 最低要求 | 推荐 |
|------|---------|------|
| GPU | NVIDIA 6GB VRAM | 8GB+ VRAM（如 RTX 3070） |
| CUDA | 12.x | 12.6+ |
| RAM | 16 GB | 32 GB |
| 磁盘 | 10 GB（模型 + 依赖） | 20 GB |

> 也支持 CPU 模式，但速度约慢 10-20 倍。

## 已验证版本

| 组件 | 版本 |
|------|------|
| Python | 3.12.9 |
| paddlepaddle-gpu | 3.2.2（CUDA 12.6 编译） |
| paddleocr | 3.4.0 |
| paddlex | 3.4.2 |
| PyMuPDF | 1.27.2.2 |
| opencv-python | 4.13.0.92 |
| Pillow | 12.1.0 |
| numpy | 2.4.1 |

## 安装步骤

### Step 1：安装 Python 3.12

前往 [python.org](https://www.python.org/downloads/) 下载 **Windows installer (64-bit)**，安装时勾选 **"Add Python to PATH"**。

```bash
python --version
# 应输出: Python 3.12.9
```

### Step 2：确认 NVIDIA 驱动

CUDA 12.6 要求驱动版本 ≥ 527.41。

```bash
nvidia-smi
```

输出中看到 `CUDA Version: 12.x` 即可。**不需要手动安装 CUDA Toolkit**，pip 包自带 CUDA 运行时。

### Step 3：创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### Step 4：安装 PaddlePaddle GPU

```bash
pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

> CUDA 12.6 对应 `cu126`。其他 CUDA 版本请参考 [PaddlePaddle 官方安装文档](https://www.paddlepaddle.org.cn/install/quick)。

### Step 5：安装 PaddleOCR + PaddleX

```bash
pip install paddleocr==3.4.0 paddlex==3.4.2
```

### Step 6：安装其余依赖

```bash
pip install -r requirements.txt
```

### Step 7：验证安装

```python
python -c "
import paddle
print('PaddlePaddle:', paddle.__version__)
print('GPU available:', paddle.is_compiled_with_cuda())

from paddleocr import PPStructureV3
print('PaddleOCR: OK')
"
```

应输出：
```
PaddlePaddle: 3.2.2
GPU available: True
PaddleOCR: OK
```

## 首次运行

首次运行 `ppstructv3_parse.py` 时，PaddleOCR 会自动下载模型文件（约 500MB），保存在 `~/.paddlex/` 目录下。

```bash
# 测试模式：只处理前 2 个 PDF
python scripts/ppstructv3_parse.py --input demo/raw --test 2

# 完整处理
python scripts/ppstructv3_parse.py --input demo/raw
```

## 性能参考

| 硬件 | 速度 | 说明 |
|------|------|------|
| RTX 3070 (8GB) | ~7 秒/页 | 逐页渲染 dpi=200 |
| RTX 3090 (24GB) | ~4 秒/页 | 同上 |
| CPU (i7-12700H) | ~120 秒/页 | 不推荐大批量 |

## 常见问题

| 问题 | 解决方法 |
|------|---------|
| `CUDA out of memory` | 降低 `--dpi`（200→150），或关闭 `--no-chart` |
| 模型下载慢 | 设置环境变量 `PADDLE_PDX_CACHE_DIR` 到本地路径，或手动下载模型 |
| `ImportError: No module named paddle` | 确认已激活虚拟环境，且安装了 GPU 版而非 CPU 版 |
| 中文乱码 | 确认系统编码为 UTF-8；Windows 下设置 `chcp 65001` |
