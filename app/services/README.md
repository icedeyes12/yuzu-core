# `app/services/`

Business logic and orchestration. Services coordinate application workflows between API endpoints, providers, tools, memory, and persistence.

Keep HTTP transport details in `app/api/`, provider request execution in `app/providers/`, shared infrastructure in `app/core/`, and presentation formatting out of backend services.