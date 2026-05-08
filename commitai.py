#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "gemma4:e2b"
CHANGELOG_PATH = os.path.join(ROOT_DIR, "CHANGELOG.md")
MAX_DIFF_CHARS = 12000
MAX_RECENT_COMMITS = 8
CONVENTIONAL_TYPES = ("feat", "fix", "refactor", "docs", "test", "chore", "style", "perf")

console = Console()


class CommitAIError(RuntimeError):
    pass


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )


def git_output(args: list[str]) -> str:
    result = run_git(args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def abort(message: str, hint: str | None = None, exit_code: int = 1) -> int:
    body = message if hint is None else f"{message}\n\n{hint}"
    console.print(Panel(body, title="commitai", border_style="red"))
    return exit_code


def print_banner() -> None:
    title = Text("commitai", style="bold cyan")
    subtitle = Text("local ai git assistant", style="bright_black")
    console.print(Panel.fit(Text.assemble(title, "\n", subtitle), border_style="cyan"))


def ensure_git_repo() -> None:
    result = run_git(["rev-parse", "--is-inside-work-tree"])
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise CommitAIError("This directory is not a git repository.")


def get_staged_diff() -> str:
    result = run_git(["diff", "--staged", "--unified=3"])
    if result.returncode != 0:
        raise CommitAIError(result.stderr.strip() or "Unable to read the staged diff.")
    diff = result.stdout.strip()
    if not diff:
        raise CommitAIError("No staged changes found. Stage files first with git add.")
    return diff


def get_staged_files() -> list[str]:
    output = git_output(["diff", "--staged", "--name-only"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def get_diff_stat() -> str:
    output = git_output(["diff", "--staged", "--stat"])
    return output or "No diff stat available."


def get_recent_commits(limit: int = MAX_RECENT_COMMITS) -> str:
    return git_output(["log", f"-{limit}", "--pretty=format:%s"]) or "No previous commits."


def truncate_text(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" .,-")


def clip_block(value: str, limit: int) -> str:
    block = value.strip()
    if len(block) <= limit:
        return block
    return block[:limit].rstrip()


def normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def suggest_commit_type(files: list[str], diff: str) -> str:
    haystack = "\n".join(files + [diff]).lower()
    if any(item.endswith((".md", ".rst", ".txt")) for item in files) or "readme" in haystack or "changelog" in haystack:
        return "docs"
    if "test" in haystack or "pytest" in haystack or "unittest" in haystack:
        return "test"
    if any(keyword in haystack for keyword in ("bug", "fix", "error", "exception", "fail", "null", "guard")):
        return "fix"
    if any(keyword in haystack for keyword in ("refactor", "cleanup", "simplify", "rename", "restructure")):
        return "refactor"
    if any(keyword in haystack for keyword in ("perf", "optimize", "faster", "speed")):
        return "perf"
    if any(keyword in haystack for keyword in ("style", "format", "lint")):
        return "style"
    if any(keyword in haystack for keyword in ("build", "deps", "dependency", "requirements", "setup", "config")):
        return "chore"
    return "feat"


def suggest_scope(files: list[str]) -> str:
    if not files:
        return "cli"
    normalized = [item.replace("\\", "/") for item in files]
    if any(item.startswith("hooks/") for item in normalized):
        return "hooks"
    if any(item.lower() in {"readme.md", "changelog.md"} for item in normalized):
        return "docs"
    if len(normalized) == 1:
        filename = os.path.basename(normalized[0])
        stem, _ = os.path.splitext(filename)
        if stem == "commitai":
            return "cli"
        if stem == "app":
            return "app"
        if stem in {"readme", "changelog"}:
            return "docs"
        return stem.lower()
    first_directory = normalized[0].split("/", 1)[0].lower()
    if first_directory in {"src", "lib", "app", "hooks", "docs"}:
        return first_directory
    return first_directory if first_directory else "cli"


def validate_model_available(model: str) -> None:
    request = urllib.request.Request(OLLAMA_TAGS_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise CommitAIError("Cannot reach Ollama. Start it with `ollama serve`.") from exc
    models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
    if models and model not in models:
        available = ", ".join(models)
        raise CommitAIError(f"Model '{model}' is not available in Ollama. Available models: {available}")


def ask_ollama(prompt: str, model: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        if "model" in body.lower() or "not found" in body.lower() or exc.code in {400, 404}:
            raise CommitAIError(f"Ollama rejected model '{model}'. Pull it with `ollama pull {model}`.") from exc
        raise CommitAIError(body.strip() or "Ollama request failed.") from exc
    except urllib.error.URLError as exc:
        raise CommitAIError("Cannot reach Ollama. Start it with `ollama serve`.") from exc
    response_text = normalize_whitespace(str(data.get("response", "")))
    if data.get("error"):
        raise CommitAIError(str(data["error"]))
    if not response_text:
        raise CommitAIError("Ollama returned an empty response.")
    return response_text


def trim_explanation_lines(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        line = line.strip("` ")
        if line:
            lines.append(line)
    if not lines:
        return ""
    return normalize_whitespace(lines[0])


def fit_commit_message(commit_type: str, scope: str, description: str) -> str:
    commit_type = commit_type.lower().strip()
    scope = scope.lower().strip()
    description = normalize_whitespace(description).lower().strip(". ")
    prefix = f"{commit_type}({scope}): " if scope else f"{commit_type}: "
    max_description_length = 72 - len(prefix)
    if max_description_length < 1:
        return truncate_text(prefix.rstrip(), 72)
    description = truncate_text(description, max_description_length)
    if not description:
        description = "update project files"
    return f"{prefix}{description}"[:72].rstrip()


def sanitize_commit_message(raw_message: str, suggested_type: str, suggested_scope: str) -> str:
    candidate = trim_explanation_lines(raw_message)
    if not candidate:
        return fit_commit_message(suggested_type, suggested_scope, "update project files")
    match = re.match(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?:\s*(?P<description>.+)$", candidate, re.IGNORECASE)
    if match and match.group("type", "description"):
        commit_type = match.group("type").lower()
        scope = (match.group("scope") or suggested_scope).strip().lower()
        description = match.group("description").strip()
        if commit_type in CONVENTIONAL_TYPES:
            return fit_commit_message(commit_type, scope, description)
    return fit_commit_message(suggested_type, suggested_scope, candidate)


def fallback_commit_message(suggested_type: str, suggested_scope: str) -> str:
    descriptions = {
        "feat": "add local ai git workflow",
        "fix": "resolve commit workflow issues",
        "refactor": "simplify the commit workflow",
        "docs": "update project documentation",
        "test": "update test coverage",
        "chore": "update project maintenance files",
        "style": "adjust formatting",
        "perf": "improve commit workflow performance",
    }
    return fit_commit_message(suggested_type, suggested_scope, descriptions.get(suggested_type, "update project files"))


def build_commit_prompt(diff: str, diff_stat: str, files: list[str], recent_commits: str, suggested_type: str, suggested_scope: str) -> str:
    file_lines = "\n".join(f"- {item}" for item in files) if files else "- (no file list available)"
    diff_excerpt = clip_block(diff, MAX_DIFF_CHARS)
    return f"""You are an expert Git assistant.

Write exactly one Conventional Commit message.

Rules:
- Output only the final commit message
- Format: type(scope): message
- Keep the total length at 72 characters or less
- Use lowercase
- Do not add markdown, bullets, quotes, explanations, or code fences
- Prefer the suggested type and scope when they fit the change

Suggested type: {suggested_type}
Suggested scope: {suggested_scope}

Changed files:
{file_lines}

Diff stat:
{diff_stat}

Recent commit subjects:
{recent_commits}

Staged diff:
{diff_excerpt}

Return only the commit message."""


def build_changelog_prompt(commit_message: str, diff_stat: str, diff: str) -> str:
    today = _datetime.date.today().strftime("%Y-%m-%d")
    diff_excerpt = clip_block(diff, 5000)
    return f"""Write one concise changelog entry for a local developer tool.

Return exactly this format:
## {today}

* <short plain-English summary>

Rules:
- One bullet only
- Keep it concise
- Focus on user-visible change
- No markdown outside the requested block

Commit message:
{commit_message}

Diff stat:
{diff_stat}

Staged diff:
{diff_excerpt}

Return only the changelog block."""


def build_pr_prompt(commit_message: str, diff_stat: str, diff: str) -> str:
    diff_excerpt = clip_block(diff, 7000)
    return f"""Write a pull request description for this change.

Format:
## Summary
## Changes
## Testing

Rules:
- Keep it concise and practical
- Use bullet lists under each section when helpful
- Mention that the workflow is local-first if relevant
- Do not mention anything not supported by the diff

Commit message:
{commit_message}

Diff stat:
{diff_stat}

Staged diff:
{diff_excerpt}

Return only the PR description."""


def build_changelog_entry(commit_message: str, diff_stat: str, diff: str, model: str) -> str:
    prompt = build_changelog_prompt(commit_message, diff_stat, diff)
    raw_entry = ask_ollama(prompt, model)
    entry = raw_entry.strip()
    today = _datetime.date.today().strftime("%Y-%m-%d")
    if not entry.startswith("## "):
        entry = f"## {today}\n\n* {entry.lstrip('* ').strip()}"
    lines = [line.rstrip() for line in entry.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("## "):
        summary = commit_message.split(":", 1)[-1].strip().capitalize()
        return f"## {today}\n\n* {summary}"
    if len(lines) == 1:
        lines.append("")
        lines.append("* Updated the project workflow.")
    return "\n".join(lines)


def build_pr_description(commit_message: str, diff_stat: str, diff: str, model: str) -> str:
    prompt = build_pr_prompt(commit_message, diff_stat, diff)
    raw_description = ask_ollama(prompt, model)
    description = raw_description.strip()
    if not description:
        description = "## Summary\n\n- Update generated from the staged diff.\n\n## Changes\n\n- See staged diff summary.\n\n## Testing\n\n- Not run."
    return description


def prepend_changelog(entry: str) -> None:
    existing = ""
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as handle:
            existing = handle.read().rstrip()
    if not existing:
        content = f"# Changelog\n\n{entry.rstrip()}\n"
    elif existing.startswith("# Changelog"):
        remainder = existing[len("# Changelog"):].lstrip("\n")
        parts = ["# Changelog", "", entry.rstrip()]
        if remainder:
            parts.extend(["", remainder])
        content = "\n".join(parts).rstrip() + "\n"
    else:
        content = f"# Changelog\n\n{entry.rstrip()}\n\n{existing}\n"
    with open(CHANGELOG_PATH, "w", encoding="utf-8") as handle:
        handle.write(content)


def stage_changelog() -> None:
    result = run_git(["add", "CHANGELOG.md"])
    if result.returncode != 0:
        raise CommitAIError(result.stderr.strip() or "Unable to stage CHANGELOG.md.")


def get_commit_message_path() -> str:
    path = git_output(["rev-parse", "--git-path", "COMMIT_EDITMSG"])
    if not path:
        raise CommitAIError("Unable to resolve the git commit message file.")
    return path


def write_commit_message_file(message: str) -> None:
    path = get_commit_message_path()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def commit_changes(message: str) -> None:
    result = run_git(["commit", "-m", message])
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "Git commit failed."
        raise CommitAIError(error)


def prompt_for_edit(message: str) -> str:
    console.print(Panel(message, title="Suggested commit message", border_style="green"))
    if Confirm.ask("Use this commit message?", default=True):
        return message
    edited = Prompt.ask("Edit commit message", default=message)
    edited = edited.strip()
    if not edited:
        raise CommitAIError("Commit message edit was empty.")
    return edited


def render_success(title: str, body: str) -> None:
    console.print(Panel(body, title=title, border_style="green"))


def main() -> int:
    parser = argparse.ArgumentParser(description="commitai - local AI commit assistant")
    parser.add_argument("--no-confirm", action="store_true", help="Skip the confirmation prompt")
    parser.add_argument("--changelog-only", action="store_true", help="Only update CHANGELOG.md")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model to use")
    parser.add_argument("--pr", action="store_true", help="Generate a pull request description")
    args = parser.parse_args()

    try:
        ensure_git_repo()
        print_banner()

        with console.status("[bold cyan]🔍 Reading staged diff..."):
            diff = get_staged_diff()
            files = get_staged_files()
            diff_stat = get_diff_stat()
            recent_commits = get_recent_commits()
            suggested_type = suggest_commit_type(files, diff)
            suggested_scope = suggest_scope(files)

        with console.status(f"[bold cyan]🤖 Checking Ollama model {args.model}..."):
            validate_model_available(args.model)

        with console.status("[bold cyan]🤖 Asking Ollama for a commit message..."):
            raw_commit_message = ask_ollama(
                build_commit_prompt(diff, diff_stat, files, recent_commits, suggested_type, suggested_scope),
                args.model,
            )

        commit_message = sanitize_commit_message(raw_commit_message, suggested_type, suggested_scope)
        if not commit_message:
            commit_message = fallback_commit_message(suggested_type, suggested_scope)

        if args.pr:
            with console.status("[bold cyan]📝 Generating pull request description..."):
                pr_description = build_pr_description(commit_message, diff_stat, diff, args.model)
            console.print(Panel(pr_description, title="Pull request description", border_style="magenta"))
            return 0

        final_commit_message = commit_message
        if not args.no_confirm and os.environ.get("COMMITAI_HOOK") != "1":
            final_commit_message = prompt_for_edit(commit_message)
            final_commit_message = sanitize_commit_message(final_commit_message, suggested_type, suggested_scope)

        with console.status("[bold cyan]📝 Updating changelog..."):
            changelog_entry = build_changelog_entry(final_commit_message, diff_stat, diff, args.model)
            prepend_changelog(changelog_entry)
            if not args.changelog_only:
                stage_changelog()

        if args.changelog_only:
            render_success("done", "Changelog updated. No commit was created.")
            return 0

        if os.environ.get("COMMITAI_HOOK") == "1":
            write_commit_message_file(final_commit_message)
            render_success("hook", "Commit message prepared for git commit.")
            return 0

        with console.status("[bold cyan]🚀 Creating git commit..."):
            commit_changes(final_commit_message)

        render_success("success", f"Committed with message:\n{final_commit_message}")
        return 0
    except CommitAIError as exc:
        return abort(str(exc))
    except KeyboardInterrupt:
        return abort("Operation cancelled.")


if __name__ == "__main__":
    raise SystemExit(main())
