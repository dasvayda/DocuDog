# DocuDog regression fixtures

Short sample documents for manual smoke and `tools/regression_smoke.py`.
Each file is padded to exceed the default `file_filters.size_limit.min_bytes` (1024).

## Manual smoke (real backend)

From the repo root, with `config.json` configured:

```powershell
python tools/classify_one.py fixtures/sample_internal_memo.md
python tools/classify_one.py fixtures/sample_internal_memo.md
# second run: outcome skipped_unchanged (same content hash)
```

Edit the file and run again — expect `analyzed`.

## Automated regression (mock, no LLM)

```powershell
python tools/regression_smoke.py
```

Covers: first classify -> hash skip -> append edit -> reclassify.
