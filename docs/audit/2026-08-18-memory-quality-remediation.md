# Yuzuki Graph Memory Data Quality Audit & Remediation Plan (Phase 1)

## Executive Summary

- **Production Node**: Appliance Nubia (`100.85.113.57:5433/yuzuki`) via role `reina`.
- **Total Existing Dataset Size**:
  - `memory_nodes`: **1,335 total rows** (312 `active`, 1,023 `archived`, 0 `deleted`).
  - `episodes`: **30 high-importance narrative summaries** (unbroken historical anchors).
  - `memory_evidence`: **5,315 provenance records** linking nodes/episodes to message turns.
  - `messages`: **14,923 conversation turns** across 56 chat sessions.
- **Data Quality Health Status**: **DEGRADED BUT RECOVERABLE**.
  - No database-level corruption or broken foreign keys found.
  - The 1,023 `archived` nodes represent historical segment rollups from previous migration passes (all safely stamped with `valid_until` timestamps).
  - Among the **312 active fact nodes**, we identified **300 nodes clustered across 10 overlapping subject-predicate buckets** (e.g. 74 `user preference`, 54 `user experience`, 45 `user interest`, 35 `user guideline`, 28 `user goal`).
  - True invalid conversational residue in active nodes is extremely low (< 2%), but **semantic redundancy and historical drift** (e.g. outdated stack references: `Termux + Flask` vs current `FastAPI + PG`) account for ~35% of active memory nodes.

---

## Memory Quality Taxonomy

| Category | Definition | Remediation Strategy |
| :--- | :--- | :--- |
| **CANONICAL_KEEP** | Unique, enduring, highly personal fact or stable identity trait (e.g., location in Cirebon, full name Bani Baskara, GitHub handle icedeyes12). | **KEEP** active. |
| **TEMPORAL_SUPERSEDED** | Historical fact that was true at timestamp $T_1$ but replaced by fact at $T_2$ (e.g., "unemployed looking for PC" $\rightarrow$ "employed as warehouse QC, saving for PC"). | **SUPERSEDE** (`valid_until = NOW(), status = 'archived'`). |
| **SEMANTIC_DUPLICATE** | Paraphrased variants asserting identical facts (e.g., "/imagine must be on the first line" repeated 4 times). | **MERGE** into canonical node, redirecting `memory_evidence` foreign keys. |
| **TRANSIENT_RESIDUE** | Ephemeral mood, single-turn conversational prompt, or temporary state (e.g., explicit camera shot requests). | **INVALIDATE** (`valid_until = NOW(), status = 'archived'`). |

---

## Dataset Findings & Cluster Analysis

### 1. Semantic Duplicate Clusters (Target: MERGE)

#### Cluster A: Tool Execution & Image Generation Directives (`user guideline`)
- **Node `019f8f2f-a020...`**: *"Bani Baskara expects tool commands like '/imagine' to be on the first line..."*
- **Node `019f8f30-d0de-7976...`**: *"Bas expects image generation commands to start with '/imagine' on the first line..."*
- **Node `019f8f2f-b697...`**: *"The user emphasizes that the /imagine command must be on the first line to function properly."*
- **Action**: Merge into single Canonical Node: `User Guideline: Prompt commands (/imagine) must be placed on the first line for correct frontend parser execution.` Redirect 18 evidence records to canonical ID.

#### Cluster B: Geographic Identity (`user identity`)
- **Node `019f8f2f-94da...`**: *"Bani Baskara is based in Cirebon, West Java, Indonesia."*
- **Node `019f8f2f-b102...`**: *"The user is located at latitude -6.4905191, longitude 108.4515524, in the Cirebon/Indramayu area of Indonesia, not Sukabumi."*
- **Action**: Merge into single Canonical Node preserving precise coordinates and province.

### 2. Temporal Drift & Contradiction Clusters (Target: SUPERSEDE)

#### Cluster C: Technology Stack & Infrastructure Evolution
- **Node `019f9398-322c...` (2026-07-24)**: *"user current_tech_stack Termux, Flask, SQLite, SQLAlchemy"*
- **Node `019f9397-f1a3...` (2026-07-24 Episode)**: *"moving from Termux + Flask to a more robust framework like FastAPI for better scalability"*
- **Action**: Supersede older Flask/SQLite stack claims (`valid_until = NOW(), status = 'archived'`) in favor of active architecture (`FastAPI + PostgreSQL on PRoot Debian / Nubia appliance`).

#### Cluster D: Employment & Career Evolution
- **Node `019f926f-96f9...`**: *"User financial_status Currently unemployed with a monthly income/salary of 2.4 million"*
- **Node `019f9398-292c...`**: *"user working_as warehouse man / quantity control for a government program (SPPG)"*
- **Action**: Mark historical node as `status = 'archived', valid_until = '2026-07-24'`, preserving historical narrative while keeping the current employment active.

---

## Graph Integrity Analysis

- **Foreign Key Constraints**: PostgreSQL enforcers (`ON DELETE CASCADE` from `profiles`, `memory_nodes`, `episodes`) are 100% intact.
- **Edge Consistency**: `memory_edges` currently holds 0 active rows (relationship links are primarily maintained through `memory_evidence` and `profiles.session_history`).
- **Provenance Integrity**: 269 active nodes possess 5,315 direct evidence linkages to historical chat turns. Merging nodes MUST execute `UPDATE memory_evidence SET node_id = :canonical_id WHERE node_id = :duplicate_id` before archiving the duplicate.

---

## Remediation Strategy & Safety Gates

1. **Strict Invariant**: Zero Hard Deletions. All pruned or merged records transition to `status = 'archived'` with `valid_until = NOW()` to preserve complete auditability and prevent historical hallucination.
2. **Evidence Preservation**: When merging $N$ nodes into 1 canonical node, all associated `memory_evidence` rows are repointed to the canonical node ID.
3. **Deterministic Staged Pipeline**:
   - **Step 1: Backup Snapshot**: Trigger automated server snapshot of `yuzuki` database.
   - **Step 2: Dry-Run Manifest**: Generate and review JSON manifest containing exact UUID transformations.
   - **Step 3: Transactional Batch Execution**: Execute mutations in atomic batches of 50 nodes with automatic rollback on error.
   - **Step 4: Post-Verification**: Re-run vector index scans and provenance coverage validation.
