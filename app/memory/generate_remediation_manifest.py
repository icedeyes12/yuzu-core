"""Dry-run script to generate deterministic memory remediation manifest ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import json
import os

import psycopg


def generate_manifest() -> dict[str, object]:
    dsn = "postgresql://reina:NyanPass123@100.85.113.57:5433/yuzuki"
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, node_type, content, confidence, importance, created_at
                FROM memory_nodes
                WHERE status = 'active'
                ORDER BY content ASC;
            """
            )
            rows = cur.fetchall()

            # Deterministic grouping by normalized Subject + Predicate
            clusters: dict[tuple[str, str], list[tuple]] = {}
            for r in rows:
                content = str(r[3])
                words = content.split()
                if len(words) >= 3:
                    key = (words[0].lower(), words[1].lower())
                    clusters.setdefault(key, []).append(r)

            manifest_entries = []

            for (subject, predicate), items in clusters.items():
                if len(items) <= 1:
                    continue

                # Sort by created_at DESC -> Latest node becomes Canonical Candidate
                items_sorted = sorted(items, key=lambda x: x[6], reverse=True)
                canonical = items_sorted[0]
                canonical_id = str(canonical[0])

                # Check duplicates and older superseded variants
                for item in items_sorted[1:]:
                    item_id = str(item[0])
                    item_content = str(item[3])
                    can_content = str(canonical[3])

                    # Action classification: MERGE (exact duplicate idea) vs SUPERSEDE (temporal evolution)
                    action = "SUPERSEDE"
                    reason = f"Temporal evolution under predicate ({subject} {predicate}); superseded by newer canonical record."
                    confidence = 0.90

                    if item_content.lower() == can_content.lower():
                        action = "MERGE"
                        reason = "Exact/normalized semantic duplicate."
                        confidence = 0.99

                    manifest_entries.append(
                        {
                            "memory_id": item_id,
                            "content": item_content,
                            "action": action,
                            "canonical_id": canonical_id,
                            "canonical_content": can_content,
                            "reason": reason,
                            "confidence": confidence,
                            "affected_user_id": str(item[1]),
                            "created_at": item[6].isoformat(),
                        }
                    )

            return {
                "version": "1.0",
                "generated_for": "yuzuki_companion_memory_remediation",
                "total_active_nodes": len(rows),
                "remediation_proposals_count": len(manifest_entries),
                "proposals": manifest_entries,
            }


if __name__ == "__main__":
    manifest = generate_manifest()
    out_path = os.path.expanduser(
        "/root/home/workspace/yuzu-core/docs/audit/remediation_manifest.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(
        f"Manifest successfully generated with {manifest['remediation_proposals_count']} proposals at {out_path}!"
    )
