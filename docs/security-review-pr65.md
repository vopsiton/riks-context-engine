# Security Review — PR #65

**Repo:** `vopsiton/riks-context-engine`
**PR:** #65 — `fix/token-estimation-tiktoken`
**Reviewer:** Rik (security-tester subagent)
**Date:** 2026-04-20

---

## Findings
🟢 Safe

---

## Security Analysis

- [x] **ImportError handling** — 🟢 Safe
  - `_get_tiktoken_encoding()` catches `ImportError` and logs a warning: `"tiktoken not installed. Install with: pip install tiktoken\nFalling back to character-based estimation."`
  - Returns `None` gracefully; no exception propagates. No information disclosure beyond a pip install hint (benign).

- [x] **tiktoken encoding safety** — 🟢 Safe
  - `encoding.encode(text, disallowed_special=())` is used correctly.
  - `disallowed_special=()` tells tiktoken "do not treat any tokens as special/disallowed" — meaning all text encodes without raising exceptions. This is the correct usage for token counting (not for generation/prompting where you'd want to detect special token boundaries).
  - No injection risk; tiktoken is a deterministic tokenizer, not an interpreter.

- [x] **Exception handling** — 🟢 Safe
  - Two layers of protection:
    1. `_get_tiktoken_encoding()` — catches `ImportError` and bare `Exception` → logs → returns `None`
    2. `_estimate_tokens()` — catches `Exception` from `encoding.encode()` → logs warning → falls back to character-based estimation
  - Both paths log at `warning` level only; no sensitive data in log messages.
  - No bare `except` masking; no silent failures.

- [x] **DoS vectors** — 🟢 Safe / 🟡 Info
  - **No rate limiting or input size cap on `_estimate_tokens()`**: very large strings are passed directly to `encoding.encode()`. Tiktoken is a fast pure-Python/C++ tokenizer and is safe for large inputs in typical usage (e.g., a few MB of text). However, if an attacker can cause the application to call `_estimate_tokens()` on extremely large inputs (e.g., multi-100MB strings), this could cause memory or CPU pressure. **Assessment: low risk** in the current context since this is a library function used internally, not a direct user-facing API with untrusted input.
  - The `for model_pattern, enc_name in model_to_encoding.items()` loop is O(n) over a fixed 15-entry dict — negligible.

- [x] **Information disclosure** — 🟢 Safe
  - No sensitive data (API keys, tokens, paths, PII) appears in any error message or log.
  - Minor cosmetic issue: the `\n` in the warning message creates a two-line log output (`"Falling back to..."` on a separate line). Not a security issue.

- [x] **New dependency: `tiktoken>=0.7.0`** — 🟢 Safe
  - Tiktoken is OpenAI's well-maintained, widely-used tokenization library. It has no network I/O, no filesystem access beyond caching, and no privilege escalation vectors.

- [x] **Test assertions** — 🟢 Adequate
  - New tests cover: Turkish, code, mixed-language, CJK, Arabic, empty string, special characters, unknown models.
  - `assert tokens >= 0` and `assert tokens > 0` are loose but sufficient for non-security tests. No false-negative risk to security.
  - `test_get_tiktoken_encoding_helper` conditionally skips if tiktoken unavailable — handled correctly.

- [x] **Type annotation typo** — 🟡 Info (non-security)
  - `_get_tiktoken_encoding() -> tuple[" tiktoken.Encoding", str]` has a leading space: `" tiktoken.Encoding"`. This will be treated as a string forward reference; no runtime impact. Should be `tuple["tiktoken.Encoding", str]` for cleanliness.

---

## Verdict
**APPROVE**

No security blockers. The PR correctly handles tiktoken unavailability, uses `disallowed_special=()` safely, maintains exception safety throughout, and introduces no injection or information disclosure risks.

---

## Comments

1. **Consider adding an input size guard** (low priority): If `_estimate_tokens()` is ever called from a public-facing API, add a max-length check (e.g., 10MB) before calling tiktoken to prevent memory exhaustion. Not needed for internal-only usage.

2. **Fix type annotation typo**: `tuple[" tiktoken.Encoding"` → `tuple["tiktoken.Encoding"` (remove leading space).

3. **Log message formatting**: The `\n` in the ImportError warning creates a multi-line log. Consider either removing the `\n` or using `logger.log(..., extra={" continuation": ...})` pattern if multi-line formatting is intentional.
