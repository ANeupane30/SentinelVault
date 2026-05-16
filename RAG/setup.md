# 🛠️ SecureVault Setup Guide

This guide provides step-by-step instructions for setting up the **SecureVault** local-first environment from scratch on a Windows desktop.

---

## 📋 Step 0: Prerequisites & Tooling

Before you begin, ensure your machine has the necessary software installed.

1.  **Git**: [Install Git](https://git-scm.com/downloads) to clone the codebase.
2.  **Docker Desktop**: [Download Docker](https://www.docker.com/products/docker-desktop/).
    *   **IMPORTANT:** Ensure Docker is running and "Use the WSL 2 based engine" is enabled (if on Windows).
    *   **GPU Support:** Since you are on Windows using Docker Desktop with the WSL 2 backend, the NVIDIA Container Toolkit is *already built-in*. As long as you have the latest NVIDIA drivers installed on your host Windows machine, Docker will natively support GPU pass-through to containers. You do *not* need to manually download or install the NVIDIA Container Toolkit.
    *   Verify Docker is running by executing `docker --version` in your terminal.

---

## 📂 Step 1: Clone the Repository

Open your terminal (PowerShell, CMD, or Terminal) and run:

```bash
git clone https://github.com/your-username/SecureVault.git
cd SecureVault/RAG
```

---

## 🔑 Step 2: Environment Configuration

Since the new architecture is entirely local-first, you no longer need external API keys (like Fireworks or OpenAI).

1.  **Create the `.env` file:**
    In the `RAG` directory, create a new file named `.env`.
2.  **Copy and fill the following template:**

```env
# Neo4j (Graph)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=securevault_password

# Qdrant (Vector)
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

---

## 🚀 Step 3: Start SecureVault with Docker

We use Docker Compose to spin up the entire application stack, including the API service, Neo4j, and Qdrant.

1.  **Build and Start Containers:**
    ```bash
    docker-compose up --build -d
    ```
    *This will build the API image, download the official Neo4j and Qdrant images, and start everything in the background.*

2.  **Model Downloading:**
    *   The first time the API starts, it will automatically download the required local models (like `Phi-4`/`Qwen-2.5`, `GLiREL`, and `BGE-M3`) from HuggingFace. This may take several minutes depending on your internet connection.
    *   These models are cached in a Docker volume (`model_cache`) attached to your host machine, meaning they will only be downloaded once.

3.  **Verify Database and API Availability:**
    *   **FastAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
    *   **Neo4j UI:** [http://localhost:7474](http://localhost:7474)
        *   Default Credentials: `neo4j` / `securevault_password`
    *   **Qdrant Dashboard:** [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

---

## ✅ Step 4: Verification Test

You can check the API logs to see the progress of the model downloads and ensure the server has started correctly:

```bash
docker-compose logs -f sentinel_api
```

### Troubleshooting
*   **"Docker command not found":** Ensure Docker Desktop is installed and you've restarted your terminal.
*   **"Port 7687 or 8000 already in use":** You might have another instance of Neo4j or an API running. Stop it before running `docker-compose`.
*   **Models are redownloading:** Ensure the `model_cache` volume in `docker-compose.yml` is correctly mounted.
