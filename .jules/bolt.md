## 2024-05-24 - Optimize Deduplication SequenceMatcher
**Learning:** Checking title similarity with `SequenceMatcher` in an O(N^2) loop is extremely slow. We can avoid expensive standard library text similarity calculations when it's mathematically impossible for two strings to meet the similarity threshold based on their lengths alone (`2 * min_len / sum_lens <= threshold`).
**Action:** Always add an exact match and a mathematical bounds check (based on string length) before invoking expensive text similarity functions like `SequenceMatcher` in inner loops.
