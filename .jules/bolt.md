## 2024-05-24 - Optimize Deduplication SequenceMatcher
**Learning:** Checking title similarity with `SequenceMatcher` in an O(N^2) loop is extremely slow. We can avoid expensive standard library text similarity calculations when it's mathematically impossible for two strings to meet the similarity threshold based on their lengths alone (`2 * min_len / sum_lens <= threshold`).
**Action:** Always add an exact match and a mathematical bounds check (based on string length) before invoking expensive text similarity functions like `SequenceMatcher` in inner loops.

## 2024-10-24 - SequenceMatcher reuse in tight loop
**Learning:** Instantiating `SequenceMatcher` inside nested loops is extremely slow due to repeated initialization overhead.
**Action:** Always instantiate `SequenceMatcher` outside the loop, update the target sequence using `.set_seq2(seen)`, and use `.quick_ratio()` and `.real_quick_ratio()` for fast early-abort before calculating the expensive `.ratio()`.
