# `app/providers/`

External API client implementations. Each provider module owns request construction, authentication from the active BYOK context, response parsing, and provider capability declarations.

Providers are the only home for external provider execution, including image and embedding requests. Do not put provider API calls in `app/tools/`, `app/core/`, or UI code.