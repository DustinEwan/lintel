#!/usr/bin/env python3
"""Call a Decisions-compatible API and validate its typed answers."""

import hashlib
import json
import os
import urllib.error
import urllib.request

from lintel.core import review
from lintel.core.model import SemanticDecision
from lintel.core.ratchet import violation_fingerprint

DEFAULTS = {
    "model": "liquid/d1.2",
    "endpoint": "https://openrouter.ai/api/alpha/decisions",
    "api_key_env": "OPENROUTER_API_KEY",
    "answer_key": "decision",
    "min_confidence": 0.85,
    "timeout": 20,
    "max_findings": 64,
}
MAX_RESPONSE_BYTES = 1_000_000
CRITERIA = {
    "compliant": "The construct is allowed under the declared policy.",
    "violating": "The construct crosses a governed boundary.",
    "needs-human-review": "The evidence is insufficient for an automatic decision.",
}


class DecisionModelError(Exception):
    """Raised when provider output cannot be trusted."""


def _digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _settings(policy):
    return {**DEFAULTS, **(policy.semantic_decision or {})}


def _excerpt(root, source, line):
    if not root or not source or line <= 0:
        return ""
    path = os.path.join(root, source)
    start = max(1, line - 2)
    end = line + 2
    result = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for number, text in enumerate(handle, 1):
                if number >= start:
                    result.append(f"{number}: {text.rstrip()}")
                if number >= end:
                    break
    except OSError as error:
        raise DecisionModelError(f"cannot read finding source: {source}") from error
    return "\n".join(result)


def build_payload(findings, policy, root=None):
    settings = _settings(policy)
    limit = int(settings["max_findings"])
    if len(findings) > limit:
        raise DecisionModelError(
            f"semantic-review findings exceed configured limit of {limit}"
        )
    if not findings:
        return None

    answer_key = str(settings["answer_key"])
    state = {
        "task": "lintel.semantic_review",
        "policy": {
            "excluded_scopes": list(policy.excluded_scopes),
            "boundary_allowed_regions": {
                name: list(regions)
                for name, regions in policy.boundary_allowed_regions.items()
            },
        },
        "findings": [],
    }
    questions = {}
    question_ids = {}
    for finding in findings:
        fingerprint = violation_fingerprint(finding)
        question_id = f"{answer_key}:{fingerprint}"
        question_ids[fingerprint] = question_id
        fields = finding.fields
        state["findings"].append(
            {
                "fingerprint": fingerprint,
                "rule": finding.rule,
                "message": finding.message,
                "module": fields.get("module", ""),
                "source": fields.get("source", ""),
                "line": fields.get("line", 0),
                "reason": fields.get("reason", ""),
                "excerpt": _excerpt(root, fields.get("source", ""), int(fields.get("line") or 0)),
            }
        )
        questions[question_id] = {
            "type": "choice",
            "instructions": (
                "Decide this Lintel semantic-review finding under the declared "
                "architecture policy."
            ),
            "criteria": dict(CRITERIA),
        }
    return {
        "payload": {
            "model": settings["model"],
            "state": state,
            "questions": questions,
        },
        "state": state,
        "settings": settings,
        "question_ids": question_ids,
    }


def _validate_answer(finding, fingerprint, response, bundle):
    settings = bundle["settings"]
    question_id = bundle["question_ids"][fingerprint]
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise DecisionModelError("decision response has no answers object")
    answer = answers.get(question_id)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise DecisionModelError(f"missing choice answer for {question_id}")
    choice = review.normalize_decision(answer.get("choice"))
    if not review.is_decision(choice):
        raise DecisionModelError(f"invalid decision choice for {question_id}: {choice}")
    confidence = answer.get("confidence")
    if confidence is None:
        confidence = (answer.get("probabilities") or {}).get(choice)
    try:
        confidence = review.validate_confidence(confidence)
    except ValueError as error:
        raise DecisionModelError(
            f"invalid decision confidence for {question_id}: {error}"
        ) from error
    threshold = float(settings["min_confidence"])
    if confidence < threshold:
        choice = "needs-human-review"
    model = response.get("model") or settings["model"]
    reason = f"{model} choice={choice} confidence={confidence:.4f}"
    return SemanticDecision(
        fingerprint=fingerprint,
        decision=choice,
        reason=reason,
        confidence=confidence,
        model=str(model),
        schema_version="1",
        evidence_hash=_digest(bundle["state"]),
        state_hash=_digest(bundle["payload"]),
    )


def evaluate(findings, policy, root=None, opener=None):
    """Return validated decisions; any provider failure raises."""
    bundle = build_payload(findings, policy, root)
    if bundle is None:
        return ()
    settings = bundle["settings"]
    api_key = os.environ.get(str(settings["api_key_env"]), "")
    if not api_key:
        raise DecisionModelError(
            f"missing API key in environment: {settings['api_key_env']}"
        )

    body = json.dumps(bundle["payload"], separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        str(settings["endpoint"]),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    transport = opener or urllib.request.urlopen
    try:
        response = transport(request, timeout=int(settings["timeout"]))
        try:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
    except (urllib.error.URLError, OSError) as error:
        raise DecisionModelError(f"decision request failed: {error}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DecisionModelError("decision response exceeds size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecisionModelError("decision response is not valid JSON") from error
    if not isinstance(data, dict) or "error" in data:
        raise DecisionModelError("decision response contains an error")

    decisions = []
    for finding in findings:
        fingerprint = violation_fingerprint(finding)
        decisions.append(_validate_answer(finding, fingerprint, data, bundle))
    return tuple(decisions)
