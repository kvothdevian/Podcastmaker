import os
import json
from datetime import datetime


USAGE_LOG_FILE = "usage_log.json"


def print_session_summary(usage_log: dict):
    """Print a formatted session summary to the terminal."""
    print("\n" + "=" * 40)
    print("     Session Summary - The Essayist")
    print("=" * 40)
    print(f"  Essay:      {usage_log.get('essay', 'Unknown')}")
    print(f"  Author:     {usage_log.get('author', 'Unknown')}")
    print(f"  Model Used: {usage_log.get('model_used', 'Unknown')}")
    print(f"  Fallbacks:  {usage_log.get('fallbacks_triggered', 0)}")
    print(f"  Tokens In:  {usage_log.get('prompt_tokens', 0):,}")
    print(f"  Tokens Out: {usage_log.get('completion_tokens', 0):,}")
    meta_tokens = usage_log.get('metadata_tokens', 0)
    if meta_tokens:
        print(f"  Meta Tokens:{meta_tokens:,}")
    print(f"  Est. Cost:  $0.00 (Free tier)")
    print("=" * 40 + "\n")


def save_to_log(usage_log: dict):
    """Append the session data to the persistent usage_log.json."""
    existing = []
    if os.path.exists(USAGE_LOG_FILE):
        try:
            with open(USAGE_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("runs", [])
        except Exception:
            existing = []

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "essay": usage_log.get("essay", ""),
        "author": usage_log.get("author", ""),
        "model_used": usage_log.get("model_used", ""),
        "prompt_tokens": usage_log.get("prompt_tokens", 0),
        "completion_tokens": usage_log.get("completion_tokens", 0),
        "metadata_tokens": usage_log.get("metadata_tokens", 0),
        "fallbacks_triggered": usage_log.get("fallbacks_triggered", 0),
        "output_file": usage_log.get("output_file", ""),
    }

    existing.append(entry)

    with open(USAGE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({"runs": existing}, f, indent=2, ensure_ascii=False)

    print(f"  Usage log updated: {USAGE_LOG_FILE}")


def load_log_summary() -> dict:
    """Return cumulative stats from the usage log."""
    if not os.path.exists(USAGE_LOG_FILE):
        return {}
    try:
        with open(USAGE_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        runs = data.get("runs", [])
        total_prompt = sum(r.get("prompt_tokens", 0) for r in runs)
        total_completion = sum(r.get("completion_tokens", 0) for r in runs)
        return {
            "total_runs": len(runs),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        }
    except Exception:
        return {}
