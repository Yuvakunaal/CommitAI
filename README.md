# commitai

commitai is a local-first AI Git assistant for Python developers. It reads the staged diff, asks a local Ollama model for a Conventional Commit message, writes a changelog entry, and can create the git commit for you.

## Features

- AI-generated Conventional Commit messages
- Automatic changelog entries in `CHANGELOG.md`
- Local-only inference through Ollama
- Beautiful terminal output with `rich`
- Interactive confirmation and edit flow
- `--no-confirm`, `--changelog-only`, `--model`, and `--pr` flags
- Git hook support for `git commit` workflows

## Why Gemma 4

`gemma4:e2b` is a practical fit for a lightweight developer tool on an 8 GB MacBook Air. It stays local, keeps latency low, and produces useful commit summaries without sending source code to an external API.

## Local-First Benefits

- Your staged code never leaves your machine
- No cloud API keys or rate limits
- Fast feedback for small commit workflows
- Works offline once Ollama and the model are available

## Requirements

- Python 3.13
- Git
- Ollama running locally
- `gemma4:e2b` or another compatible model

## Installation

```bash
pip install -r requirements.txt
ollama pull gemma4:e2b
```

## Ollama Setup

Start Ollama if it is not already running:

```bash
ollama serve
```

If you want a different model, install it in Ollama and pass it with `--model`.

## Usage

Stage your changes first:

```bash
git add .
python commitai.py
```

Common commands:

```bash
python commitai.py --no-confirm
python commitai.py --model llama3
python commitai.py --changelog-only
python commitai.py --pr
```

## CLI Flags

- `--no-confirm` skips the confirmation prompt and commits immediately.
- `--changelog-only` updates `CHANGELOG.md` without creating a commit.
- `--model MODEL_NAME` selects a different local Ollama model.
- `--pr` prints a pull request description instead of committing.

## Git Hook Integration

commitai can be wired into `git commit` with a `prepare-commit-msg` hook.

1. Make the hook executable:

```bash
chmod +x hooks/prepare-commit-msg
```

2. Copy it into your repository hooks directory:

```bash
cp hooks/prepare-commit-msg .git/hooks/prepare-commit-msg
```

3. Commit as usual:

```bash
git commit
```

The hook runs commitai in non-interactive mode, generates the commit message, and lets git continue with the prepared message.

The provided hook sets `COMMITAI_HOOK=1` so commitai writes the generated message into git's commit message file instead of recursively spawning another commit.

## Screenshots

Add terminal screenshots in the `screenshots/` directory to show the commit flow, confirmation prompt, and changelog updates.

## Demo GIF

Add a short walkthrough GIF at `demo/demo.gif` to show the full commit workflow in action.

## Architecture

commitai keeps the workflow intentionally small:

1. Read the staged diff from git.
2. Inspect recent commit subjects and changed files.
3. Send a focused prompt to Ollama.
4. Normalize the AI response into a Conventional Commit message.
5. Append a changelog entry.
6. Commit the staged work or prepare the hook message file.

This keeps the tool easy to understand, easy to maintain, and safe to run locally.

## Example Output

```text
🔍 Reading staged diff...
🤖 Asking Ollama...
✅ Generated commit message
📝 Updating changelog...
✅ Commit completed
```

## Changelog Format

`CHANGELOG.md` uses a simple date-based entry format:

```md
## 2026-05-09

- Added AI commit generation support.
```

## Project Structure

```text
commitai/
├── commitai.py
├── CHANGELOG.md
├── README.md
├── requirements.txt
├── .gitignore
├── hooks/
│   └── prepare-commit-msg
├── demo/
└── screenshots/
```
