## 2024-10-24 - SequenceMatcher reuse in tight loop
**Learning:** Instantiating `SequenceMatcher` inside nested loops is extremely slow due to repeated initialization overhead.
**Action:** Always instantiate `SequenceMatcher` outside the loop, update the target sequence using `.set_seq2(seen)`, and use `.quick_ratio()` and `.real_quick_ratio()` for fast early-abort before calculating the expensive `.ratio()`.
