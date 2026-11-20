# Blind Judge batch failure

This batch is retained as a failed audit artifact and is excluded from quality metrics.

- Failure occurred on the first candidate after one real Judge response.
- The response was not valid JSON (`JSONDecodeError: Unterminated string`).
- One resource lease was settled; no complete `judgements.jsonl` was emitted.
- Recovery: the judge runner now preserves per-judge parse failures and continues the batch under a new batch id.
