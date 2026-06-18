# remittance_recon

## Testing

See **[TESTING.md](TESTING.md)** for the full testing guide.

Quick start:
```bash
# Fast check — no real Excel files needed (~3s)
pytest tests/test_reconciliation.py tests/test_reconciliation_extended.py \
       tests/test_pipeline_unit.py tests/test_pipeline_extended.py \
       tests/test_file_watcher.py tests/test_schema.py \
       tests/test_queries_extended.py tests/test_ai_chat.py \
       tests/test_name_match.py tests/test_name_match_extended.py \
       tests/test_payroll_parser_extended.py tests/test_remittance_parser_extended.py

# Full suite including live-file integration tests
pytest tests/ -v
```

| Test tier | Files | Requires real Excel? |
|-----------|-------|----------------------|
| Tier 1 — Unit/Synthetic | `*_extended.py`, `test_file_watcher.py`, `test_schema.py`, `test_pipeline_unit.py`, `test_ai_chat.py` | ❌ No |
| Tier 2 — Live Integration | `test_payroll_parser.py`, `test_remittance_parser.py`, `test_pipeline.py`, `test_queries.py`, `test_evv_tracker_validation.py` | ✅ Yes |
