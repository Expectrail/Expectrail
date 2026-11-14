"""Stable failure codes for a review, so a missing tool, a provider error, a timeout and a real
behavioral failure are never confused.

    classify(TimeoutError("replay timed out"), stage="base")["code"] == "EXECUTION_TIMEOUT"

The exception's type decides first; its message is read only as a fallback. An exception is never
classified as BEHAVIOR_FAILED: that code is for a check that ran to completion and failed
(behavior_failed), never for a crash, which says nothing about how the game behaves.
"""
from __future__ import annotations

import re
import subprocess

# code: (what it means, what to do about it)
CODES: dict[str, tuple[str, str]] = {
    "INPUT_INVALID": ("the request, a patch or a file is invalid or missing; nothing ran",
                      "fix the input and run the review again in a new folder"),
    "PATCH_SCOPE_BLOCKED": ("the candidate edits paths outside the request's editable paths",
                            "a fix may only edit the paths the request allows"),
    "TOOL_MISSING": ("a required program or display support is missing; execution is incomplete",
                     "install it (./harness/get_godot.sh, xvfb) and run again"),
    "PRIVATE_SUITE_UNAVAILABLE": ("the private routes could not be loaded, so there is no full acceptance",
                                  "mount the private set on the verifier's machine"),
    "PROVIDER_FAILED": ("a model provider failed (authentication, rate limit, quota, endpoint); "
                        "this is not a behavioral failure",
                        "check the key and the provider's status, then run again"),
    "OBSERVATION_INVALID": ("an observation is missing, malformed or uncertain; the check needs review",
                            "look at the stage's error file; never read a missing observation as a pass"),
    "EXECUTION_TIMEOUT": ("a replay or an observation ran past its deadline; the evidence is incomplete",
                          "run again; if it repeats, the route or the provider is too slow"),
    "BASE_MISMATCH": ("the game differs from the request's base, so the arms cannot be compared",
                      "make the request against this checkout"),
    "EVIDENCE_MISMATCH": ("an artifact, patch, spec or route differs from what the record names",
                          "verify this patch for this request again"),
    "BEHAVIOR_FAILED": ("a required check ran to completion and failed: the candidate is rejected",
                        "the fix does not do what the request asks; see the failing check"),
}

_PROVIDER_TYPES = {"SamError", "GlimmerError", "HTTPError", "URLError", "APIError", "RateLimitError",
                   "APIConnectionError", "APIStatusError", "AuthenticationError"}
_SECRET = re.compile(r"\b(?:msk|sk|ghp|gho|ghs|github_pat|xox[abp])[-_A-Za-z0-9]{12,}")
# (pattern in the message, code): the fallback, in order, when the type decides nothing
_TEXT = (
    (re.compile(r"base\.tree does not match|base tree", re.I), "BASE_MISMATCH"),
    (re.compile(r"timed? ?out|deadline", re.I), "EXECUTION_TIMEOUT"),
    (re.compile(r"held-out|private (set|routes?)", re.I), "PRIVATE_SUITE_UNAVAILABLE"),
    (re.compile(r"\bsam-3|\bsam observations|glimmer|rate limit|\b(401|403|429|5\d\d)\b|quota|api key", re.I),
     "PROVIDER_FAILED"),
    (re.compile(r"godot.*not found|xvfb|no display|cannot open display|command not found", re.I), "TOOL_MISSING"),
)


def redact(text: str, *, limit: int | None = 600) -> str:
    return _SECRET.sub("[redacted]", str(text))[:limit]


def _status(exc: BaseException) -> int | None:
    for attr in ("code", "status", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _by_type(exc: BaseException, stage: str) -> str | None:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "EXECUTION_TIMEOUT"
    if names & _PROVIDER_TYPES:
        return "PROVIDER_FAILED"
    if "ContractError" in names:
        return "INPUT_INVALID"
    if isinstance(exc, FileNotFoundError):
        return "INPUT_INVALID" if stage == "preflight" else "TOOL_MISSING"
    if isinstance(exc, subprocess.CalledProcessError):
        return None  # a crashed replay: its message may say why; otherwise its observations are missing
    return None


def make(code: str, *, stage: str, detail: str = "", exception_type: str | None = None,
         provider_status: int | None = None) -> dict:
    """A diagnostic with the code's own fix. Raises for an unknown code."""
    if code not in CODES:
        raise ValueError(f"unknown diagnostic code {code!r}")
    doc = {"code": code, "stage": stage, "detail": redact(detail or CODES[code][0]), "fix": CODES[code][1]}
    if exception_type:
        doc["exceptionType"] = exception_type
    if provider_status is not None:
        doc["providerStatus"] = provider_status
    return doc


def classify(exc: BaseException | None = None, *, stage: str, detail: str = "") -> dict:
    """The diagnostic for a failure in ``stage``: by exception type first, then by its message."""
    text = detail or (str(exc) if exc is not None else "")
    if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
        text = f"{text} {exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors='replace')}"
    code = _by_type(exc, stage) if exc is not None else None
    if code is None:
        code = next((c for pattern, c in _TEXT if pattern.search(text)), "OBSERVATION_INVALID")
    status = _status(exc) if exc is not None else None
    if status is not None and (status in (401, 403, 408, 429) or status >= 500) and code == "OBSERVATION_INVALID":
        code = "PROVIDER_FAILED"
    return make(code, stage=stage, detail=text, exception_type=type(exc).__name__ if exc is not None else None,
                provider_status=status)


def behavior_failed(check: dict, *, stage: str = "compare") -> dict:
    """The one way to BEHAVIOR_FAILED: a required check that completed with a fail."""
    if check.get("result") != "fail":
        raise ValueError("only a completed check that failed is a behavioral failure")
    return make("BEHAVIOR_FAILED", stage=stage, detail=f"{check['spec']} failed on {check['route']}")
