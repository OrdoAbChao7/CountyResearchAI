## 2024-05-24 - SequenceMatcher.ratio() Bottleneck
**Learning:** `difflib.SequenceMatcher.ratio()` is O(N²) and can be a significant bottleneck when used inside nested loops (e.g., deduplicating a list of titles).
**Action:** Always short-circuit `ratio()` calls by checking `real_quick_ratio()` (O(1)) and `quick_ratio()` (O(N)) first, as they provide an upper bound for the final ratio.
