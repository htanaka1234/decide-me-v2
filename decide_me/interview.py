from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from decide_me.events import new_entity_id
from decide_me.lifecycle import build_close_summary
from decide_me.protocol import (
    accept_proposal,
    answer_proposal,
    current_bundle,
    defer_decision,
    discover_decision,
    enrich_decision,
    issue_proposal,
    reject_proposal,
    render_question_block,
    resolve_by_evidence,
)
from decide_me.selector import proposal_is_stale, select_next_decision, stop_reached


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "should",
    "the",
    "this",
    "to",
    "use",
    "what",
    "where",
    "with",
}

TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".env",
    ".go",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

IGNORE_DIRS = {
    ".ai",
    ".codex",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

ACCEPT_PATTERN = re.compile(r"^(?:accept|ok)\s+(P-[A-Za-z0-9-]+)$", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"^reject\s+(P-[A-Za-z0-9-]+)(?::?\s*(.*))?$", re.IGNORECASE)
DEFER_PATTERN = re.compile(r"^defer\s+(D-[A-Za-z0-9-]+)(?::?\s*(.*))?$", re.IGNORECASE)
POSITIVE_REPLIES = {
    "agree",
    "agreed",
    "fine",
    "good",
    "lgtm",
    "looks good",
    "makes sense",
    "okay",
    "ok",
    "sounds good",
    "that works",
    "works for me",
    "yes",
    "yep",
}
NEGATIVE_ONLY_REPLIES = {
    "disagree",
    "nah",
    "no",
    "nope",
    "not that",
}
CLAUSE_SPLIT_PATTERN = re.compile(
    r"(?:[;\n]+|,\s+(?=(?:but|and|plus|also|except|unless|only|with|without|before|after|we\b|there\b)\b))",
    re.IGNORECASE,
)
INLINE_CONSTRAINT_PATTERN = re.compile(
    r"\b(only if|only for|unless|except|provided that|as long as|with the constraint that)\b",
    re.IGNORECASE,
)
ANSWER_PREFIX_PATTERN = re.compile(
    r"^(?:yes|yeah|yep|sure|okay|ok|agree|agreed|sounds good|that works|works for me|no|nope|nah|not that)\b[,:-]?\s*",
    re.IGNORECASE,
)
DISCOVERY_PHRASES = (
    "we need",
    "we also need",
    "we still need",
    "need to decide",
    "need a ",
    "need an ",
    "need another ",
    "must decide",
    "must add",
    "must have",
    "should also have",
    "should also support",
    "we should also",
    "there needs to be",
    "there also needs to be",
    "before launch we need",
    "for the mvp we need",
    "for mvp we need",
)
CONSTRAINT_PHRASES = (
    "only if",
    "only for",
    "unless",
    "except",
    "must be",
    "must stay",
    "must remain",
    "cannot",
    "can't",
    "needs to be",
    "has to be",
    "at least",
    "at most",
    "within ",
    "no later than",
    "before ",
    "after ",
)
TRIGGER_PREFIXES = ("if ", "when ", "unless ", "before ", "after ")
DOMAIN_PRIORITY = ("legal", "ops", "data", "technical", "ux", "product", "other")
DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "product": (
        "pricing",
        "billing",
        "tier",
        "plan",
        "feature flag",
        "rollout",
        "roadmap",
        "entitlement",
        "signup",
        "trial",
        "tenant",
        "enterprise plan",
    ),
    "technical": (
        "auth",
        "authentication",
        "password",
        "magic link",
        "login",
        "session",
        "api",
        "endpoint",
        "service",
        "backend",
        "frontend",
        "s3",
        "bucket",
        "smtp",
        "oauth",
        "token",
        "encryption",
        "reset",
        "export",
    ),
    "data": (
        "analytics",
        "metric",
        "metrics",
        "dataset",
        "warehouse",
        "pipeline",
        "report",
        "reporting",
        "csv",
        "parquet",
        "table",
        "schema",
        "retention",
        "export",
        "import",
    ),
    "ux": (
        "ux",
        "ui",
        "screen",
        "modal",
        "form",
        "copy",
        "flow",
        "journey",
        "navigation",
        "onboarding",
        "accessibility",
        "mobile",
    ),
    "ops": (
        "deploy",
        "deployment",
        "monitoring",
        "alert",
        "incident",
        "infra",
        "infrastructure",
        "hosting",
        "region",
        "backup",
        "docker",
        "ci",
        "cd",
        "runbook",
        "logging",
        "retention",
    ),
    "legal": (
        "privacy",
        "legal",
        "compliance",
        "gdpr",
        "contract",
        "terms",
        "consent",
        "policy",
        "soc 2",
        "soc2",
        "residency",
        "dpa",
        "audit",
        "eu",
    ),
}
DEPENDENCY_PHRASES = (
    "integration",
    "provider",
    "vendor",
    "smtp",
    "s3",
    "bucket",
    "webhook",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "host",
    "hosting",
    "region",
    "export",
    "import",
    "sync",
)
RISK_PHRASES = (
    "risk",
    "fallback",
    "mitigation",
    "rollback",
    "outage",
    "failure",
    "abuse",
    "fraud",
    "breach",
    "recovery",
)
LEGAL_CONSTRAINT_PHRASES = (
    "compliance",
    "privacy",
    "contract",
    "residency",
    "gdpr",
    "soc 2",
    "soc2",
    "policy",
    "consent",
)
NOW_PRIORITY_PHRASES = (
    "before launch",
    "before release",
    "before ship",
    "for the mvp",
    "for mvp",
    "required",
    "blocking",
    "blocker",
    "must have",
    "cannot ship",
)
LATER_PRIORITY_PHRASES = (
    "later",
    "post-mvp",
    "eventually",
    "future",
    "after launch",
    "after release",
)
NICE_TO_HAVE_PHRASES = ("nice to have", "optional", "could have")
DOCS_PHRASES = (
    "docs",
    "documentation",
    "document",
    "readme",
    "runbook",
    "playbook",
    "guide",
    "manual",
    "reference",
    "adr",
    "spec",
)
TESTS_PHRASES = (
    "test",
    "tests",
    "unit test",
    "integration test",
    "regression test",
    "e2e",
    "end-to-end",
    "coverage",
    "fixture",
)
CODEBASE_PHRASES = (
    "auth",
    "authentication",
    "password",
    "reset",
    "api",
    "endpoint",
    "service",
    "backend",
    "frontend",
    "config",
    "setting",
    "schema",
    "migration",
    "database",
    "s3",
    "bucket",
    "smtp",
    "oauth",
    "token",
    "encryption",
    "export",
    "import",
    "sync",
    "webhook",
)
EXTERNAL_PHRASES = (
    "legal",
    "privacy",
    "compliance",
    "gdpr",
    "soc 2",
    "soc2",
    "contract",
    "dpa",
    "vendor",
    "procurement",
    "approval",
    "signoff",
    "audit",
    "residency",
)
IRREVERSIBLE_PHRASES = (
    "irreversible",
    "permanent",
    "permanently",
    "cannot undo",
    "can't undo",
    "one-way",
    "destructive",
    "delete all",
    "delete existing",
    "drop data",
    "purge",
)
HARD_TO_REVERSE_PHRASES = (
    "auth",
    "authentication",
    "oauth",
    "encryption",
    "migration",
    "database",
    "schema",
    "residency",
    "privacy",
    "contract",
    "billing",
    "pricing",
    "retention",
    "region",
    "vendor",
    "provider",
)


def advance_session(
    ai_dir: str,
    session_id: str,
    *,
    repo_root: str | Path = ".",
    max_auto_resolutions: int = 20,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    auto_resolved: list[dict[str, Any]] = []

    while True:
        bundle = current_bundle(ai_dir)
        session = _require_session(bundle, session_id)
        if session["session"]["lifecycle"]["status"] == "closed":
            raise ValueError(f"session {session_id} is closed")

        active = session["working_state"]["active_proposal"]
        if active.get("proposal_id"):
            stale, reason = proposal_is_stale(bundle["project_state"], session)
            if not stale:
                decision = _lookup_decision(bundle, active["target_id"])
                return _question_result(
                    session_id=session_id,
                    decision=decision,
                    proposal=active,
                    auto_resolved=auto_resolved,
                    reused_active_proposal=True,
                )
            if active.get("is_active") and active.get("target_id"):
                return {
                    "status": "stale-proposal",
                    "session_id": session_id,
                    "proposal_id": active["proposal_id"],
                    "decision_id": active["target_id"],
                    "stale_reason": reason,
                    "auto_resolved": auto_resolved,
                    "message": _render_stale_proposal_message(active, reason),
                }
            stale_proposal_id = active["proposal_id"]
        else:
            stale_proposal_id = None

        decision_ids = session["session"].get("decision_ids", [])
        decision = select_next_decision(
            bundle["project_state"],
            decision_ids=decision_ids,
            scope="session",
        )
        if decision is None and not decision_ids:
            return {
                "status": "unbound",
                "session_id": session_id,
                "auto_resolved": auto_resolved,
                "message": _render_unbound_message(session_id),
            }
        if decision is None or stop_reached(bundle["project_state"]):
            summary = stopping_summary(bundle, session_id)
            return {
                "status": "complete",
                "session_id": session_id,
                "auto_resolved": auto_resolved,
                "summary": summary,
                "message": _render_complete_message(auto_resolved, summary),
            }

        evidence = find_evidence(bundle, session_id, decision, repo_root)
        if evidence is not None:
            resolve_by_evidence(
                ai_dir,
                session_id,
                decision_id=decision["id"],
                source=evidence["source"],
                summary=evidence["summary"],
                evidence_refs=evidence["evidence_refs"],
            )
            auto_resolved.append(
                {
                    "decision_id": decision["id"],
                    "source": evidence["source"],
                    "summary": evidence["summary"],
                    "evidence_refs": evidence["evidence_refs"],
                }
            )
            if len(auto_resolved) >= max_auto_resolutions:
                return {
                    "status": "resolved-by-evidence",
                    "session_id": session_id,
                    "auto_resolved": auto_resolved,
                    "message": _render_auto_resolved(auto_resolved),
                }
            continue

        proposal = issue_proposal(
            ai_dir,
            session_id,
            decision_id=decision["id"],
            question=_proposal_question(decision),
            recommendation=_proposal_recommendation(decision),
            why=_proposal_why(decision),
            if_not=_proposal_if_not(decision),
        )
        if stale_proposal_id:
            proposal = dict(proposal)
            proposal["superseded_stale_proposal_id"] = stale_proposal_id
        return _question_result(
            session_id=session_id,
            decision=_lookup_decision(current_bundle(ai_dir), decision["id"]),
            proposal=proposal,
            auto_resolved=auto_resolved,
            reused_active_proposal=False,
        )


def handle_reply(
    ai_dir: str,
    session_id: str,
    reply: str,
    *,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    text = reply.strip()
    if not text:
        raise ValueError("reply must not be empty")

    bundle = current_bundle(ai_dir)
    session = _require_session(bundle, session_id)
    if session["session"]["lifecycle"]["status"] == "closed":
        raise ValueError(f"session {session_id} is closed")

    lowered = text.casefold()
    if lowered == "ok":
        decision = accept_proposal(ai_dir, session_id, acceptance_mode="ok")
        next_turn = advance_session(ai_dir, session_id, repo_root=repo_root)
        accepted_message = "\n".join(
            [
                f"Accepted: {decision['id']}",
                f"Accepted answer: {decision['accepted_answer']['summary']}",
                next_turn["message"],
            ]
        )
        return {
            "status": "accepted",
            "session_id": session_id,
            "decision": decision,
            "next_turn": next_turn,
            "message": accepted_message,
        }

    accept_match = ACCEPT_PATTERN.match(text)
    if accept_match:
        proposal_id = accept_match.group(1)
        decision = accept_proposal(ai_dir, session_id, proposal_id=proposal_id, acceptance_mode="explicit")
        next_turn = advance_session(ai_dir, session_id, repo_root=repo_root)
        accepted_message = "\n".join(
            [
                f"Accepted: {decision['id']}",
                f"Accepted answer: {decision['accepted_answer']['summary']}",
                next_turn["message"],
            ]
        )
        return {
            "status": "accepted",
            "session_id": session_id,
            "decision": decision,
            "next_turn": next_turn,
            "message": accepted_message,
        }

    reject_match = REJECT_PATTERN.match(text)
    if reject_match:
        proposal_id = reject_match.group(1)
        reason = (reject_match.group(2) or "Rejected by user.").strip()
        decision = reject_proposal(ai_dir, session_id, proposal_id=proposal_id, reason=reason)
        message = "\n".join(
            [
                f"Rejected: {decision['id']}",
                f"Reason: {reason}",
                "Please provide the preferred answer or update the recommendation before advancing.",
            ]
        )
        return {
            "status": "rejected",
            "session_id": session_id,
            "decision": decision,
            "message": message,
        }

    defer_match = DEFER_PATTERN.match(text)
    if defer_match:
        decision_id = defer_match.group(1)
        reason = (defer_match.group(2) or "Deferred by user.").strip()
        decision = defer_decision(ai_dir, session_id, decision_id=decision_id, reason=reason)
        next_turn = advance_session(ai_dir, session_id, repo_root=repo_root)
        message = "\n".join(
            [
                f"Deferred: {decision['id']}",
                f"Reason: {reason}",
                next_turn["message"],
            ]
        )
        return {
            "status": "deferred",
            "session_id": session_id,
            "decision": decision,
            "next_turn": next_turn,
            "message": message,
        }

    active = session["working_state"]["active_proposal"]
    if active.get("proposal_id"):
        stale, reason = proposal_is_stale(bundle["project_state"], session)
        if stale:
            raise ValueError(
                f"active proposal for session {session_id} is stale: {reason}. "
                f"Use Accept {active['proposal_id']} for explicit acceptance."
            )
        parsed = _parse_active_reply(text, active["recommendation"])
        if parsed["kind"] == "affirm":
            decision = accept_proposal(ai_dir, session_id, acceptance_mode="explicit")
            next_turn = advance_session(ai_dir, session_id, repo_root=repo_root)
            message = _accepted_reply_message(decision, next_turn)
            return {
                "status": "accepted",
                "session_id": session_id,
                "decision": decision,
                "next_turn": next_turn,
                "message": message,
            }
        if parsed["kind"] == "reject":
            decision = reject_proposal(ai_dir, session_id, reason=text)
            message = "\n".join(
                [
                    f"Rejected: {decision['id']}",
                    f"Reason: {text}",
                    "Please provide the preferred answer or update the recommendation before advancing.",
                ]
            )
            return {
                "status": "rejected",
                "session_id": session_id,
                "decision": decision,
                "message": message,
            }

        decision = answer_proposal(
            ai_dir,
            session_id,
            answer_summary=parsed["answer_summary"],
            reason="User supplied an explicit answer.",
        )
        decision, captured_constraints, discovered_decisions = _capture_reply_artifacts(
            ai_dir,
            session_id,
            decision,
            parsed,
        )
        discovered_decisions, immediate_auto_resolved = _resolve_discovered_decisions_by_evidence(
            ai_dir,
            session_id,
            discovered_decisions,
            repo_root,
        )
        next_turn = advance_session(ai_dir, session_id, repo_root=repo_root)
        next_turn = _prepend_auto_resolved(next_turn, immediate_auto_resolved)
        message = _accepted_reply_message(
            decision,
            next_turn,
            constraints=captured_constraints,
            discovered_decisions=discovered_decisions,
        )
        return {
            "status": "accepted",
            "session_id": session_id,
            "decision": decision,
            "captured_constraints": captured_constraints,
            "discovered_decisions": discovered_decisions,
            "auto_resolved": immediate_auto_resolved,
            "next_turn": next_turn,
            "message": message,
        }

    raise ValueError(
        "Unsupported reply format. Use OK, Accept P-..., Reject P-...: reason, or Defer D-...: reason."
    )


def stopping_summary(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    session = _require_session(bundle, session_id)
    close_summary = build_close_summary(bundle["project_state"], session)
    return {
        "accepted_decisions": close_summary["accepted_decisions"],
        "deferred_decisions": close_summary["deferred_decisions"],
        "remaining_risks": close_summary["unresolved_risks"],
        "next_recommended_action": _next_recommended_action(close_summary, session_id),
    }


def find_evidence(
    bundle: dict[str, Any],
    session_id: str,
    decision: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any] | None:
    runtime_hit = _runtime_evidence(bundle, session_id, decision)
    if runtime_hit is not None:
        return runtime_hit

    if decision.get("resolvable_by") not in {"codebase", "docs", "tests"}:
        return None
    summary = _evidence_resolution_summary(decision)
    if not summary:
        return None

    source = decision["resolvable_by"]
    phrases = _evidence_phrases(decision)
    if not phrases:
        return None
    refs = _search_repo(repo_root, phrases, source)
    if not refs:
        return None
    return {
        "source": source,
        "summary": summary,
        "evidence_refs": refs,
    }


def _runtime_evidence(
    bundle: dict[str, Any], session_id: str, decision: dict[str, Any]
) -> dict[str, Any] | None:
    title = _normalize(decision.get("title"))
    for candidate in bundle["project_state"]["decisions"]:
        if candidate["id"] == decision["id"]:
            continue
        if candidate["status"] not in {"accepted", "resolved-by-evidence"}:
            continue
        if title and title == _normalize(candidate.get("title")):
            summary = candidate["accepted_answer"]["summary"] or candidate["resolved_by_evidence"]["summary"]
            refs = candidate.get("evidence_refs", [])
            return {
                "source": "existing-decisions",
                "summary": summary,
                "evidence_refs": refs,
            }

    for candidate_session in bundle["sessions"].values():
        if candidate_session["session"]["id"] == session_id:
            continue
        if candidate_session["session"]["lifecycle"]["status"] != "closed":
            continue
        close_summary = candidate_session["close_summary"]
        work_item_title = _normalize(close_summary.get("work_item_title"))
        if title and title == work_item_title:
            accepted = close_summary.get("accepted_decisions", [])
            if accepted:
                summary = accepted[0].get("accepted_answer")
                if summary:
                    return {
                        "source": "close-summaries",
                        "summary": summary,
                        "evidence_refs": close_summary.get("evidence_refs", []),
                    }
    return None


def _search_repo(repo_root: Path, phrases: list[str], source: str) -> list[str]:
    rg_matches = _search_repo_with_rg(repo_root, phrases, source)
    if rg_matches:
        return rg_matches

    matches: list[str] = []
    for path in _iter_searchable_files(repo_root):
        category = _path_category(path)
        if source != category:
            continue
        if _file_matches_phrases(path, phrases):
            matches.append(_relative_ref(repo_root, path))
        if len(matches) >= 3:
            break
    return matches


def _search_repo_with_rg(repo_root: Path, phrases: list[str], source: str) -> list[str] | None:
    rg = shutil.which("rg")
    patterns = _rg_patterns(phrases)
    if not rg or not patterns:
        return None

    command = [
        rg,
        "--files-with-matches",
        "--ignore-case",
        "--fixed-strings",
        "--no-messages",
    ]
    for ignored in sorted(IGNORE_DIRS):
        command.extend(["--glob", f"!{ignored}/**"])
        command.extend(["--glob", f"!**/{ignored}/**"])
    for pattern in patterns:
        command.extend(["-e", pattern])
    command.append(str(repo_root))

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode not in {0, 1}:
        return None

    matches: list[str] = []
    for raw_path in completed.stdout.splitlines():
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo_root / path
        if not _is_searchable_file(path):
            continue
        if source != _path_category(path):
            continue
        if not _file_matches_phrases(path, phrases):
            continue
        matches.append(_relative_ref(repo_root, path))
        if len(matches) >= 3:
            break
    return matches


def _rg_patterns(terms: list[str]) -> list[str]:
    patterns: list[str] = []
    for term in terms:
        pattern = str(term).strip()
        if not pattern or "\n" in pattern or "\r" in pattern:
            continue
        if pattern not in patterns:
            patterns.append(pattern)
        if len(patterns) >= 20:
            break
    return patterns


def _iter_searchable_files(repo_root: Path) -> Iterable[Path]:
    for path in repo_root.rglob("*"):
        if not _is_searchable_file(path):
            continue
        yield path


def _is_searchable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in IGNORE_DIRS for part in path.parts):
        return False
    if path.suffix and path.suffix.lower() not in TEXT_EXTENSIONS:
        return False
    return True


def _path_category(path: Path) -> str:
    lower = str(path).casefold()
    if "/tests/" in lower or "/test/" in lower or path.name.startswith("test_"):
        return "tests"
    if "/docs/" in lower or path.suffix.lower() in {".md", ".rst", ".txt"} or path.name.upper().startswith("README"):
        return "docs"
    return "codebase"


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 256_000:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _file_matches_phrases(path: Path, phrases: list[str]) -> bool:
    text = _read_text(path)
    if text is None:
        return False
    normalized_text = _normalize_search_phrase(text)
    return any(_normalize_search_phrase(phrase) in normalized_text for phrase in phrases)


def _evidence_phrases(decision: dict[str, Any]) -> list[str]:
    source_texts: list[str] = []
    for field in (
        decision.get("title"),
        decision.get("recommendation", {}).get("summary"),
    ):
        if field:
            source_texts.append(str(field))
    options = decision.get("options", [])
    if len(options) == 1 and options[0].get("summary"):
        source_texts.append(str(options[0]["summary"]))

    phrases: list[str] = []
    for text in source_texts:
        tokens = _phrase_tokens(text)
        if len(tokens) < 2:
            continue
        max_size = min(5, len(tokens))
        for size in range(max_size, 1, -1):
            for index in range(0, len(tokens) - size + 1):
                phrases.append(" ".join(tokens[index : index + size]))
    return _stable_unique_strings(phrases)[:20]


def _phrase_tokens(text: str) -> list[str]:
    normalized = _normalize_search_phrase(text)
    return [
        token
        for token in normalized.split()
        if token not in STOP_WORDS and len(token) > 1
    ]


def _normalize_search_phrase(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _resolve_discovered_decisions_by_evidence(
    ai_dir: str,
    session_id: str,
    discovered_decisions: list[dict[str, Any]],
    repo_root: Path,
    *,
    max_auto_resolutions: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not discovered_decisions:
        return [], []

    auto_resolved: list[dict[str, Any]] = []
    for discovered in discovered_decisions:
        bundle = current_bundle(ai_dir)
        current = _lookup_decision(bundle, discovered["id"])
        if len(auto_resolved) >= max_auto_resolutions:
            continue
        evidence = find_evidence(bundle, session_id, current, repo_root)
        if evidence is None:
            continue
        resolve_by_evidence(
            ai_dir,
            session_id,
            decision_id=current["id"],
            source=evidence["source"],
            summary=evidence["summary"],
            evidence_refs=evidence["evidence_refs"],
        )
        auto_resolved.append(
            {
                "decision_id": current["id"],
                "source": evidence["source"],
                "summary": evidence["summary"],
                "evidence_refs": evidence["evidence_refs"],
            }
        )

    bundle = current_bundle(ai_dir)
    updated_discovered = [_lookup_decision(bundle, discovered["id"]) for discovered in discovered_decisions]
    return updated_discovered, auto_resolved


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", text)
    return [token for token in tokens if token.casefold() not in STOP_WORDS]


def _proposal_question(decision: dict[str, Any]) -> str:
    return decision.get("question") or f"What should we decide about {decision['title']}?"


def _proposal_recommendation(decision: dict[str, Any]) -> str:
    recommendation = decision.get("recommendation", {})
    if recommendation.get("summary"):
        return recommendation["summary"]
    options = decision.get("options", [])
    if len(options) == 1 and options[0].get("summary"):
        return options[0]["summary"]
    return f"Choose the lowest-risk option for {decision['title']}."


def _evidence_resolution_summary(decision: dict[str, Any]) -> str | None:
    recommendation = decision.get("recommendation", {})
    if recommendation.get("summary"):
        return recommendation["summary"]
    options = decision.get("options", [])
    if len(options) == 1 and options[0].get("summary"):
        return options[0]["summary"]
    return None


def _proposal_why(decision: dict[str, Any]) -> str:
    recommendation = decision.get("recommendation", {})
    return (
        recommendation.get("rationale_short")
        or decision.get("context")
        or "This is the best-supported option for the current milestone."
    )


def _proposal_if_not(decision: dict[str, Any]) -> str:
    return decision.get("context") or "Rejecting this recommendation changes scope or milestone risk."


def _question_result(
    *,
    session_id: str,
    decision: dict[str, Any],
    proposal: dict[str, Any],
    auto_resolved: list[dict[str, Any]],
    reused_active_proposal: bool,
) -> dict[str, Any]:
    block = render_question_block(decision, proposal)
    message = block
    if auto_resolved:
        message = "\n".join([_render_auto_resolved(auto_resolved), block])
    return {
        "status": "question",
        "session_id": session_id,
        "decision_id": decision["id"],
        "proposal_id": proposal["proposal_id"],
        "decision": decision,
        "proposal": proposal,
        "reused_active_proposal": reused_active_proposal,
        "auto_resolved": auto_resolved,
        "message": message,
    }


def _prepend_auto_resolved(turn: dict[str, Any], auto_resolved: list[dict[str, Any]]) -> dict[str, Any]:
    if not auto_resolved:
        return turn
    merged = dict(turn)
    merged["auto_resolved"] = [*auto_resolved, *(turn.get("auto_resolved") or [])]
    message = turn.get("message")
    auto_message = _render_auto_resolved(auto_resolved)
    if message:
        merged["message"] = "\n".join([auto_message, message])
    else:
        merged["message"] = auto_message
    return merged


def _render_auto_resolved(auto_resolved: list[dict[str, Any]]) -> str:
    lines = []
    for item in auto_resolved:
        refs = ", ".join(item["evidence_refs"]) if item["evidence_refs"] else "no refs recorded"
        lines.append(f"Resolved by evidence: {item['decision_id']} ({item['source']}: {refs})")
    return "\n".join(lines)


def _render_complete_message(auto_resolved: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    parts = []
    if auto_resolved:
        parts.append(_render_auto_resolved(auto_resolved))
    parts.extend(
        [
            "Accepted decisions:",
            _render_summary_items(summary["accepted_decisions"]),
            "Deferred decisions:",
            _render_summary_items(summary["deferred_decisions"]),
            "Remaining risks:",
            _render_summary_items(summary["remaining_risks"]),
            f"Next recommended action: {summary['next_recommended_action']}",
        ]
    )
    return "\n".join(parts)


def _render_unbound_message(session_id: str) -> str:
    return "\n".join(
        [
            f"No decisions are bound to session {session_id}.",
            "Discover a new decision in this session, or resume a session that already owns the open decision.",
        ]
    )


def _render_stale_proposal_message(proposal: dict[str, Any], reason: str | None) -> str:
    return "\n".join(
        [
            f"Proposal {proposal['proposal_id']} is stale: {reason or 'stale'}.",
            f"Decision: {proposal['target_id']}",
            f"Recommendation: {proposal.get('recommendation')}",
            "Use explicit Accept P-... or Reject P-... before advancing this decision.",
        ]
    )


def _render_summary_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- none"
    return "\n".join(
        f"- {item['id']}: {item.get('accepted_answer') or item.get('title') or item['id']}"
        for item in items
    )


def _next_recommended_action(close_summary: dict[str, Any], session_id: str) -> str:
    if close_summary["unresolved_blockers"]:
        blocker = close_summary["unresolved_blockers"][0]
        return f"Resolve blocker {blocker['id']} before closing the session."
    if close_summary["unresolved_risks"]:
        return f"Review remaining risks, then close session {session_id} or generate a plan."
    return f"Close session {session_id} or generate a plan from closed sessions."


def _lookup_decision(bundle: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for decision in bundle["project_state"]["decisions"]:
        if decision["id"] == decision_id:
            return decision
    raise ValueError(f"unknown decision: {decision_id}")


def _require_session(bundle: dict[str, Any], session_id: str) -> dict[str, Any]:
    try:
        return bundle["sessions"][session_id]
    except KeyError as exc:
        raise ValueError(f"unknown session: {session_id}") from exc


def _relative_ref(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _looks_like_affirmation(text: str, recommendation: str | None) -> bool:
    normalized = _normalize(text)
    if normalized in POSITIVE_REPLIES:
        return True
    if recommendation:
        normalized_recommendation = _normalize(recommendation)
        if normalized_recommendation and normalized_recommendation in normalized:
            return True
        reply_tokens = set(_keywords(text))
        recommendation_tokens = set(_keywords(recommendation))
        if recommendation_tokens:
            overlap = len(reply_tokens & recommendation_tokens) / len(recommendation_tokens)
            if overlap >= 0.6:
                return True
    return False


def _looks_like_negative_only(text: str) -> bool:
    return _normalize(text) in NEGATIVE_ONLY_REPLIES


def _parse_active_reply(text: str, recommendation: str | None) -> dict[str, Any]:
    clauses = _split_reply_clauses(text)
    constraints: list[str] = []
    discovered: list[str] = []
    answer_clauses: list[str] = []

    if clauses:
        first_answer, inline_constraints = _extract_inline_constraints(clauses[0])
        if first_answer:
            answer_clauses.append(first_answer)
        constraints.extend(inline_constraints)
        tail_clauses = clauses[1:]
    else:
        tail_clauses = []

    for clause in tail_clauses:
        kind = _classify_follow_up_clause(clause)
        cleaned = _clean_clause(clause)
        if not cleaned:
            continue
        if kind == "constraint":
            constraints.append(cleaned)
        elif kind == "decision":
            discovered.append(cleaned)
        else:
            answer_clauses.append(cleaned)

    constraints = _stable_unique_strings(constraints)
    discovered = _stable_unique_strings(discovered)
    answer_text = " ".join(clause for clause in answer_clauses if clause).strip() or text.strip()

    if not constraints and not discovered:
        if _looks_like_affirmation(text, recommendation):
            return {"kind": "affirm", "constraints": [], "new_decision_clauses": []}
        if _looks_like_negative_only(text):
            return {"kind": "reject", "constraints": [], "new_decision_clauses": []}

    answer_summary = _derive_answer_summary(
        answer_text,
        recommendation,
        prefer_recommendation=bool(constraints or discovered),
    )
    return {
        "kind": "answer",
        "answer_summary": answer_summary,
        "constraints": constraints,
        "new_decision_clauses": discovered,
    }


def _capture_reply_artifacts(
    ai_dir: str,
    session_id: str,
    decision: dict[str, Any],
    parsed: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    captured_constraints = parsed.get("constraints", [])
    discovered_clauses = parsed.get("new_decision_clauses", [])
    updated_decision = decision

    if captured_constraints:
        updated_decision = enrich_decision(
            ai_dir,
            session_id,
            decision_id=decision["id"],
            notes_append=[f"Constraint: {constraint}" for constraint in captured_constraints],
            revisit_triggers_append=_revisit_triggers_from_constraints(captured_constraints),
            context_append=_constraints_context_append(captured_constraints),
        )

    discovered_decisions: list[dict[str, Any]] = []
    for clause in discovered_clauses:
        discovered_decisions.append(
            discover_decision(
                ai_dir,
                session_id,
                _build_discovered_decision(updated_decision, clause),
            )
        )
    return updated_decision, captured_constraints, discovered_decisions


def _split_reply_clauses(text: str) -> list[str]:
    return [part.strip(" ,") for part in CLAUSE_SPLIT_PATTERN.split(text) if part.strip(" ,")]


def _extract_inline_constraints(clause: str) -> tuple[str, list[str]]:
    match = INLINE_CONSTRAINT_PATTERN.search(clause)
    if not match:
        return clause.strip(), []
    answer_part = clause[: match.start()].strip(" ,")
    constraint_part = clause[match.start() :].strip(" ,")
    return answer_part, [constraint_part] if constraint_part else []


def _classify_follow_up_clause(clause: str) -> str:
    normalized = _normalize(_clean_clause(clause))
    if not normalized:
        return "ignore"
    if normalized.startswith(("because ", "since ", "so that ")):
        return "answer"
    if _looks_like_new_decision_clause(normalized):
        return "decision"
    if _looks_like_constraint_clause(normalized):
        return "constraint"
    return "answer"


def _looks_like_new_decision_clause(normalized_clause: str) -> bool:
    return any(phrase in normalized_clause for phrase in DISCOVERY_PHRASES)


def _looks_like_constraint_clause(normalized_clause: str) -> bool:
    return any(phrase in normalized_clause for phrase in CONSTRAINT_PHRASES)


def _clean_clause(clause: str) -> str:
    cleaned = clause.strip(" ,")
    cleaned = re.sub(r"^(?:and|but|plus|also)\b[:,]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _derive_answer_summary(
    answer_text: str,
    recommendation: str | None,
    *,
    prefer_recommendation: bool,
) -> str:
    stripped = _strip_answer_prefixes(answer_text)
    if prefer_recommendation and _looks_like_affirmation(stripped, recommendation):
        return recommendation or stripped or answer_text
    if recommendation and _looks_like_affirmation(stripped, recommendation):
        return recommendation
    return stripped or recommendation or answer_text


def _strip_answer_prefixes(text: str) -> str:
    stripped = text.strip()
    previous = None
    while stripped and previous != stripped:
        previous = stripped
        stripped = ANSWER_PREFIX_PATTERN.sub("", stripped).strip()
    return stripped


def _revisit_triggers_from_constraints(constraints: list[str]) -> list[str]:
    triggers = []
    for constraint in constraints:
        normalized = _normalize(constraint)
        if any(normalized.startswith(prefix) for prefix in TRIGGER_PREFIXES):
            triggers.append(constraint)
    return _stable_unique_strings(triggers)


def _constraints_context_append(constraints: list[str]) -> str:
    return "Additional constraints from user reply:\n" + "\n".join(f"- {constraint}" for constraint in constraints)


def _build_discovered_decision(current_decision: dict[str, Any], clause: str) -> dict[str, Any]:
    normalized = _normalize(clause)
    title = _title_from_clause(clause)
    priority, frontier = _priority_and_frontier_from_clause(current_decision, normalized)
    kind = _kind_from_clause(current_decision, normalized)
    domain = _domain_from_clause(current_decision, title, clause)
    resolvable_by = _resolvable_by_from_clause(current_decision, normalized, domain, kind)
    reversibility = _reversibility_from_clause(
        current_decision,
        normalized,
        domain=domain,
        kind=kind,
        resolvable_by=resolvable_by,
    )
    recommendation = _recommendation_from_clause(title, kind=kind, resolvable_by=resolvable_by)
    discovered = {
        "id": new_entity_id("D"),
        "title": title,
        "kind": kind,
        "domain": domain,
        "priority": priority,
        "frontier": frontier,
        "status": "unresolved",
        "resolvable_by": resolvable_by,
        "reversibility": reversibility,
        "question": _question_from_follow_up_clause(title, clause, kind=kind, resolvable_by=resolvable_by),
        "context": clause.strip(),
        "notes": [f"Discovered from reply while resolving {current_decision['id']}."],
    }
    if recommendation is not None:
        discovered["options"] = [{"summary": recommendation["summary"]}]
    return discovered


def _title_from_clause(clause: str) -> str:
    cleaned = _clean_clause(clause)
    cleaned = re.sub(
        r"^(?:we\s+(?:also\s+|still\s+)?)?need(?:\s+to)?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(?:there\s+(?:also\s+)?)?needs\s+to\s+be\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:must|should)\s+(?:also\s+)?", "", cleaned, flags=re.IGNORECASE)
    words = cleaned.strip(" .")
    if not words:
        return "Follow-up decision"
    tokens = words.split()
    shortened = " ".join(tokens[:8])
    return shortened[0].upper() + shortened[1:]


def _priority_and_frontier_from_clause(
    current_decision: dict[str, Any], normalized_clause: str
) -> tuple[str, str]:
    if any(marker in normalized_clause for marker in NOW_PRIORITY_PHRASES):
        return "P0", "now"
    if any(marker in normalized_clause for marker in LATER_PRIORITY_PHRASES):
        return "P2", "later"
    if any(marker in normalized_clause for marker in NICE_TO_HAVE_PHRASES):
        return "P2", "later"
    if any(marker in normalized_clause for marker in ("must ", "need ", "needs ", "have to ")):
        return "P0", "now"
    if any(marker in normalized_clause for marker in ("should also", "we also need", "there needs to be")):
        if current_decision.get("frontier") == "now":
            return "P1", "now"
        return "P1", "discovered-later"
    inherited_priority = current_decision.get("priority")
    if inherited_priority == "P0":
        return "P1", current_decision.get("frontier") or "discovered-later"
    return "P1", "discovered-later"


def _kind_from_clause(current_decision: dict[str, Any], normalized_clause: str) -> str:
    if any(marker in normalized_clause for marker in RISK_PHRASES):
        return "risk"
    if any(marker in normalized_clause for marker in LEGAL_CONSTRAINT_PHRASES):
        return "constraint"
    if any(marker in normalized_clause for marker in ("dependency", "depends on", *DEPENDENCY_PHRASES)):
        return "dependency"
    if any(marker in normalized_clause for marker in ("must", "cannot", "can't", "only", "unless", "except")):
        return "constraint"
    if current_decision.get("kind") in {"dependency", "constraint"} and any(
        marker in normalized_clause for marker in ("also need", "need ", "needs ")
    ):
        return current_decision["kind"]
    return "choice"


def _domain_from_clause(current_decision: dict[str, Any], title: str, clause: str) -> str:
    primary = _normalize(" ".join([title, clause]))
    scores = _score_domains(primary)
    current_domain = current_decision.get("domain") or "other"
    if not scores:
        context_scores = _score_domains(_normalize(current_decision.get("context")))
        if not context_scores:
            return current_domain
        scores = context_scores

    best_score = max(scores.values())
    if current_domain in scores and scores[current_domain] == best_score:
        return current_domain

    tied = [domain for domain, score in scores.items() if score == best_score]
    for domain in DOMAIN_PRIORITY:
        if domain in tied:
            return domain
    return current_domain


def _score_domains(normalized: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for domain, hints in DOMAIN_HINTS.items():
        score = 0
        for hint in hints:
            if _contains_hint(normalized, hint):
                score += 2 if " " in hint else 1
        if score:
            scores[domain] = score
    return scores


def _contains_hint(normalized: str, hint: str) -> bool:
    escaped = re.escape(hint.casefold()).replace(r"\ ", r"\s+")
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, normalized) is not None


def _resolvable_by_from_clause(
    current_decision: dict[str, Any],
    normalized_clause: str,
    domain: str,
    kind: str,
) -> str:
    if any(_contains_hint(normalized_clause, marker) for marker in TESTS_PHRASES):
        return "tests"
    if any(_contains_hint(normalized_clause, marker) for marker in DOCS_PHRASES):
        return "docs"
    if domain == "legal" or any(_contains_hint(normalized_clause, marker) for marker in EXTERNAL_PHRASES):
        return "external"
    if any(_contains_hint(normalized_clause, marker) for marker in CODEBASE_PHRASES):
        return "codebase"

    inherited = current_decision.get("resolvable_by")
    if inherited in {"codebase", "docs", "tests"} and kind in {"choice", "dependency"}:
        return inherited
    if domain in {"technical", "data"} and kind in {"choice", "dependency"}:
        return "codebase"
    return "human"


def _reversibility_from_clause(
    current_decision: dict[str, Any],
    normalized_clause: str,
    *,
    domain: str,
    kind: str,
    resolvable_by: str,
) -> str:
    if any(_contains_hint(normalized_clause, marker) for marker in IRREVERSIBLE_PHRASES):
        return "irreversible"
    if any(_contains_hint(normalized_clause, marker) for marker in ("configurable", "feature flag", "toggle")):
        return "reversible"
    if resolvable_by in {"docs", "tests"}:
        return "reversible"
    if domain == "legal" or resolvable_by == "external":
        return "hard-to-reverse"
    if any(_contains_hint(normalized_clause, marker) for marker in HARD_TO_REVERSE_PHRASES):
        return "hard-to-reverse"
    if domain in {"data", "ops"} and kind in {"constraint", "dependency"}:
        return "hard-to-reverse"

    inherited = current_decision.get("reversibility")
    if inherited in {"hard-to-reverse", "irreversible"} and kind in {"constraint", "dependency"}:
        return inherited
    return "reversible"


def _question_from_follow_up_clause(title: str, clause: str, *, kind: str, resolvable_by: str) -> str:
    normalized = _normalize(clause)
    subject = _question_subject(title)
    if kind == "constraint":
        if resolvable_by == "external":
            return f"What external requirement should apply to {subject}?"
        return f"What constraint should apply to {subject}?"
    if kind == "dependency":
        if resolvable_by == "tests":
            return f"What test coverage do we need for {subject}?"
        if resolvable_by == "docs":
            return f"What documentation do we need for {subject}?"
        if resolvable_by == "external":
            return f"What external dependency do we need for {subject}?"
        if resolvable_by == "codebase":
            return f"What implementation do we need for {subject}?"
        return f"What dependency do we need to resolve for {subject}?"
    if resolvable_by == "tests":
        return f"What tests do we need for {subject}?"
    if resolvable_by == "docs":
        return f"What documentation do we need for {subject}?"
    if "decide" in normalized:
        return f"What should we decide about {subject}?"
    if resolvable_by == "codebase":
        return f"How should we implement {subject}?"
    return f"How should we handle {subject}?"


def _question_subject(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        return "this"
    first_token = stripped.split(maxsplit=1)[0]
    if first_token.isupper() or any(char.isdigit() for char in first_token):
        return stripped
    return stripped[0].lower() + stripped[1:]


def _recommendation_from_clause(title: str, *, kind: str, resolvable_by: str) -> dict[str, Any] | None:
    subject = _question_subject(title)
    if resolvable_by == "docs":
        return {
            "summary": f"Document {subject}.",
            "rationale_short": "The follow-up clause points to documentation work.",
        }
    if resolvable_by == "tests":
        return {
            "summary": f"Add tests for {subject}.",
            "rationale_short": "The follow-up clause points to test coverage work.",
        }
    if resolvable_by == "codebase":
        if kind == "dependency":
            return {
                "summary": f"Implement {subject}.",
                "rationale_short": "The follow-up clause points to implementation work in the repo.",
            }
        return {
            "summary": f"Implement {subject}.",
            "rationale_short": "The follow-up clause points to implementation work in the repo.",
        }
    return None


def _accepted_reply_message(
    decision: dict[str, Any],
    next_turn: dict[str, Any],
    *,
    constraints: list[str] | None = None,
    discovered_decisions: list[dict[str, Any]] | None = None,
) -> str:
    parts = [
        f"Accepted: {decision['id']}",
        f"Accepted answer: {decision['accepted_answer']['summary']}",
    ]
    if constraints:
        parts.extend(
            [
                "Captured constraints:",
                *[f"- {constraint}" for constraint in constraints],
            ]
        )
    if discovered_decisions:
        parts.extend(
            [
                "Discovered decisions:",
                *[
                    f"- {item['id']}: {item['title']}"
                    for item in discovered_decisions
                ],
            ]
        )
    parts.append(next_turn["message"])
    return "\n".join(parts)


def _stable_unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = _normalize(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(value.strip())
    return ordered
