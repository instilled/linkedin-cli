# linkedin-cli

CLI tool for your LinkedIn analytics — post impressions, reactions, comments, and profile viewers.

Uses browser automation ([Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)) to extract data from LinkedIn's analytics pages. No API keys or developer app needed.

## Install

```bash
# Requires Python 3.11+ and uv
uv tool install git+https://github.com/fabio-bernasconi/linkedin-cli
```

Or clone and install locally:

```bash
git clone https://github.com/fabio-bernasconi/linkedin-cli
cd linkedin-cli
uv sync
uv run linkedin --help
```

On first run, Chromium will be downloaded automatically if not already installed.

## Usage

### 1. Login

```bash
linkedin login
```

A browser window opens — log in to LinkedIn as you normally would. Once you reach the feed, the session is saved to `~/.config/linkedin-cli/session.json`. Sessions last until LinkedIn expires them (typically weeks).

### 2. Post analytics

```bash
linkedin posts           # Rich table output
linkedin posts --json    # JSON (for AI/scripts)
```

Shows your posts with impressions, reactions, comments, and reposts. Also includes a summary with total impressions and members reached vs. prior period.

### 3. Profile viewers

```bash
linkedin views           # Rich table output
linkedin views --json    # JSON (for AI/scripts)
```

Shows who viewed your profile — names, headlines, and when they viewed. Anonymous viewers show as "Someone at {Company}".

### 4. Debug

```bash
linkedin dump posts      # Raw API responses from analytics page
linkedin dump views      # Raw API responses from profile views page
```

### 5. Logout

```bash
linkedin logout          # Clears saved session
```

## JSON output

Both `posts --json` and `views --json` produce structured JSON, useful for piping into other tools or AI assistants:

```bash
linkedin posts --json | jq '.posts[] | {text: .text[:60], impressions}'
```

## How it works

1. **Login**: Opens a real Chromium browser (via Patchright) for you to log in manually. Saves cookies.
2. **Scraping**: Navigates to LinkedIn's analytics pages headlessly and parses the rendered page text.
3. **Anti-detection**: Patchright patches Playwright's automation flags. Realistic Chrome/macOS fingerprint with proper `sec-ch-ua` headers.

## Notes

- Session is stored in `~/.config/linkedin-cli/` with `0600` permissions
- LinkedIn may rate-limit or challenge automated access — if you get errors, wait a bit and try again
- Profile viewer details depend on your LinkedIn plan — Premium shows more viewers
- This tool reads your own analytics; it does not access other people's data
