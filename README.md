# Yuzu Core ฅ^•ﻌ•^ฅ

> Sovereign FastAPI backend and Graph-Memory Engine powering the Yuzu Companion appliance.

[![CI](https://github.com/icedeyes12/yuzu-core/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/icedeyes12/yuzu-core/actions/workflows/ci.yml)
[![Deploy](https://github.com/icedeyes12/yuzu-core/actions/workflows/deploy.yml/badge.svg?branch=master)](https://github.com/icedeyes12/yuzu-core/actions/workflows/deploy.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%20%2B%20pgvector-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org)

---

## 🛠️ Architecture & Features

- **Decoupled API Facade (`/v1`)**: Exposes strictly typed, authenticated REST endpoints and SSE streaming.
- **Episodic & Graph Memory**: PostgreSQL 18 with `pgvector` embeddings, semantic facts extraction, and FSRS memory decay.
- **Autonomous Tool Execution**: Native `tool_calls` loop bounded by strict orchestration guards.
- **Appliance Deployment**: Tailscale SSH auto-deployment pipeline targeting Termux PRoot environments.

---

## 🚀 Quick Start (Development)

```bash
# 1. Clone repository
git clone https://github.com/icedeyes12/yuzu-core.git
cd yuzu-core

# 2. Setup virtual environment & sync dependencies
uv venv .venv
source .venv/bin/activate
uv sync

# 3. Configure environment
cp .env.example .env

# 4. Start local development server
uvicorn main:app --host 127.0.0.1 --port 5000 --reload
```

---

## 🧪 Testing & Validation

```bash
# Run unit & contract tests
pytest tests/ -k "not integration and not live" -q

# Code formatting & linting
ruff check .
ruff format --check .
```

Documentation and architectural specifications are maintained in the central [**yuzu-companion**](https://github.com/icedeyes12/yuzu-companion) repository.
