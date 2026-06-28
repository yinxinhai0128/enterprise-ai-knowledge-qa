# Claude Code Multi-Agent Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前项目体检发现的质量门禁、本地数据一致性、前端 lint warning，并把 FAISS 依赖弃用风险纳入独立评估。

**Architecture:** 使用 Controller + Executor + Checker 的多 Agent 协作。Controller 只调度、整合和最终验收；Executor 负责单一问题域的修改；Checker 使用独立上下文只读检查 Executor 的改动，避免“自己改自己验”。

**Tech Stack:** FastAPI, LangChain/LangGraph, FAISS, SQLite, pytest, ruff, mypy, React, Vite, Vitest, oxlint.

---

## Controller Rules

- Controller 不直接修改业务代码、测试代码或本地数据。
- 每个 Executor 必须有独立任务边界；同一文件不得被两个 Executor 同时修改。
- 每个 Executor 完成后必须交给对应 Checker，Checker 不允许修改文件，只允许读代码、看 diff、运行验证命令并给出结论。
- 若 Checker 发现问题，Controller 将问题返还给原 Executor 修复，再由 Checker 复验。
- 工作区已有未提交改动，所有 Agent 禁止使用 `git reset --hard`、`git checkout --`、`git clean`、删除未跟踪文件或回滚不属于本任务的改动。
- 涉及 `storage/app.db`、`storage/`、`$HOME/faiss_kb` 的写操作前必须备份。写 `$HOME/faiss_kb` 在受限环境中可能需要用户批准。
- 所有命令优先用 PowerShell；前端脚本用 `npm.cmd`，避免 PowerShell 执行策略拦截 `npm.ps1`。

## Current Evidence

已验证通过：

- `.\.venv\Scripts\python.exe -m pytest -q` -> `120 passed`
- `.\.venv\Scripts\python.exe -m pytest tests\test_ecommerce_business_scenario.py -q` -> `1 passed`
- `.\.venv\Scripts\python.exe -m ruff check tests\test_ecommerce_business_scenario.py` -> `All checks passed!`
- `npm.cmd test` in `frontend` -> `35 passed`
- `npm.cmd run build` in `frontend` -> build succeeded

需要修复：

- `.\.venv\Scripts\python.exe -m ruff check app tests scripts` -> 29 fixable errors, mostly import ordering, unused imports, one-line imports, and f-string without placeholders.
- `.\.venv\Scripts\python.exe -m mypy` -> timed out after 180s, but reported 2 errors in `scripts/test_qa.py` around bytes/str handling.
- `.\.venv\Scripts\python.exe -m app.commands.check_consistency` -> `{"missing_files":1,"missing_vectors":1,"orphan_files":1,"total_issues":3}`.
- Consistency root cause found by read-only inspection: document id `2`, tenant `legacy`, status `indexed`, DB path `D:\企业级AI知识问答系统\storage\79b4b0d2fad8420da052f92d87664d4a_acceptance_stage1.txt`, actual file `D:\企业级AI知识问答系统\storage\documents\legacy\79b4b0d2fad8420da052f92d87664d4a_acceptance_stage1.txt`, FAISS vectors for `(legacy, 2)` are `0` while DB `chunk_count` is `1`.
- `npm.cmd run lint` in `frontend` -> 3 warnings:
  - `frontend/vite.config.ts`: triple-slash reference for `vitest/config`
  - `frontend/src/components/ui/button.tsx`: `buttonVariants` export triggers Fast Refresh warning
  - `frontend/src/components/ui/badge.tsx`: `badgeVariants` export triggers Fast Refresh warning
- pytest warning: `langchain_community.vectorstores.FAISS` package deprecation warning in `app/core/faiss_store.py`.

## Files By Task

- Backend lint/type cleanup:
  - Modify: `app/core/vectorstore.py`
  - Modify: `app/main.py`
  - Modify: `app/services/ingest.py`
  - Modify: `tests/conftest.py`
  - Modify: selected `scripts/*.py`, excluding the data repair script if created by the data Executor.
- Script mypy cleanup:
  - Modify: `scripts/test_qa.py`
  - Modify: `scripts/test_stream.py` only if needed for ruff import cleanup.
- Local data consistency repair:
  - Modify data after backup: `storage/app.db`
  - May modify data after approval/backup: `$HOME/faiss_kb`
  - May create: `backups/consistency-YYYYMMDD-HHMMSS/`
  - No production code changes unless Executor proves a reusable repair command is necessary.
- Frontend lint cleanup:
  - Modify: `frontend/vite.config.ts`
  - Modify: `frontend/src/components/ui/button.tsx`
  - Create: `frontend/src/components/ui/button-variants.ts`
  - Modify: `frontend/src/components/ui/badge.tsx`
  - Create: `frontend/src/components/ui/badge-variants.ts`
- Dependency deprecation assessment:
  - Read: `app/core/faiss_store.py`
  - Read: `requirements.txt`
  - Read: `requirements.lock`
  - May create: `docs/audit/faiss-deprecation-assessment-2026-06-27.md`

---

### Task 0: Controller Preflight

**Files:**
- Read: `CLAUDE.md`
- Read: `docs/superpowers/plans/2026-06-27-claudecode-multiagent-remediation.md`

- [ ] **Step 1: Record worktree state**

Run:

```powershell
git status --short
git branch --show-current
.\.venv\Scripts\python.exe --version
```

Expected:

- Python is `3.12.x`.
- Worktree may be dirty. Record the dirty files in the Controller notes. Do not revert them.

- [ ] **Step 2: Re-run baseline checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ecommerce_business_scenario.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m mypy
Push-Location frontend; npm.cmd test; npm.cmd run build; npm.cmd run lint; Pop-Location
.\.venv\Scripts\python.exe -m app.commands.check_consistency
```

Expected:

- pytest and frontend test/build pass.
- ruff, mypy, consistency, and frontend lint reproduce the issues listed in Current Evidence.

- [ ] **Step 3: Dispatch independent Executors**

Dispatch these in parallel only if they do not edit overlapping files:

- Executor A: Backend and scripts ruff cleanup, excluding `scripts/test_qa.py` and `scripts/test_stream.py`.
- Executor B: `scripts/test_qa.py` and `scripts/test_stream.py` type/lint cleanup.
- Executor C: local consistency repair.
- Executor D: frontend lint cleanup.
- Executor E: FAISS deprecation assessment.

---

### Task 1: Executor A - Backend Ruff Cleanup

**Files:**
- Modify: `app/core/vectorstore.py`
- Modify: `app/main.py`
- Modify: `app/services/ingest.py`
- Modify: `tests/conftest.py`
- Modify: `scripts/check_db.py`
- Modify: `scripts/import_demo_data.py`
- Modify: `scripts/inspect_db_schema.py`
- Modify: `scripts/inspect_queue_schema.py`
- Modify: `scripts/list_documents.py`
- Modify: `scripts/rebuild_hnsw_queue.py`
- Modify: `scripts/reindex_all.py`
- Modify: `scripts/reindex_to_faiss.py`
- Modify: `scripts/test_chroma.py`
- Modify: `scripts/test_chroma2.py`

- [ ] **Step 1: Read the reported files**

Run:

```powershell
Get-Content app\core\vectorstore.py
Get-Content app\main.py
Get-Content app\services\ingest.py
Get-Content tests\conftest.py
Get-Content scripts\check_db.py
Get-Content scripts\import_demo_data.py
Get-Content scripts\inspect_db_schema.py
Get-Content scripts\inspect_queue_schema.py
Get-Content scripts\list_documents.py
Get-Content scripts\rebuild_hnsw_queue.py
Get-Content scripts\reindex_all.py
Get-Content scripts\reindex_to_faiss.py
Get-Content scripts\test_chroma.py
Get-Content scripts\test_chroma2.py
```

Expected:

- You understand whether each ruff error is import ordering, unused import, multiple imports, or f-string without placeholders.

- [ ] **Step 2: Apply automatic ruff fixes only to this task's files**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check app\core\vectorstore.py app\main.py app\services\ingest.py tests\conftest.py scripts\check_db.py scripts\import_demo_data.py scripts\inspect_db_schema.py scripts\inspect_queue_schema.py scripts\list_documents.py scripts\rebuild_hnsw_queue.py scripts\reindex_all.py scripts\reindex_to_faiss.py scripts\test_chroma.py scripts\test_chroma2.py --fix
```

Expected:

- Ruff applies import ordering and unused import fixes.
- No files outside this task's scope are changed.

- [ ] **Step 3: Manually review the diff**

Run:

```powershell
git diff -- app\core\vectorstore.py app\main.py app\services\ingest.py tests\conftest.py scripts\check_db.py scripts\import_demo_data.py scripts\inspect_db_schema.py scripts\inspect_queue_schema.py scripts\list_documents.py scripts\rebuild_hnsw_queue.py scripts\reindex_all.py scripts\reindex_to_faiss.py scripts\test_chroma.py scripts\test_chroma2.py
```

Expected:

- Diff contains mechanical import/f-string cleanup only.
- No business logic is changed.

- [ ] **Step 4: Run scoped verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check app\core\vectorstore.py app\main.py app\services\ingest.py tests\conftest.py scripts\check_db.py scripts\import_demo_data.py scripts\inspect_db_schema.py scripts\inspect_queue_schema.py scripts\list_documents.py scripts\rebuild_hnsw_queue.py scripts\reindex_all.py scripts\reindex_to_faiss.py scripts\test_chroma.py scripts\test_chroma2.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:

- Scoped ruff passes.
- pytest passes.

---

### Task 2: Checker A - Backend Ruff Cleanup Review

**Files:**
- Review only the files changed by Executor A.

- [ ] **Step 1: Inspect Executor A diff**

Run:

```powershell
git diff -- app\core\vectorstore.py app\main.py app\services\ingest.py tests\conftest.py scripts\check_db.py scripts\import_demo_data.py scripts\inspect_db_schema.py scripts\inspect_queue_schema.py scripts\list_documents.py scripts\rebuild_hnsw_queue.py scripts\reindex_all.py scripts\reindex_to_faiss.py scripts\test_chroma.py scripts\test_chroma2.py
```

Expected:

- Changes are mechanical.
- No unrelated refactor.

- [ ] **Step 2: Run independent checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check app\core\vectorstore.py app\main.py app\services\ingest.py tests\conftest.py scripts\check_db.py scripts\import_demo_data.py scripts\inspect_db_schema.py scripts\inspect_queue_schema.py scripts\list_documents.py scripts\rebuild_hnsw_queue.py scripts\reindex_all.py scripts\reindex_to_faiss.py scripts\test_chroma.py scripts\test_chroma2.py
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:

- Both commands pass.

---

### Task 3: Executor B - Script Type Cleanup

**Files:**
- Modify: `scripts/test_qa.py`
- Modify: `scripts/test_stream.py`

- [ ] **Step 1: Read live probe scripts**

Run:

```powershell
Get-Content scripts\test_qa.py
Get-Content scripts\test_stream.py
```

Expected:

- Confirm both scripts are manual live probes, not pytest tests.
- Preserve behavior: generate dev token, call local API, print response or HTTP error body.

- [ ] **Step 2: Fix imports and bytes/str handling in `scripts/test_qa.py`**

Make these changes:

```python
"""快速 QA 端对端测试。"""
import json
import subprocess
import urllib.error
import urllib.request
```

In the `except urllib.error.HTTPError as e:` block, ensure `body` stays a string:

```python
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"HTTP {e.code}: {body[:300]}")
```

Expected:

- No unused `sys` import.
- No bytes assigned to a variable previously inferred as `str`.

- [ ] **Step 3: Fix imports in `scripts/test_stream.py`**

Use separate imports:

```python
"""测试 /qa/stream SSE 端点。"""
import json
import subprocess
import urllib.error
import urllib.request
```

Expected:

- Ruff no longer reports E401 or I001 for this file.

- [ ] **Step 4: Run scoped checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check scripts\test_qa.py scripts\test_stream.py
.\.venv\Scripts\python.exe -m mypy scripts\test_qa.py
```

Expected:

- Scoped ruff passes.
- Scoped mypy for `scripts/test_qa.py` passes.

---

### Task 4: Checker B - Script Type Cleanup Review

**Files:**
- Review: `scripts/test_qa.py`
- Review: `scripts/test_stream.py`

- [ ] **Step 1: Inspect diff**

Run:

```powershell
git diff -- scripts\test_qa.py scripts\test_stream.py
```

Expected:

- Diff only changes imports and HTTP error body decoding.
- Local API URL, token generation, request body, and printed success fields are preserved.

- [ ] **Step 2: Run independent checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check scripts\test_qa.py scripts\test_stream.py
.\.venv\Scripts\python.exe -m mypy scripts\test_qa.py
```

Expected:

- Both commands pass.

---

### Task 5: Executor C - Local Consistency Repair

**Files/Data:**
- Read/modify after backup: `storage/app.db`
- Read/modify after approval/backup if needed: `$HOME/faiss_kb`
- Create: `backups/consistency-YYYYMMDD-HHMMSS/`

- [ ] **Step 1: Back up database and current FAISS directory**

Run:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "backups\consistency-$stamp"
New-Item -ItemType Directory -Force -Path $backup
Copy-Item -LiteralPath storage\app.db -Destination "$backup\app.db"
if (Test-Path "$HOME\faiss_kb") { Copy-Item -LiteralPath "$HOME\faiss_kb" -Destination "$backup\faiss_kb" -Recurse -Force }
```

Expected:

- Backup directory exists.
- `app.db` backup exists.
- FAISS backup exists if `$HOME\faiss_kb` exists.

- [ ] **Step 2: Confirm current consistency problem**

Run:

```powershell
.\.venv\Scripts\python.exe -m app.commands.check_consistency
.\.venv\Scripts\python.exe scripts\list_documents.py
```

Expected:

- `total_issues` is non-zero.
- Document id `2` path points to `storage\79b4b0d2fad8420da052f92d87664d4a_acceptance_stage1.txt`.
- Actual file exists under `storage\documents\legacy\79b4b0d2fad8420da052f92d87664d4a_acceptance_stage1.txt`.

- [ ] **Step 3: Update document id 2 to the actual promoted file path**

Run this one-off repair:

```powershell
@'
import asyncio
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.models.document import Document


async def main() -> None:
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, 2)
        if doc is None:
            raise SystemExit("document id=2 not found")
        current = Path(doc.file_path)
        candidate = current.parent / "documents" / doc.tenant_id / current.name
        if not candidate.is_file():
            raise SystemExit(f"candidate file missing: {candidate}")
        doc.file_path = str(candidate)
        await db.commit()
        print(f"updated doc_id=2 file_path={candidate}")


asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected:

- Command prints `updated doc_id=2 file_path=...storage\documents\legacy\79b4...txt`.

- [ ] **Step 4: Reindex document id 2**

Use the existing service path so FAISS metadata and DB `chunk_count` stay aligned. This may call the configured embedding provider and may write `$HOME\faiss_kb`; get approval if the environment requires it.

Run:

```powershell
@'
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.document import Document
from app.services.ingest import ingest_document


async def main() -> None:
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, 2)
        if doc is None:
            raise SystemExit("document id=2 not found")
        result = await ingest_document(
            doc_id=doc.id,
            file_path=doc.file_path,
            source=doc.filename,
            tenant_id=doc.tenant_id,
            uploaded_by=doc.uploaded_by,
        )
        if not result.success:
            raise SystemExit(result.error_msg or "reindex failed")
        doc.status = "indexed"
        doc.chunk_count = result.chunk_count
        doc.error_msg = None
        await db.commit()
        print(f"reindexed doc_id=2 chunk_count={result.chunk_count}")


asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected:

- Command prints `reindexed doc_id=2 chunk_count=1`.

- [ ] **Step 5: Run consistency check**

Run:

```powershell
.\.venv\Scripts\python.exe -m app.commands.check_consistency
```

Expected:

- Output has `total_issues: 0`.

---

### Task 6: Checker C - Local Consistency Review

**Files/Data:**
- Read only: `storage/app.db`
- Read only: `$HOME/faiss_kb`
- Read only: `backups/consistency-*`

- [ ] **Step 1: Verify backup exists**

Run:

```powershell
Get-ChildItem backups -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 3
```

Expected:

- Latest backup directory contains `app.db`.
- Latest backup directory contains `faiss_kb` if FAISS existed before repair.

- [ ] **Step 2: Verify document id 2 state**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\list_documents.py
```

Expected:

- Document id `2` path points to `storage\documents\legacy\79b4b0d2fad8420da052f92d87664d4a_acceptance_stage1.txt`.
- Path exists.
- Document id `2` status is `indexed`.

- [ ] **Step 3: Verify FAISS vector count for document id 2**

Run:

```powershell
@'
from app.core.faiss_store import get_faiss_store

store = get_faiss_store()
count = 0
if store is not None:
    for doc in store.docstore._dict.values():
        md = doc.metadata
        if str(md.get("tenant_id")) == "legacy" and int(md.get("doc_id", -1)) == 2:
            count += 1
print(count)
'@ | .\.venv\Scripts\python.exe -
```

Expected:

- Prints `1`.

- [ ] **Step 4: Verify full consistency**

Run:

```powershell
.\.venv\Scripts\python.exe -m app.commands.check_consistency
```

Expected:

- Output has `total_issues: 0`.

---

### Task 7: Executor D - Frontend Lint Cleanup

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/button-variants.ts`
- Modify: `frontend/src/components/ui/badge.tsx`
- Create: `frontend/src/components/ui/badge-variants.ts`

- [ ] **Step 1: Remove triple-slash reference from Vite config**

In `frontend/vite.config.ts`, remove this line:

```ts
/// <reference types="vitest/config" />
```

Keep:

```ts
import { defineConfig } from 'vitest/config'
```

Expected:

- Vitest config typing still works through the import.

- [ ] **Step 2: Move button variants into a non-component module**

Create `frontend/src/components/ui/button-variants.ts`:

```ts
import { cva } from 'class-variance-authority'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export { buttonVariants }
```

Update `frontend/src/components/ui/button.tsx`:

```ts
import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
import { buttonVariants } from './button-variants'
```

Remove the inline `const buttonVariants = cva(...)` block from `button.tsx`.

Expected:

- `button.tsx` exports only React component/type exports and re-exports `buttonVariants` only if existing imports require it.

- [ ] **Step 3: Move badge variants into a non-component module**

Create `frontend/src/components/ui/badge-variants.ts`:

```ts
import { cva } from 'class-variance-authority'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground hover:bg-primary/80',
        secondary: 'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive: 'border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80',
        outline: 'text-foreground',
        success: 'border-transparent bg-green-100 text-green-800',
        warning: 'border-transparent bg-yellow-100 text-yellow-800',
        info: 'border-transparent bg-blue-100 text-blue-800',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export { badgeVariants }
```

Update `frontend/src/components/ui/badge.tsx`:

```ts
import * as React from 'react'
import { type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'
import { badgeVariants } from './badge-variants'
```

Remove the inline `const badgeVariants = cva(...)` block from `badge.tsx`.

Expected:

- `badge.tsx` exports only React component/type exports and re-exports `badgeVariants` only if existing imports require it.

- [ ] **Step 4: Search for variant imports and update them**

Run:

```powershell
Push-Location frontend
Get-ChildItem src -Recurse -File | Select-String -Pattern "buttonVariants|badgeVariants"
Pop-Location
```

Expected:

- Any non-component import of `buttonVariants` points to `@/components/ui/button-variants` or a relative equivalent.
- Any non-component import of `badgeVariants` points to `@/components/ui/badge-variants` or a relative equivalent.

- [ ] **Step 5: Run frontend checks**

Run:

```powershell
Push-Location frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
Pop-Location
```

Expected:

- oxlint has 0 errors and 0 warnings.
- Vitest passes.
- Build succeeds.

---

### Task 8: Checker D - Frontend Lint Review

**Files:**
- Review: `frontend/vite.config.ts`
- Review: `frontend/src/components/ui/button.tsx`
- Review: `frontend/src/components/ui/button-variants.ts`
- Review: `frontend/src/components/ui/badge.tsx`
- Review: `frontend/src/components/ui/badge-variants.ts`

- [ ] **Step 1: Inspect diff**

Run:

```powershell
git diff -- frontend\vite.config.ts frontend\src\components\ui\button.tsx frontend\src\components\ui\button-variants.ts frontend\src\components\ui\badge.tsx frontend\src\components\ui\badge-variants.ts
```

Expected:

- Only variant extraction and Vite config reference removal.
- Button and badge class strings are unchanged.

- [ ] **Step 2: Run independent frontend checks**

Run:

```powershell
Push-Location frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
Pop-Location
```

Expected:

- All commands pass.
- oxlint emits 0 warnings.

---

### Task 9: Executor E - FAISS Deprecation Assessment

**Files:**
- Read: `app/core/faiss_store.py`
- Read: `requirements.txt`
- Read: `requirements.lock`
- Create: `docs/audit/faiss-deprecation-assessment-2026-06-27.md`

- [ ] **Step 1: Inspect current FAISS usage**

Run:

```powershell
Get-Content app\core\faiss_store.py
Get-Content requirements.txt
Select-String -Path requirements.lock -Pattern "langchain-community|faiss|langchain"
```

Expected:

- Identify exact imports and package versions.
- Confirm warning comes from `langchain_community.vectorstores.FAISS`.

- [ ] **Step 2: Decide whether this is an immediate code change**

Use these criteria:

- If the installed dependency set contains a stable, compatible standalone FAISS vectorstore package, propose a minimal migration and include exact import/package changes.
- If no installed stable replacement exists, do not change production code in this task.
- Do not suppress the warning unless Checker and Controller agree it is acceptable as a temporary test hygiene measure.

Expected:

- Clear recommendation with no speculative dependency changes.

- [ ] **Step 3: Write assessment doc**

Create `docs/audit/faiss-deprecation-assessment-2026-06-27.md` with:

```markdown
# FAISS Deprecation Assessment - 2026-06-27

## Current State

- `app/core/faiss_store.py` imports `FAISS` from `langchain_community.vectorstores`.
- Backend tests pass, but pytest emits a deprecation warning from `langchain-community`.

## Risk

- This is not a current functional failure.
- It is an upgrade risk because future LangChain package changes may remove or relocate the integration.

## Recommendation

- Keep current implementation unchanged until a stable compatible FAISS integration is confirmed in dependencies.
- Track migration separately from lint/type/data repair work.
- Re-run full backend tests after any future migration.

## Verification

- `.\.venv\Scripts\python.exe -m pytest -q` currently passes.
```

Expected:

- A concrete audit note exists.
- No production code changed by this task unless a stable local replacement was proven.

---

### Task 10: Checker E - FAISS Assessment Review

**Files:**
- Review: `docs/audit/faiss-deprecation-assessment-2026-06-27.md`
- Review if changed: `app/core/faiss_store.py`, `requirements.txt`, `requirements.lock`

- [ ] **Step 1: Inspect diff**

Run:

```powershell
git diff -- docs\audit\faiss-deprecation-assessment-2026-06-27.md app\core\faiss_store.py requirements.txt requirements.lock
```

Expected:

- If only documentation changed, confirm the doc accurately reflects the warning.
- If code/dependencies changed, require evidence from official package docs or installed package metadata and full test results.

- [ ] **Step 2: Run backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:

- pytest passes.

---

### Task 11: Controller Final Integration

**Files:**
- Review all changed files from Executors.

- [ ] **Step 1: Run complete verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.commands.check_consistency
Push-Location frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
Pop-Location
```

Expected:

- ruff passes.
- mypy passes or reaches a known unrelated timeout only after previously reported `scripts/test_qa.py` errors are gone. If it times out, rerun with a longer timeout before accepting.
- pytest passes.
- consistency reports `total_issues: 0`.
- frontend lint/test/build pass.

- [ ] **Step 2: Review final diff for ownership and scope**

Run:

```powershell
git status --short
git diff --stat
git diff -- tests\test_ecommerce_business_scenario.py docs\superpowers\plans\2026-06-27-claudecode-multiagent-remediation.md
```

Expected:

- Final diff contains only intended fixes and the previously added e-commerce scenario test/plan if retained.
- No unrelated user changes are reverted.

- [ ] **Step 3: Produce handoff summary**

Include:

- Which Executor changed which files.
- Which Checker reviewed each change.
- Exact verification command outputs.
- Any remaining warnings or accepted follow-up items.
- Whether local data backup was created and where.

## Suggested Claude Code Controller Prompt

```markdown
You are the Controller for this remediation. Read `CLAUDE.md` and `docs/superpowers/plans/2026-06-27-claudecode-multiagent-remediation.md`.

Follow the plan exactly. Use multi-agent collaboration:

- Dispatch Executor agents for independent task domains.
- Dispatch separate Checker agents after each Executor completes.
- Controller must not directly edit code or data.
- Checkers must not edit files.
- Never let an Executor self-certify its own change.
- Preserve existing dirty worktree changes and do not use destructive git commands.

Start with Task 0. After all Checkers pass, run Task 11 full verification and provide the handoff summary.
```
