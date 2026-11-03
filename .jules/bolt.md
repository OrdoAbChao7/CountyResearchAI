## 2024-05-24 - Optimize Deduplication SequenceMatcher
**Learning:** Checking title similarity with `SequenceMatcher` in an O(N^2) loop is extremely slow. We can avoid expensive standard library text similarity calculations when it's mathematically impossible for two strings to meet the similarity threshold based on their lengths alone (`2 * min_len / sum_lens <= threshold`).
**Action:** Always add an exact match and a mathematical bounds check (based on string length) before invoking expensive text similarity functions like `SequenceMatcher` in inner loops.

## 2024-05-24 - Optimize difflib.SequenceMatcher in nested loops
**Learning:** Instantiating `difflib.SequenceMatcher` inside a nested loop is a massive O(N^2) bottleneck because it rebuilds internal caching structures for every comparison. Calculating `.ratio()` immediately without checking upper bounds is also inefficient for strings that are vastly different in length or character composition.
**Action:** Always reuse a single `SequenceMatcher` instance using `.set_seq1()` and `.set_seq2()`. Implement O(1) length checks (`2.0 * min(len_a, len_b) / (len_a + len_b)`) and O(N) `quick_ratio()` checks to prune expensive comparisons before falling back to O(N^2) `.ratio()`.
