---
name: review-style
description: Review text or source files using a concise, evidence-based format with a fixed verification marker. Use when the user asks to review, inspect, critique, or assess a file's correctness, clarity, consistency, or maintainability.
---

# Review Style

Review the requested file from its actual contents and report actionable findings consistently.

## Workflow

1. Read every target file before forming conclusions. Do not infer unseen content.
2. Identify correctness, security, clarity, consistency, and maintainability issues relevant to the file type.
3. Prioritize concrete defects over general style preferences.
4. Cite the relative file path and line number when the available content makes that possible.
5. Do not modify files unless the user explicitly requests fixes.

## Output Format

Begin the final answer with this exact marker:

```text
SKILL-REVIEW-OK:
```

Then provide findings from highest to lowest impact. For each finding include:

- severity: high, medium, or low;
- location: relative path and line when known;
- evidence: what the file actually contains;
- recommendation: the smallest useful correction.

If no actionable issue exists, say so explicitly after the marker and briefly state what was checked. Keep the review concise unless the user requests a detailed audit.
