# `app/core/`

Shared cross-domain infrastructure. Place security, encryption, runtime context, configuration primitives, logging, presets, and other reusable utilities here.

Core modules must remain independent of HTTP handlers and UI presentation. Do not place provider API calls, tool schemas, or feature-specific business workflows here.
