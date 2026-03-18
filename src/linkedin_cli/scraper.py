"""LinkedIn data extraction via Patchright browser automation.

Strategy: navigate to LinkedIn analytics pages, extract data from the
rendered DOM text.  LinkedIn's internal API responses are hard to capture
reliably, but the page text has a very regular structure.
"""

import json
import re
from datetime import datetime, timedelta

from patchright.sync_api import sync_playwright

from .browser import create_page, is_logged_in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _navigate(page, url, *, wait_ms=5000):
    """Navigate and wait for content to settle."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(wait_ms)


def _num(val):
    """Best-effort int extraction from a string like ' 666' or '1,418'."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        val = val.replace(",", "").strip()
        m = re.search(r"\d+", val)
        return int(m.group()) if m else 0
    return 0


def _time_range_param(days):
    """Return the LinkedIn timeRange URL param covering at least *days*."""
    for threshold, param in [
        (7, "past_7_days"),
        (14, "past_14_days"),
        (28, "past_28_days"),
        (90, "past_90_days"),
        (365, "past_365_days"),
    ]:
        if days <= threshold:
            return param
    return "past_365_days"


_TIMEAGO_RE = re.compile(r"^(\d+)\s*(mo|yr|m|h|d|w|y)$")


def _parse_timeago(timeago_str):
    """Convert a relative time string like '5d', '2mo', '6yr' to a datetime."""
    now = datetime.now()
    m = _TIMEAGO_RE.match(timeago_str.strip())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    delta = {
        "m": timedelta(minutes=val),
        "h": timedelta(hours=val),
        "d": timedelta(days=val),
        "w": timedelta(weeks=val),
        "mo": timedelta(days=val * 30),
        "y": timedelta(days=val * 365),
        "yr": timedelta(days=val * 365),
    }.get(unit)
    return (now - delta) if delta else None


_ACTIVITY_ID_RE = re.compile(r"urn:li:activity:(\d+)")


def _activity_id_to_datetime(activity_id):
    """Extract the exact publish time from a LinkedIn Snowflake activity ID."""
    from datetime import timezone
    ts_ms = int(activity_id) >> 22
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _extract_activity_ids(page):
    """Return a list of activity IDs from the post links on the page."""
    seen = []
    links = page.locator('a[href*="/feed/update/urn:li:activity:"]').all()
    for link in links:
        href = link.get_attribute("href") or ""
        m = _ACTIVITY_ID_RE.search(href)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _load_all_posts(page):
    """Click the 'Show more' pagination button to load all posts.

    Be careful NOT to click the '…show more' text-expansion links on
    individual posts — target only the pagination button at the bottom.
    """
    for _ in range(50):  # safety limit
        # Use a tight text match: the pagination button says exactly "Show more"
        # (with possible trailing arrow).  The post-expand links say "…show more".
        btn = page.locator("button", has_text=re.compile(r"^Show more")).first
        try:
            if btn.is_visible(timeout=1000):
                btn.scroll_into_view_if_needed()
                btn.click()
                page.wait_for_timeout(2000)
            else:
                break
        except Exception:
            break


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

_POST_HEADER_RE = re.compile(r"^(.+?) posted this • (.+)$")
_IMPRESSION_LINE_RE = re.compile(r"^ +[\d,]+$")  # e.g. " 666" — must have leading space
_COMMENT_RE = re.compile(r"^(\d+)\s+comments?$")
_REPOST_RE = re.compile(r"^(\d+)\s+reposts?$")


def scrape_posts(days=90, debug=False):
    """Return list[dict] of posts with impression/reaction/comment stats.

    *days* controls how far back to look (default 90).
    """
    with sync_playwright() as p:
        browser, page = create_page(p)
        try:
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            url = (
                f"https://www.linkedin.com/analytics/creator/top-posts/"
                f"?endDate={end}&metricType=IMPRESSIONS"
                f"&startDate={start}&timeRange={_time_range_param(days)}"
            )
            _navigate(page, url)
            if not is_logged_in(page):
                raise RuntimeError("Session expired. Run 'linkedin login' again.")

            # Load all posts
            _load_all_posts(page)

            # Extract activity IDs (Snowflake IDs with exact timestamps)
            activity_ids = _extract_activity_ids(page)

            # Extract summary stats
            summary = _parse_summary(page)

            # Extract individual posts
            text = page.inner_text("body")
            posts = _parse_posts_from_text(text)

            # Match activity IDs to posts (same order on the page)
            for i, post in enumerate(posts):
                if i < len(activity_ids):
                    dt = _activity_id_to_datetime(activity_ids[i])
                    post["published_at"] = dt.isoformat()
                    post["activity_id"] = activity_ids[i]
                else:
                    # Fallback to timeago approximation
                    dt = _parse_timeago(post["timeago"])
                    if dt:
                        post["published_at"] = dt.isoformat()

            # Filter by requested window
            cutoff = datetime.now(tz=__import__("datetime").timezone.utc) - timedelta(days=days)
            filtered = [
                p for p in posts
                if "published_at" not in p
                or datetime.fromisoformat(p["published_at"]) >= cutoff
            ]

            if debug:
                print(f"Summary: {json.dumps(summary, indent=2)}")
                print(f"Posts found: {len(filtered)} (of {len(posts)} total)")

            return {"summary": summary, "posts": filtered}
        finally:
            browser.close()


def _parse_summary(page):
    """Extract the summary stats (total impressions, members reached)."""
    text = page.inner_text("body")
    summary = {}

    # "1,418\n\nImpressions\n\n44.8% vs. prior 7 days"
    m = re.search(r"([\d,]+)\s+Impressions\s+([\d.]+%)\s+vs\.\s+prior", text)
    if m:
        summary["impressions"] = _num(m.group(1))
        summary["impressions_change"] = m.group(2)

    # "729\n\nMembers reached\n\n53.5% vs. prior 7 days"
    m = re.search(r"([\d,]+)\s+Members reached\s+([\d.]+%)\s+vs\.\s+prior", text)
    if m:
        summary["members_reached"] = _num(m.group(1))
        summary["members_reached_change"] = m.group(2)

    return summary


def _parse_posts_from_text(text):
    """Parse individual post stats from the page body text.

    The page text has this repeating pattern per post:
        {Author} posted this • {timeago}
        {timeago}
        {post body ...}
        …show more
        {reactions_count}              ← may be absent
        [{N} comment(s)]               ← optional
        [{N} repost(s)]                ← optional
         {impressions_count}           ← number with leading whitespace
        Impressions
        View analytics
    """
    posts = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]
        header_match = _POST_HEADER_RE.match(line.strip())
        if not header_match:
            i += 1
            continue

        author = header_match.group(1)
        timeago = header_match.group(2).strip()

        # Collect lines until "View analytics"
        post_lines = []
        i += 1
        while i < len(lines) and lines[i].strip() != "View analytics":
            post_lines.append(lines[i])
            i += 1
        i += 1  # skip "View analytics"

        # Parse from the end of post_lines backwards to find metrics
        impressions = 0
        reactions = 0
        comments = 0
        reposts = 0

        # Work backwards through the trailing metric lines
        tail = list(reversed(post_lines))
        metric_end = 0
        for j, tl in enumerate(tail):
            stripped = tl.strip()
            if stripped == "Impressions":
                continue
            if _IMPRESSION_LINE_RE.match(tl) and stripped:
                impressions = _num(stripped)
                metric_end = j + 1
                continue
            cm = _COMMENT_RE.match(stripped)
            if cm:
                comments = _num(cm.group(1))
                metric_end = j + 1
                continue
            rm = _REPOST_RE.match(stripped)
            if rm:
                reposts = _num(rm.group(1))
                metric_end = j + 1
                continue
            # A bare number right before Impressions = reactions count
            if re.match(r"^\d+$", stripped):
                reactions = _num(stripped)
                metric_end = j + 1
                continue
            break

        # The remaining lines (minus metrics from the tail) are the post body
        body_lines = post_lines[:len(post_lines) - metric_end] if metric_end else post_lines
        # Skip the duplicate timeago line at the start
        if body_lines and body_lines[0].strip() == timeago:
            body_lines = body_lines[1:]
        # Get first meaningful line as preview
        body_text = "\n".join(l for l in body_lines if l.strip())
        # Trim to first paragraph
        preview = ""
        for bl in body_lines:
            bl = bl.strip()
            if bl and bl != "…show more":
                preview = bl[:200]
                break

        posts.append({
            "author": author,
            "timeago": timeago,
            "text": preview,
            "impressions": impressions,
            "reactions": reactions,
            "comments": comments,
            "reposts": reposts,
        })

    return posts


# ---------------------------------------------------------------------------
# Profile views
# ---------------------------------------------------------------------------

def scrape_profile_views(debug=False):
    """Return dict with total_views and viewers."""
    with sync_playwright() as p:
        browser, page = create_page(p)
        try:
            _navigate(page, "https://www.linkedin.com/me/profile-views/")
            if not is_logged_in(page):
                raise RuntimeError("Session expired. Run 'linkedin login' again.")

            text = page.inner_text("body")
            if debug:
                print(text[:3000])

            result = _parse_views_from_text(text)

            # Try alternate URL if nothing found
            if not result["total_views"] and not result["viewers"]:
                _navigate(page, "https://www.linkedin.com/analytics/creator/profile-views/")
                text = page.inner_text("body")
                if debug:
                    print(text[:3000])
                result = _parse_views_from_text(text)

            return result
        finally:
            browser.close()


def _parse_views_from_text(text):
    """Extract profile view data from page text.

    Identified viewers look like:
        {Name}
        View {Name}'s profile
        · {degree}
        {Headline}
        Viewed {timeago} ago

    Anonymous viewers look like:
        Someone at {Company}
        View
    """
    result = {"total_views": 0, "viewers": []}

    # Total view count: "107\n\nProfile viewers in the past 90 days"
    m = re.search(r"([\d,]+)\s*\n+\s*Profile viewers?", text, re.IGNORECASE)
    if not m:
        m = re.search(r"([\d,]+)\s*(?:profile\s*view|viewer)", text, re.IGNORECASE)
    if m:
        result["total_views"] = _num(m.group(1))

    lines = text.split("\n")
    seen = set()

    # Find the viewer details section
    start = 0
    for i, line in enumerate(lines):
        if "Viewer details" in line or "Browse up to" in line:
            start = i + 1
            break

    i = start
    while i < len(lines):
        stripped = lines[i].strip()

        # "Viewed 1d ago" → look backwards for the viewer info
        viewed_match = re.match(r"Viewed (.+?) ago", stripped)
        if viewed_match:
            viewed_at = viewed_match.group(1)
            # Walk backwards to find name and headline
            name, headline = _extract_viewer_backwards(lines, i)
            if name and name not in seen:
                seen.add(name)
                result["viewers"].append({
                    "name": name,
                    "headline": headline,
                    "viewed_at": viewed_at,
                })
            i += 1
            continue

        # "Someone at {Company}" or "Someone in the {Industry}"
        someone_match = re.match(r"Someone (?:at|in)(?: the)?\s+(.+)", stripped)
        if someone_match:
            name = stripped
            if name not in seen:
                seen.add(name)
                result["viewers"].append({
                    "name": name,
                    "headline": "",
                    "viewed_at": "",
                })
            i += 1
            continue

        # Stop at footer
        if stripped in ("About", "Show more results"):
            break

        i += 1

    return result


def _extract_viewer_backwards(lines, viewed_line_idx):
    """Walk backwards from a 'Viewed X ago' line to find name and headline."""
    name = ""
    headline = ""

    # Boundary markers — these indicate the END of a previous viewer entry.
    # STOP (don't skip) when we hit one.
    boundary = {"Message", "Connect", "Search", "Follow"}
    skip = {"View", ""}

    j = viewed_line_idx - 1
    candidates = []
    while j >= 0 and len(candidates) < 4:
        s = lines[j].strip()
        # Stop at boundaries (buttons from previous entry)
        if s in boundary:
            break
        if (
            s in skip
            or s.startswith("View ")
            or s.startswith("Viewed ")
            or "mutual connection" in s
        ):
            j -= 1
            continue
        if s.startswith("·"):  # degree indicator like "· 3rd"
            j -= 1
            continue
        candidates.append(s)
        j -= 1

    # candidates are in reverse order: [headline, name, ...]
    if len(candidates) >= 2:
        headline = candidates[0]
        name = candidates[1]
    elif len(candidates) == 1:
        name = candidates[0]

    return name, headline


# ---------------------------------------------------------------------------
# Dump (debug)
# ---------------------------------------------------------------------------

def dump_page(url):
    """Navigate to a URL and return the page text + screenshot path."""
    with sync_playwright() as p:
        browser, page = create_page(p)
        try:
            captured = []

            def _on_response(response):
                try:
                    u = response.url
                    ct = response.headers.get("content-type", "")
                    if response.ok and "linkedin.com" in u and "json" in ct:
                        captured.append(response)
                except Exception:
                    pass

            page.on("response", _on_response)
            _navigate(page, url)

            if not is_logged_in(page):
                raise RuntimeError("Session expired. Run 'linkedin login' again.")

            api_responses = []
            for r in captured:
                try:
                    api_responses.append({"url": r.url, "data": r.json()})
                except Exception:
                    pass

            return {
                "url": url,
                "page_url": page.url,
                "page_title": page.title(),
                "page_text": page.inner_text("body"),
                "responses": api_responses,
            }
        finally:
            browser.close()
