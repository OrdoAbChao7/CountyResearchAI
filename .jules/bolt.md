## 2024-05-24 - Optimize Deduplication SequenceMatcher
**Learning:** Checking title similarity with `SequenceMatcher` in an O(N^2) loop is extremely slow. We can avoid expensive standard library text similarity calculations when it's mathematically impossible for two strings to meet the similarity threshold based on their lengths alone (`2 * min_len / sum_lens <= threshold`).
**Action:** Always add an exact match and a mathematical bounds check (based on string length) before invoking expensive text similarity functions like `SequenceMatcher` in inner loops.

## 2024-05-18 - [Optimize SequenceMatcher in O(N^2) loops]
**Learning:** `difflib.SequenceMatcher(None, a, b).ratio()` creates a new object and computes the expensive longest common subsequence algorithm each time. In an O(N^2) similarity deduplication pass, this is a significant bottleneck.
**Action:** When comparing a string `b` against many strings `a` in a loop, reuse `matcher = SequenceMatcher(b=title)`. In the inner loop, use `matcher.set_seq1(seen)`, and check `matcher.real_quick_ratio()` and `matcher.quick_ratio()` upper bounds before calling `ratio()` to exit early for dissimilar strings.
