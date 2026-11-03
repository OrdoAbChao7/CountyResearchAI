## 2024-05-24 - Optimize Deduplication SequenceMatcher
**Learning:** Checking title similarity with `SequenceMatcher` in an O(N^2) loop is extremely slow. We can avoid expensive standard library text similarity calculations when it's mathematically impossible for two strings to meet the similarity threshold based on their lengths alone (`2 * min_len / sum_lens <= threshold`).
**Action:** Always add an exact match and a mathematical bounds check (based on string length) before invoking expensive text similarity functions like `SequenceMatcher` in inner loops.

## 2024-05-24 - SequenceMatcher.ratio() Bottleneck
**Learning:** `difflib.SequenceMatcher.ratio()` is O(N²) and can be a significant bottleneck when used inside nested loops (e.g., deduplicating a list of titles).
**Action:** Always short-circuit `ratio()` calls by checking `real_quick_ratio()` (O(1)) and `quick_ratio()` (O(N)) first, as they provide an upper bound for the final ratio.
