##
## SentinelVault RAG — Dockerfile
##
## Base image: pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime
##   - Ships Python 3.10, PyTorch 2.5.1, CUDA 12.1, cuDNN 9 runtime libs.
##   - GPU pass-through works out-of-the-box on Docker Desktop + NVIDIA Container Toolkit.
##   - Replaces the previous python:3.10-slim base which had no CUDA runtime,
##     causing BGE-M3 and the reranker to silently run on CPU even on GPU hosts.
##
## The separate "pip install torch" step from the old Dockerfile is removed — torch is
## already baked into the base image at the exact version we need (2.5.1+cu121).
##

FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

# System-level build dependencies required by docling, grpcio, and OpenCV helpers.
# libgomp1   → OpenMP runtime used by FlagEmbedding / FAISS kernels
# libgl1     → OpenCV dependency pulled in by docling's PDF rendering backend
# libglib2.0-0 → GLib dependency for the same rendering path
# gcc / g++  → needed to compile grpcio wheels that ship no pre-built binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
# torch is already present in the base image, but we still pin it in
# requirements.txt so pip does not accidentally upgrade it.  The
# --extra-index-url ensures any torch-dependent wheel resolves the correct
# CUDA variant if pip needs to pull a transitive dep.
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
