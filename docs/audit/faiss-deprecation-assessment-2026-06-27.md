# FAISS Deprecation Assessment - 2026-06-27

## Current State

- `app/core/faiss_store.py` imports `FAISS` from `langchain_community.vectorstores` (line 13).
- **Exact deprecation warning message** (emitted at Python import time with `-W all`):

  ```
  DeprecationWarning: `langchain-community` is being sunset and is no longer actively maintained.
  See https://github.com/langchain-ai/langchain-community/issues/674 for details and migration
  guidance toward standalone integration packages.
  ```

- **langchain-community version installed:** `0.4.2`
- The warning fires once per interpreter session whenever any symbol is imported from `langchain_community`, not only FAISS. It is a package-level sunset notice, not a specific API removal warning.
- Backend tests pass; pytest surfaces this as a `DeprecationWarning` but does not fail.

## Installed Package Inventory (relevant)

| Package | Version | Notes |
|---|---|---|
| `langchain-community` | 0.4.2 | Sunset; still functional |
| `faiss-cpu` | 1.14.3 | C++ FAISS library; no LangChain wrapper |
| `langchain-classic` | 1.0.8 | Re-exports `FAISS` but itself emits a `LangChainDeprecationWarning` pointing back to `langchain_community` |
| `langchain-core` | 1.4.8 | No FAISS vectorstore class |

No dedicated standalone `langchain-faiss` (or equivalent) package is installed. The only functional, non-warning path for `LangchainFAISS` today remains `langchain_community.vectorstores.FAISS`.

## Risk

- **No functional failure today.** The `langchain_community` package at version `0.4.2` is still fully functional; the warning is a policy sunset notice, not an API removal.
- **Medium-term risk:** The LangChain team has signalled `langchain-community` will eventually stop receiving updates. If a bug or security fix is needed in the FAISS integration layer, no patch will come through `langchain-community`. Migration to a standalone package would be required at that point.
- **Migration risk is low in isolation:** `faiss-cpu 1.14.3` is already installed. A hypothetical standalone `langchain-faiss` package (if/when published) would wrap the same binary. The surface used by `faiss_store.py` is limited (`FAISS.from_texts`, `FAISS.load_local`, `FAISS.save_local`, `similarity_search_with_score`, `add_texts`, `delete`) — all standard LangChain vectorstore interface methods.
- **Do NOT migrate today:** No stable, warning-free standalone FAISS integration package exists in the current venv without adding new dependencies. Adding an untested dependency mid-sprint risks breaking the passing test suite.

## Recommendation

1. **No production code change required at this time.** Continue using `langchain_community.vectorstores.FAISS` until a stable, officially published standalone package (e.g., `langchain-faiss`) is available on PyPI.
2. **Monitor** the upstream tracking issue: https://github.com/langchain-ai/langchain-community/issues/674
3. **When a standalone package is released**, migration will be confined to a single import line in `app/core/faiss_store.py`:
   ```python
   # Before
   from langchain_community.vectorstores import FAISS as LangchainFAISS
   # After (hypothetical)
   from langchain_faiss import FAISS as LangchainFAISS
   ```
   No other logic changes should be needed because only standard vectorstore interface methods are used.
4. **Track migration separately** from lint/type/data repair work to avoid scope creep.
5. **Re-run full backend tests** after any future migration:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   ```

## Verification

- `.\.venv\Scripts\python.exe -m pytest -q` currently passes (excluding known Windows file-lock failures).
- Deprecation warning confirmed reproducible:
  ```powershell
  .\.venv\Scripts\python.exe -W all -c "from langchain_community.vectorstores import FAISS"
  ```
- No alternative warning-free import path exists in the current environment without new dependencies.
