"""Optional Advanced Coach via OpenAI-compatible chat APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

PROVIDERS = {
    "xai": {
        "label": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-4",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.2",
    },
    "custom": {
        "label": "Custom OpenAI-compatible URL",
        "base_url": "",
        "default_model": "gpt-4o-mini",
    },
}


SYSTEM_PROMPT = """You are Advanced Coach inside a personal finance command center.
You only see numbers the user already stored locally (accounts, bills, debt plan, cash-flow summary).
Be specific, calm, and practical. Prefer short paragraphs and concrete next steps.
Never invent balances or bills that are not in the snapshot.
Do not ask for bank passwords or account numbers.
Encourage without toxic positivity; cash-flow stress is real.
When recommending debt order, prefer avalanche for high APR gaps and snowball when balances are small and motivation matters.
Always respect the safety buffer and upcoming calendar hits before suggesting extra debt payments or investing.
"""


def build_snapshot(
    summary: dict,
    debts: list[dict],
    plan: dict,
    obligations: list[dict],
    brief: dict,
) -> str:
    from datetime import date as _date

    from engine import is_obligation_current

    today = _date.fromisoformat(summary["today"]) if summary.get("today") else _date.today()
    live = [o for o in obligations if is_obligation_current(o, today)]
    subs = [
        {
            "name": o.get("name"),
            "vendor": o.get("vendor"),
            "amount": o.get("amount"),
            "due_day": o.get("due_day"),
            "end_date": o.get("end_date"),
        }
        for o in live
        if o.get("category") == "subscriptions" and o.get("direction") == "out"
    ]
    payload = {
        "live_obligation_count": len(live),
        "today": summary.get("today"),
        "cash": summary.get("cash"),
        "investments": summary.get("investments"),
        "crypto": summary.get("crypto"),
        "debt": summary.get("debt"),
        "net_worth": summary.get("net_worth"),
        "safe_to_spend": summary.get("safe_to_spend"),
        "next30_safe": summary.get("next30_safe"),
        "buffer": summary.get("buffer"),
        "remaining_in": summary.get("remaining_in"),
        "remaining_out": summary.get("remaining_out"),
        "budget_leftover": (summary.get("budget") or {}).get("leftover"),
        "debt_strategy": plan.get("strategy"),
        "extra_monthly": plan.get("extra_monthly"),
        "debt_plan_totals": plan.get("totals"),
        "debt_order": plan.get("order"),
        "debts": debts,
        "subscriptions": subs,
        "local_coach_brief": {
            "recommended_strategy": brief.get("recommended_strategy"),
            "why": brief.get("why"),
            "focus": brief.get("focus"),
            "cuts": brief.get("cuts"),
        },
    }
    return json.dumps(payload, indent=2, default=str)


def chat(
    *,
    question: str,
    snapshot: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 60,
) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        raise ValueError("Base URL is required for the Advanced Coach.")
    if not model:
        raise ValueError("Model name is required.")
    # Ollama often works without a key
    key = (api_key or "").strip() or "ollama"

    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Financial snapshot (JSON):\n"
                    f"{snapshot}\n\n"
                    f"User question: {question or 'Give a concise strategic briefing and one next action.'}"
                ),
            },
        ],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach LLM endpoint: {e.reason}") from e

    try:
        return raw["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise RuntimeError(f"Unexpected LLM response shape: {str(raw)[:300]}") from e


def public_config(settings: dict[str, str]) -> dict[str, Any]:
    key = settings.get("llm_api_key") or ""
    provider = settings.get("llm_provider") or "openai"
    meta = PROVIDERS.get(provider, PROVIDERS["openai"])
    return {
        "enabled": settings.get("llm_enabled") == "1",
        "provider": provider,
        "base_url": settings.get("llm_base_url") or meta["base_url"],
        "model": settings.get("llm_model") or meta["default_model"],
        "has_api_key": bool(key.strip()),
        "api_key_hint": ("••••" + key[-4:]) if len(key) >= 4 else ("set" if key else ""),
        "providers": {k: {"label": v["label"], "base_url": v["base_url"], "default_model": v["default_model"]} for k, v in PROVIDERS.items()},
    }
