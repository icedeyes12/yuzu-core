# `app/tools/`

Native function-calling definitions and structured tool dispatch. Tool modules define schemas, argument validation, and the structured execution contract consumed by `app/tools/registry.py`.

Keep provider HTTP execution in `app/providers/`. Tools must return structured data and must not format Markdown, HTML, or other UI presentation.