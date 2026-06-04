# 🛠️ SentinelVault Setup Guide

This guide provides step-by-step instructions for setting up the **SentinelVault RAG** environment from scratch on a Windows desktop.

> **LLM is remote.** The system connects to a self-hosted Ollama server for all generative inference. No local GPU is required for the LLM — only for the embedding and reranking models (`BGE-M3`, `BGE-Reranker-v2-m3`).

---

## 📋 Step 0: Prerequisites & Tooling

Before you begin, ensure your machine has the necessary software installed.

1. **Git** — [Install Git](https://git-scm.com/downloads) to clone the codebase.
2. **Docker Desktop** — [Download Docker](https://www.docker.com/products/docker-desktop/).
   - Enable **"Use the WSL 2 based engine"** (Windows only).
   - Since the LLM is now remote, Docker Desktop AI is **not required**.
   - GPU pass-through (for BGE-M3 / Reranker): on Windows + Docker Desktop, NVIDIA support is built-in — just keep your host NVIDIA drivers up to date. No Container Toolkit install needed.
   - Verify Docker is running: `docker --version`
3. **NVIDIA GPU** *(optional but recommended)* — needed for local embedding/reranking models. Minimum 4 GB VRAM. Set `REQUIRE_GPU=false` to run in CPU-only mode.

---

## 📂 Step 1: Clone the Repository

Open PowerShell or your terminal and run:

```bash
git clone https://github.com/your-username/SecureVault.git
cd SecureVault/RAG
```

---

## 🔑 Step 2: Environment Configuration

All sensitive configuration lives in a `.env` file inside the `RAG/` directory. This file is **not** committed to git.

1. **Create the `.env` file** in the `RAG/` directory.
2. **Fill in the template below:**

```env
# ── Neo4j (Graph DB) ────────────────────────────────────────────────────────
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=securevault_password

# ── Qdrant (Vector DB) ──────────────────────────────────────────────────────
QDRANT_URL=http://localhost:6333

# ── Remote Ollama LLM ───────────────────────────────────────────────────────
# Points to the self-hosted Ollama server via its OpenAI-compatible /v1 endpoint.
# Supports both /api/generate|chat (native) and /v1/chat/completions (OpenAI-compat).
LLM_BASE_URL=http://134.199.148.99:11434/v1
LLM_MODEL_ID=qwen2.5:3b-instruct-q4_K_M
LLM_API_KEY=ollama
LLM_JSON_RETRIES=3

# ── Service-to-Service Auth ──────────────────────────────────────────────────
# The .NET backend must send this value in the X-Api-Key header on /v1/* calls.
RAG_API_KEY=your-secret-key-here

# ── Hardware ─────────────────────────────────────────────────────────────────
# Minimum VRAM for BGE-M3 + BGE-Reranker (local models only; LLM is remote).
MIN_VRAM_GB=4
# Set to false to skip GPU check and run in CPU-only mode (degraded throughput).
REQUIRE_GPU=true

# ── Chunker ──────────────────────────────────────────────────────────────────
CHUNK_SIZE=1500
CHUNK_OVERLAP=150
```

> **Note on `LLM_BASE_URL`, `LLM_MODEL_ID`, and `LLM_API_KEY`:** These variables have **no hardcoded fallback** in the code — if any is missing, the service will fail fast with a clear error at startup. Always set all three.

---

## 🚀 Step 3: Start SentinelVault with Docker Compose

Docker Compose spins up the full stack: FastAPI service, Neo4j, and Qdrant.

```bash
docker-compose up --build -d
```

> *This builds the API image, pulls the official Neo4j and Qdrant images, and starts everything in the background.*

### What happens on first start

| Component | Behaviour |
| :--- | :--- |
| **Neo4j** | Downloads image, initialises data volume. Ready in ~10 s. |
| **Qdrant** | Downloads image, initialises storage volume. Ready in ~5 s. |
| **sentinel_api** | Builds Python image, downloads `BGE-M3` and `BGE-Reranker-v2-m3` from HuggingFace into the `hf_cache` named volume. **This may take several minutes on the first run.** Subsequent restarts use the cached weights. |
| **LLM** | No download needed — inference hits the remote Ollama server directly. |

---

## ✅ Step 4: Verify Everything Is Running

### 4a. Service URLs

| Service | URL |
| :--- | :--- |
| FastAPI (Swagger UI) | [http://localhost:8000/docs](http://localhost:8000/docs) |
| FastAPI Health Check | [http://localhost:8000/health](http://localhost:8000/health) |
| Neo4j Browser | [http://localhost:7474](http://localhost:7474) — login: `neo4j` / `securevault_password` |
| Qdrant Dashboard | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |

### 4b. Follow API Logs

```bash
docker-compose logs -f sentinel_api
```

Look for this log line to confirm the LLM client is connected correctly:

```
LocalLLMClient initialised → base_url=http://134.199.148.99:11434/v1, model=qwen2.5:3b-instruct-q4_K_M
```

### 4c. Test the Remote LLM Connection

You can quickly verify the Ollama endpoint is reachable before starting the full stack:

```bash
curl http://134.199.148.99:11434/api/tags
```

A JSON list of available models should be returned. Confirm `qwen2.5:3b-instruct-q4_K_M` is present.

---

## 🔒 Step 5: API Key Authentication

All `/v1/*` endpoints require the `X-Api-Key` header. Set `RAG_API_KEY` in your `.env` (and expose it to the container via `docker-compose.yml`) and pass the same value from your .NET backend:

```http
POST /v1/ingest
X-Api-Key: your-secret-key-here
```

The `/health` endpoint is **public** (no auth required) and is used by Docker's health check.

---

## 🛠️ Troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `"Docker command not found"` | Ensure Docker Desktop is installed and you've restarted your terminal. |
| `"Port 7687 or 8000 already in use"` | Stop any conflicting Neo4j or API processes before running `docker-compose`. |
| `"LLM_BASE_URL is not set"` | Ensure your `.env` file contains all three `LLM_*` variables and is mounted correctly. |
| LLM requests time out | Verify the Ollama server is reachable: `curl http://134.199.148.99:11434/api/tags` |
| BGE models re-downloading on restart | Confirm the `hf_cache` named volume is correctly defined and mounted in `docker-compose.yml`. |
| GPU not detected | Check host NVIDIA driver version. Set `REQUIRE_GPU=false` to run in CPU-only mode. |
