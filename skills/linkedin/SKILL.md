---
name: linkedin-cli
description: "LinkedIn analytics CLI: fetch post impressions, engagement stats, and profile viewers via the `linkedin` command. Use this skill whenever the user wants to check LinkedIn post performance, see who viewed their profile, or manage LinkedIn authentication from the terminal."
compatibility: "Requires a Playwright-based browser install."
---

# linkedin-cli

LinkedIn analytics CLI — post impressions & profile views. Uses a headless browser under the hood.

## Commands

### `linkedin posts`
List posts with impression & engagement stats.
```bash
linkedin posts                  # Last 90 days (default)
    linkedin posts --days 30        # Last 30 days
    linkedin posts --json           # Raw JSON output
    linkedin posts --debug          # Include debug info
    ```

### `linkedin views`
    Show who viewed your profile.
    ```bash
    linkedin views
    linkedin views --json
    linkedin views --debug
    ```

### `linkedin auth`
    Manage authentication.
    ```bash
    linkedin auth status            # Show current session status
    linkedin auth login             # Re-authenticate (opens browser window)
    linkedin auth logout            # Clear saved session
    ```

### `linkedin dump`
    Dump raw API responses from a LinkedIn page (for debugging).
    ```bash
    linkedin dump
    ```

## Security Rules

    - **Never** output session tokens or cookies
    - **Always** confirm with user before `linkedin auth logout`

## Notes

    - `--json` flag is useful for piping into `jq` for further processing
