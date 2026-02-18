# Yuzu Companion — Server Requirements

> **Date**: 2026-02-18
> **Based on**: Codebase analysis of v2.1.2 (8,396 LOC Python)
> **Architecture**: Flask 3.0 + SQLAlchemy 2.0 + SQLite → PostgreSQL (planned)

---

## Architecture Summary

| Component            | Technology                          | Notes                                      |
|----------------------|-------------------------------------|---------------------------------------------|
| Web Framework        | Flask 3.0 (dev server, single proc) | No Gunicorn/WSGI in current setup           |
| Database             | SQLite (StaticPool, single file)    | PostgreSQL migration planned                |
| ORM                  | SQLAlchemy 2.0 declarative          | 6 tables, 14 indexes                        |
| AI Inference         | Remote APIs (no local models)       | Cerebras, OpenRouter, Chutes, Ollama (opt.) |
| Encryption           | ChaCha20-Poly1305 (PyCryptodome)    | API keys encrypted at rest                  |
| Memory System        | Semantic + episodic + segments      | LargeBinary embeddings, FSRS decay          |
| Image Generation     | Chutes API (Hunyuan)                | Results stored locally as PNG               |
| Vision               | Kimi-K2.5 via OpenRouter            | Base64 image encoding in memory             |
| Web Search           | DuckDuckGo HTML scraping            | BeautifulSoup parsing                       |
| Streaming            | Server-Sent Events (SSE)            | Long-lived HTTP connections                 |
| Static Assets        | Flask send_from_directory           | CSS ~120 KB, JS ~128 KB, templates ~84 KB   |

---

## Resource Analysis

### CPU

The application is **I/O-bound**, not CPU-bound. Key CPU consumers:

| Operation                | CPU Impact | Frequency          |
|--------------------------|------------|--------------------|
| Flask request handling   | Minimal    | Per request        |
| ChaCha20 encrypt/decrypt | Negligible | API key read/write |
| BeautifulSoup parsing    | Low        | Per web search     |
| Base64 image encoding    | Low-Medium | Per vision message |
| SQLAlchemy ORM queries   | Low        | Per message        |
| Memory scoring/decay     | Low        | Per retrieval      |
| JSON serialization       | Negligible | Per response       |

**No local ML inference is run.** All AI computation is offloaded to remote APIs. The CPU primarily waits on network I/O (API calls to Cerebras/OpenRouter/Chutes typically take 2–30 seconds per request).

### Memory (RAM)

| Consumer                        | Estimated Usage          | Notes                                      |
|----------------------------------|--------------------------|---------------------------------------------|
| Python interpreter + Flask       | 50–80 MB                 | Base process                                |
| SQLAlchemy engine + sessions     | 10–30 MB                 | StaticPool, single connection               |
| Loaded modules (rich, PIL, etc.) | 20–40 MB                 | Import overhead                             |
| Per-request overhead             | 5–20 MB per active req   | Message context, API payloads               |
| Base64 image buffers (vision)    | 2–10 MB per image        | 3-turn visual context buffer                |
| SSE streaming connections        | 1–3 MB per stream        | Generator + HTTP connection held open       |
| Memory retrieval pipeline        | 5–15 MB                  | Loads all session memories for scoring      |
| Image generation response        | 1–5 MB                   | Full PNG in memory before disk write        |
| **Idle baseline**                | **~120–180 MB**          | No active requests                          |
| **Per concurrent user**          | **+20–50 MB**            | During active chat with vision              |

### Storage

| Item                     | Current Size | Growth Rate             | Notes                             |
|--------------------------|--------------|-------------------------|-----------------------------------|
| Application code         | ~1 MB        | Stable                  | 8,396 lines Python                |
| SQLite database          | 3.3 MB       | ~1–5 MB/month           | Messages, memories, profiles      |
| Static assets (CSS/JS)   | ~250 KB      | Stable                  | Frontend files                    |
| Generated images         | 23 MB        | ~50–200 MB/month        | AI-generated PNGs (~1–3 MB each)  |
| Cached images            | 4.8 MB       | ~10–50 MB/month         | Downloaded external images        |
| Uploaded images          | 2.5 MB       | ~10–100 MB/month        | User uploads                      |
| Debug logs               | Variable     | ~1–10 MB/month          | Debug output files                |
| Python dependencies      | ~200 MB      | Stable (after install)  | Virtual environment               |
| **Total baseline**       | **~250 MB**  |                         | Without venv                      |

**With PostgreSQL migration**: Add 200–500 MB for PostgreSQL data directory + WAL files + indexes. Database will grow faster due to JSONB semantic references and proper indexing overhead.

### Network / Bandwidth

| Operation              | Per-Request Size | Direction | Frequency             |
|------------------------|------------------|-----------|-----------------------|
| Chat API call          | 2–50 KB          | Outbound  | Every message         |
| Chat API response      | 1–30 KB          | Inbound   | Every message         |
| Streaming SSE          | 1–30 KB          | Inbound   | Chunked, per message  |
| Image generation       | ~1–3 MB          | Inbound   | Per image request     |
| Vision (base64 upload) | 0.5–5 MB         | Outbound  | Per image in context  |
| Web search (DDG)       | 5–20 KB          | Both      | Per search tool call  |
| Static asset serving   | 100–500 KB       | Outbound  | Per page load         |

**Estimated monthly bandwidth** (per user):

| Load Level | Messages/day | Est. Monthly Bandwidth |
|------------|--------------|------------------------|
| Light      | 20–50        | 500 MB – 1 GB         |
| Normal     | 50–200       | 1–5 GB                |
| Heavy      | 200–500+     | 5–15 GB               |

---

## Load Profiles

### Light Load (1–2 concurrent users, casual use)
- 20–50 messages per day
- Occasional image generation (1–3/day)
- Rare vision/multimodal usage
- Web search 2–5 times/day

### Normal Load (3–5 concurrent users, regular use)
- 100–300 messages per day
- Regular image generation (5–15/day)
- Moderate vision usage (10–20 images/day)
- Web search 10–20 times/day

### Heavy Load (5–10+ concurrent users, intensive use)
- 500+ messages per day
- Frequent image generation (20–50/day)
- Heavy vision usage (50+ images/day)
- Web search 30+ times/day
- Multiple simultaneous SSE streams

---

## Server Specification Table

### Current Architecture (SQLite, Flask dev server)

| Resource       | Minimum               | Recommended           | Comfortable Production |
|----------------|-----------------------|-----------------------|------------------------|
| **CPU**        | 1 core / 1 vCPU       | 2 cores / 2 vCPU      | 4 cores / 4 vCPU       |
| **RAM**        | 512 MB                | 1 GB                  | 2 GB                   |
| **Storage**    | 2 GB                  | 10 GB                 | 50 GB                  |
| **Bandwidth**  | 5 Mbps                | 20 Mbps               | 50 Mbps                |
| **Network**    | Stable internet       | Low-latency broadband | Dedicated line         |
| **OS**         | Linux (any)           | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 LTS |
| **Python**     | 3.9+                  | 3.11+                 | 3.12+                  |
| **Users**      | 1–2 concurrent        | 3–5 concurrent        | 5–10 concurrent        |

### With PostgreSQL Migration (Production-Ready)

| Resource       | Minimum               | Recommended           | Comfortable Production |
|----------------|-----------------------|-----------------------|------------------------|
| **CPU**        | 2 cores / 2 vCPU      | 4 cores / 4 vCPU      | 8 cores / 8 vCPU       |
| **RAM**        | 1 GB                  | 2 GB                  | 4 GB                   |
| **Storage**    | 10 GB (SSD)           | 30 GB (SSD)           | 100 GB (NVMe SSD)      |
| **Bandwidth**  | 10 Mbps               | 50 Mbps               | 100 Mbps               |
| **Network**    | Stable internet       | Low-latency broadband | Dedicated + CDN        |
| **Database**   | PostgreSQL 14+        | PostgreSQL 15+        | PostgreSQL 16+         |
| **WSGI**       | Gunicorn (2 workers)  | Gunicorn (4 workers)  | Gunicorn (8–16 workers)|
| **Reverse Proxy** | —                 | Nginx                 | Nginx + CDN            |
| **OS**         | Ubuntu 22.04+         | Ubuntu 24.04 LTS      | Ubuntu 24.04 LTS       |
| **Python**     | 3.10+                 | 3.11+                 | 3.12+                  |
| **Users**      | 5–10 concurrent       | 10–30 concurrent      | 30–100 concurrent      |

### With Local Ollama Models (Self-Hosted Inference)

If running local models via Ollama on the same server, add these **on top** of the above:

| Resource       | Small Models (≤7B)    | Medium Models (13–34B)| Large Models (70B+)    |
|----------------|-----------------------|-----------------------|------------------------|
| **CPU**        | +4 cores              | +8 cores              | GPU required           |
| **RAM**        | +8 GB                 | +24 GB                | +48 GB                 |
| **GPU (opt.)** | —                     | 8 GB VRAM             | 24+ GB VRAM            |
| **Storage**    | +10 GB                | +30 GB                | +80 GB                 |

---

## Cloud Instance Equivalents

| Tier                 | AWS               | GCP                  | Hetzner           | DigitalOcean      |
|----------------------|-------------------|----------------------|-------------------|-------------------|
| **Minimum**          | t3.micro          | e2-micro             | CX22              | Basic 1 GB        |
| **Recommended**      | t3.small          | e2-small             | CX32              | Basic 2 GB        |
| **Production**       | t3.medium         | e2-medium            | CX42              | Basic 4 GB        |
| **Prod + PostgreSQL**| m6i.large         | n2-standard-4        | CX52              | Premium 8 GB      |

---

## Key Bottlenecks & Scaling Notes

1. **Flask dev server is single-threaded** — the primary concurrency bottleneck. Migrate to Gunicorn with multiple workers for production.

2. **SQLite StaticPool limits concurrency** — only one connection at a time. PostgreSQL migration removes this bottleneck entirely.

3. **SSE streams hold connections open** — each streaming chat response occupies a thread/worker for 2–30+ seconds. Size worker count accordingly (2× expected concurrent streams).

4. **Image storage grows unbounded** — implement rotation/cleanup or external storage (S3) for generated/cached images. At 50 images/day × 2 MB average = ~3 GB/month.

5. **Memory retrieval loads all session memories** — retrieval queries scan all semantic/episodic records per session. Add pagination or caching as memory tables grow beyond 10,000 rows.

6. **No rate limiting exists** — add Flask-Limiter or Nginx rate limiting before production exposure.

7. **No connection pooling for external APIs** — each API call creates a new `requests` connection. Consider `requests.Session()` or `httpx` with connection pooling for high throughput.

8. **Encryption key stored in plaintext file** — move to environment variables or a secrets manager (HashiCorp Vault, AWS Secrets Manager) for production.

---

## Production Readiness Checklist

- [ ] Replace Flask dev server with Gunicorn (+ Nginx reverse proxy)
- [ ] Migrate SQLite → PostgreSQL with proper connection pooling
- [ ] Add Redis for session management and response caching
- [ ] Implement image storage cleanup / external storage (S3)
- [ ] Add rate limiting (Flask-Limiter or Nginx)
- [ ] Move encryption key to environment variable / secrets manager
- [ ] Enable HTTPS (Let's Encrypt / Cloudflare)
- [ ] Add health check endpoint (`/health`)
- [ ] Set up monitoring (Prometheus + Grafana or similar)
- [ ] Configure log rotation for debug_logs/
- [ ] Add Celery for background tasks (memory decay, image cleanup)
- [ ] Implement database backup strategy

---

## Methodology

Requirements were derived from:

- Static analysis of all 8,396 lines of Python source code
- Dependency audit of 12 core packages (requirements.txt)
- Measurement of current storage usage (DB: 3.3 MB, static: 31 MB)
- Analysis of API payload sizes across 4 providers (62+ model configurations)
- Memory system architecture review (3 table types, scoring pipeline)
- SSE streaming connection lifecycle analysis
- Image pipeline sizing (generation, caching, uploads, base64 encoding)
- SQLAlchemy connection pool configuration review (StaticPool)
- Threading model analysis (single daemon thread, no worker pool)
