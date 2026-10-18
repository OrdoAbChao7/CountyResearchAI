# Pilot status correction

This batch originally wrote groups A and B as `VALID`. A post-run audit found that the legacy settlement path allowed actual Gemini usage to exceed the local pilot capacity: 45,641 tokens were settled against a 24,000-token limit.

The two manifests were corrected to `INVALID_RESOURCE_ACCOUNTING`. Their reports and source files are retained as raw failure evidence and must not enter quality comparison. Group C was recorded as `BLOCKED` when the same resource budget was exhausted.

The pilot also exposed an input bug: the execution helper used a legacy fallback focus (`脐橙产业`) for non-development counties instead of the frozen 于都县 focus (`电子信息与纺织服装`). This makes the entire pilot unsuitable for quality comparison independently of the resource overrun.

The Resource Manager now rejects an over-capacity settlement and records an `overrun` lease before raising `ResourceExhaustedError`.
