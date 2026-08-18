"""Safe, batch-isolated remediation executor for Yuzuki Graph Memory ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import json
import os
import sys

import psycopg


def apply_remediation(dry_run: bool = True) -> None:
    manifest_path = (
        "/root/home/workspace/yuzu-core/docs/audit/remediation_manifest.json"
    )
    if not os.path.exists(manifest_path):
        print(f"Manifest not found at {manifest_path}")
        return

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    proposals = manifest.get("proposals", [])
    print(f"Loaded {len(proposals)} proposals. Running with dry_run={dry_run}...")

    dsn = "postgresql://reina:NyanPass123@100.85.113.57:5433/yuzuki"
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            batch_size = 50
            merged_count = 0
            superseded_count = 0
            evidence_redirected_count = 0

            for i in range(0, len(proposals), batch_size):
                batch = proposals[i : i + batch_size]
                if not dry_run:
                    conn.execute("SAVEPOINT batch_remediation")

                try:
                    for entry in batch:
                        mem_id = entry["memory_id"]
                        can_id = entry["canonical_id"]
                        action = entry["action"]
                        user_id = entry["affected_user_id"]

                        if dry_run:
                            continue

                        # 1. Redirect Evidence Provenance to Canonical Node
                        cur.execute(
                            """
                            UPDATE memory_evidence
                            SET node_id = %s
                            WHERE user_id = %s AND node_id = %s
                            RETURNING id;
                        """,
                            (can_id, user_id, mem_id),
                        )
                        evidence_redirected_count += len(cur.fetchall())

                        # 2. Update Node Status to Archived with Supersession Pointer
                        cur.execute(
                            """
                            UPDATE memory_nodes
                            SET status = 'archived',
                                valid_until = NOW(),
                                supersedes_node_id = %s,
                                updated_at = NOW()
                            WHERE id = %s AND user_id = %s AND status = 'active';
                        """,
                            (can_id, mem_id, user_id),
                        )

                        if action == "MERGE":
                            merged_count += 1
                        else:
                            superseded_count += 1

                    if not dry_run:
                        conn.execute("RELEASE SAVEPOINT batch_remediation")
                        conn.commit()
                except Exception as e:
                    if not dry_run:
                        conn.execute("ROLLBACK TO SAVEPOINT batch_remediation")
                    print(f"Error in batch {i}: {e}")
                    raise

            print("\n=== REMEDIATION SUMMARY ===")
            print(f"Dry Run: {dry_run}")
            print(f"Proposals Evaluated: {len(proposals)}")
            if not dry_run:
                print(f"Nodes Archived/Superseded: {superseded_count}")
                print(f"Nodes Merged: {merged_count}")
                print(
                    f"Evidence Links Preserved/Redirected: {evidence_redirected_count}"
                )


if __name__ == "__main__":
    dry_run_mode = True
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        dry_run_mode = False
    apply_remediation(dry_run=dry_run_mode)
