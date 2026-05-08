#!/usr/bin/env python3
"""
commitai — AI-powered commit messages & changelog using Gemma 4 (via Ollama)
Usage: python commitai.py [--changelog-only] [--no-confirm]
"""

import subprocess
import sys
import json
import urllib.request
import urllib.error
import datetime
import os
import argparse

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma4:e2b"
CHANGELOG_FILE = "CHANGELOG.md"

def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def get_staged_diff() -> str:
    diff = run(["git", "diff", "--staged"])
    if not diff:
        print("⚠  No staged changes found. Run `git add .` first.")
        sys.exit(1)
    return diff


def get_recent_commits(n: int = 5) -> str:
    return run(["git", "log", f"-{n}", "--pretty=format:%s"])


def ask_gemma(prompt: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3}
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except urllib.error.URLError:
        print("❌  Cannot reach Ollama. Is it running? Try: ollama serve")
        sys.exit(1)


def generate_commit_message(diff: str, recent: str) -> str:
    prompt = f"""You are a Git commit message expert. Analyze this staged diff and write ONE conventional commit message.

Rules:
- Format: <type>(<scope>): <short description>
- Types: feat, fix, refactor, docs, test, chore, style, perf
- Max 72 characters total
- Lowercase, no period at end
- Output ONLY the commit message, nothing else

Recent commits for context:
{recent}

Staged diff:
{diff[:3000]}

Commit message:"""
    return ask_gemma(prompt)


def generate_changelog_entry(diff: str, commit_msg: str) -> str:
    today = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""Write a single changelog entry for a CHANGELOG.md file.

Format exactly like this:
### {today}
- <plain English description of what changed and why it matters to users>

Rules:
- One bullet point only
- Plain English, no jargon
- Focus on what changed from a user perspective
- Output ONLY the changelog entry block, nothing else

Commit: {commit_msg}
Diff summary:
{diff[:2000]}

Changelog entry:"""
    return ask_gemma(prompt)


def prepend_to_changelog(entry: str):
    existing = ""
    if os.path.exists(CHANGELOG_FILE):
        with open(CHANGELOG_FILE, "r") as f:
            existing = f.read()

    header = "# Changelog\n\n" if not existing.startswith("# Changelog") else ""

    with open(CHANGELOG_FILE, "w") as f:
        if header:
            f.write(header)
            f.write(entry + "\n\n")
            f.write(existing)
        else:
            # Insert after the header line
            lines = existing.split("\n", 2)
            f.write(lines[0] + "\n\n")
            f.write(entry + "\n\n")
            if len(lines) > 2:
                f.write(lines[2])


def confirm(message: str, default: str = "y") -> bool:
    hint = "[Y/n]" if default == "y" else "[y/N]"
    choice = input(f"{message} {hint}: ").strip().lower()
    if not choice:
        return default == "y"
    return choice in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(description="commitai — AI commit messages with Gemma 4")
    parser.add_argument("--no-confirm", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--changelog-only", action="store_true", help="Only update changelog, don't commit")
    args = parser.parse_args()

    print("🔍  Reading staged diff...")
    diff = get_staged_diff()
    recent = get_recent_commits()

    print(f"🤖  Asking Gemma 4 ({MODEL})...\n")

    commit_msg = generate_commit_message(diff, recent)

    print(f"  Suggested commit message:\n")
    print(f"  \033[1m{commit_msg}\033[0m\n")

    final_msg = commit_msg
    if not args.no_confirm:
        choice = input("  Use this? [Y/n/edit]: ").strip().lower()
        if choice == "n":
            print("Aborted.")
            sys.exit(0)
        elif choice == "edit" or choice == "e":
            edited = input(f"  Edit message: ").strip()
            if edited:
                final_msg = edited

    if not args.changelog_only:
        run(["git", "commit", "-m", final_msg])
        print(f"\n✅  Committed: {final_msg}")

    print("📝  Generating changelog entry...")
    entry = generate_changelog_entry(diff, final_msg)
    prepend_to_changelog(entry)
    print(f"✅  {CHANGELOG_FILE} updated.\n")

    if args.changelog_only:
        print(f"  Changelog entry added (no commit made).")


if __name__ == "__main__":
    main()
