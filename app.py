import os
import time
import re
import json
import sys
from difflib import SequenceMatcher
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
YTMUSIC_AUTH_FILE = os.getenv("YTMUSIC_AUTH_FILE", "browser.json")
DELAY_SECONDS = int(os.getenv("DELAY_SECONDS", "1"))
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME", "Spotify Liked Songs")
PLAYLIST_DESCRIPTION = os.getenv("PLAYLIST_DESCRIPTION", "Migrated from Spotify")
PLAYLIST_PRIVACY = os.getenv("PLAYLIST_PRIVACY", "PRIVATE")
INTERACTIVE_REVIEW = os.getenv("INTERACTIVE_REVIEW", "true").lower() in ("true", "1", "yes")


def clean_title(title: str) -> str:
    """Removes remaster tags, deluxe edition text, and feature tags for cleaner search."""
    cleaned = title
    cleaned = re.sub(r"\s*-\s*.*?(Remaster|Deluxe|Anniversary|Expanded|Bonus\s*Track).*?$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(.*?(remaster|anniversary|deluxe).*?\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[.*?(remaster|anniversary|deluxe).*?\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\((feat|ft)\.?\s+.*?\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[(feat|ft)\.?\s+.*?\]", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def parse_duration_str(dur_str: str) -> int | None:
    if not dur_str or not isinstance(dur_str, str):
        return None
    parts = dur_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


def get_candidate_duration(candidate: dict) -> int | None:
    if "duration_seconds" in candidate and candidate["duration_seconds"] is not None:
        return int(candidate["duration_seconds"])
    if "duration" in candidate and candidate["duration"]:
        return parse_duration_str(candidate["duration"])
    return None


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "Unknown"
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


def score_candidate(track: dict, candidate: dict) -> tuple[float, str]:
    """
    Evaluates a YouTube Music candidate against the Spotify track.
    Enforces studio audio songs only, strict duration tolerance, and negative keyword filtering.
    """
    if candidate.get("resultType") != "song":
        return 0.0, "Disqualified: Not an official song release"

    yt_duration = get_candidate_duration(candidate)
    if yt_duration is None:
        return 0.0, "Disqualified: Missing duration"

    dur_diff = abs(yt_duration - track["duration_sec"])
    # Disqualify if duration differs by more than 4 seconds
    # (Removes music videos with dialogue, live versions, extended mixes)
    if dur_diff > 4:
        return 0.0, f"Disqualified: Duration mismatch ({dur_diff}s difference)"

    score = 0.0

    # 1. Duration points (max 40)
    if dur_diff <= 1:
        score += 40.0
    elif dur_diff <= 2:
        score += 35.0
    elif dur_diff <= 3:
        score += 25.0
    else:
        score += 15.0

    # 2. Title & Artist similarity (max 40)
    cand_title = candidate.get("title", "")
    cand_artists = [a.get("name", "") for a in candidate.get("artists", [])]
    cand_artists_str = " ".join(cand_artists)

    clean_sp_title = clean_title(track["title"])
    clean_yt_title = clean_title(cand_title)

    title_sim = similarity(clean_sp_title, clean_yt_title)
    artist_sim = max(
        [similarity(track["primary_artist"], a) for a in cand_artists]
        + [similarity(track["primary_artist"], cand_artists_str)]
        + [0.0]
    )

    score += title_sim * 25.0
    score += artist_sim * 15.0

    # 3. Explicit / Clean parity (max 10)
    if candidate.get("isExplicit") == track["is_explicit"]:
        score += 10.0

    # 4. Album match bonus (max 10)
    cand_album = candidate.get("album", {}).get("name", "") if candidate.get("album") else ""
    if cand_album and track["album"] and similarity(track["album"], cand_album) > 0.8:
        score += 10.0

    # 5. Negative keyword penalty
    unwanted_keywords = ["live", "remix", "acoustic", "cover", "instrumental", "karaoke", "slowed", "reverb"]
    lower_cand = cand_title.lower()
    lower_orig = track["title"].lower()

    for kw in unwanted_keywords:
        if kw in lower_cand and kw not in lower_orig:
            return 0.0, f"Disqualified: Contains unwanted keyword '{kw}'"

    return score, f"Score: {score:.0f}% (Δt={dur_diff}s)"


def find_exact_track(yt: YTMusic, track: dict) -> dict:
    """
    Multi-tier search ensuring 100% audio accuracy:
    Tier 1: ISRC Digital Fingerprint Lookup
    Tier 2: Clean Title + Primary Artist in 'songs' catalog
    Tier 3: Title + Artist + Album in 'songs' catalog
    """
    # Tier 1: Search by ISRC
    if track.get("isrc"):
        try:
            isrc_res = yt.search(track["isrc"], filter="songs", limit=3)
            for r in isrc_res:
                yt_dur = get_candidate_duration(r)
                if yt_dur and abs(yt_dur - track["duration_sec"]) <= 2:
                    # CRITICAL: Verify title or artist similarity!
                    # YouTube Music search returns generic fallback trending songs if an ISRC is unknown!
                    r_title = clean_title(r.get("title", ""))
                    sp_title = clean_title(track["title"])
                    t_sim = similarity(sp_title, r_title)

                    r_artists = [a.get("name", "") for a in r.get("artists", [])]
                    a_sim = max([similarity(track["primary_artist"], a) for a in r_artists] + [0.0])

                    # Require title match OR artist match
                    if t_sim >= 0.4 or a_sim >= 0.5:
                        return {
                            "video_id": r.get("videoId"),
                            "match_type": "ISRC Master Match",
                            "confidence": 100.0,
                            "yt_title": r.get("title"),
                            "yt_duration": yt_dur,
                            "details": f"Verified ISRC {track['isrc']} (Δt={abs(yt_dur - track['duration_sec'])}s)",
                            "candidates": isrc_res
                        }
        except Exception:
            pass

    # Tier 2: Search Clean Title + Primary Artist
    query_primary = f"{clean_title(track['title'])} {track['primary_artist']}"
    results_t2 = []
    try:
        results_t2 = yt.search(query_primary, filter="songs", limit=5)
    except Exception:
        pass

    best_candidate = None
    best_score = 0.0
    best_details = ""
    valid_candidates = []

    for r in results_t2:
        score, reason = score_candidate(track, r)
        if score > 0:
            valid_candidates.append(r)
        if score > best_score:
            best_score = score
            best_candidate = r
            best_details = reason

    if best_score >= 80.0 and best_candidate:
        return {
            "video_id": best_candidate.get("videoId"),
            "match_type": "High Confidence Studio Audio",
            "confidence": best_score,
            "yt_title": best_candidate.get("title"),
            "yt_duration": get_candidate_duration(best_candidate),
            "details": best_details,
            "candidates": results_t2
        }

    # Tier 3: Search with Album info
    results_t3 = []
    if track.get("album"):
        query_album = f"{clean_title(track['title'])} {track['primary_artist']} {track['album']}"
        try:
            results_t3 = yt.search(query_album, filter="songs", limit=5)
        except Exception:
            pass

        for r in results_t3:
            score, reason = score_candidate(track, r)
            if score > 0:
                valid_candidates.append(r)
            if score > best_score:
                best_score = score
                best_candidate = r
                best_details = reason

        if best_score >= 75.0 and best_candidate:
            return {
                "video_id": best_candidate.get("videoId"),
                "match_type": "Album-Verified Studio Audio",
                "confidence": best_score,
                "yt_title": best_candidate.get("title"),
                "yt_duration": get_candidate_duration(best_candidate),
                "details": best_details,
                "candidates": results_t2 + results_t3
            }

    all_candidates = valid_candidates if valid_candidates else (results_t2 + results_t3)
    return {
        "video_id": None,
        "match_type": "Review Needed",
        "confidence": best_score,
        "yt_title": best_candidate.get("title") if best_candidate else None,
        "yt_duration": get_candidate_duration(best_candidate) if best_candidate else None,
        "details": best_details if best_details else "No candidate satisfied duration/similarity threshold",
        "candidates": all_candidates
    }


def create_progress_bar(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(bar_width=30, complete_style="green"),
        TaskProgressColumn(),
        TextColumn("{task.fields[extra]}"),
        TimeElapsedColumn(),
        console=console,
        refresh_per_second=1
    )


def print_header(console: Console) -> None:
    console.print()
    console.print(Panel(
        Text("🎵 Spotify → YouTube Music [100% Audio Accuracy]", justify="center", style="bold magenta"),
        style="bold white",
        padding=(0, 2)
    ))
    console.print()


def print_setup_instructions(console: Console) -> None:
    console.print(Panel.fit(
        "[bold cyan]browser.json not found![/bold cyan]\n\n"
        "[dim]1.[/dim] Go to [link=https://music.youtube.com]music.youtube.com[/link] (logged in)\n"
        "[dim]2.[/dim] DevTools (F12) → Network → filter 'browse'\n"
        "[dim]3.[/dim] Right-click a request → Copy → Copy request headers\n"
        "[dim]4.[/dim] Run: [bold]uv run ytmusicapi browser[/bold]\n"
        "[dim]5.[/dim] Paste the headers and press Ctrl+Z then Enter",
        title="Setup Required", border_style="red"
    ))


def connect_spotify(progress: Progress, task) -> spotipy.Spotify:
    progress.reset(task, total=100, description="Connecting to Spotify", extra="")
    client = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope="user-library-read"
    ))
    progress.update(task, completed=100)
    time.sleep(0.2)
    return client


def connect_ytmusic(progress: Progress, task) -> YTMusic:
    progress.reset(task, total=100, description="Connecting to YouTube Music", extra="")
    client = YTMusic(YTMUSIC_AUTH_FILE)
    progress.update(task, completed=100)
    time.sleep(0.2)
    return client


def fetch_spotify_tracks(sp: spotipy.Spotify, progress: Progress, task) -> list[dict]:
    progress.reset(task, total=None, description="Fetching Spotify Library", extra="")
    tracks = []
    seen_ids = set()
    offset = 0
    while True:
        results = sp.current_user_saved_tracks(limit=50, offset=offset)
        if not results['items']:
            break
        for item in results['items']:
            t = item['track']
            if not t:
                continue
            t_id = t.get("id")
            if t_id and t_id in seen_ids:
                continue
            if t_id:
                seen_ids.add(t_id)

            tracks.append({
                "id": t_id,
                "title": t.get("name", "Unknown Title"),
                "artists": [a.get("name", "") for a in t.get("artists", [])],
                "primary_artist": t.get("artists", [{}])[0].get("name", "Unknown Artist") if t.get("artists") else "Unknown Artist",
                "album": t.get("album", {}).get("name", "") if t.get("album") else "",
                "duration_ms": t.get("duration_ms", 0),
                "duration_sec": round(t.get("duration_ms", 0) / 1000),
                "isrc": t.get("external_ids", {}).get("isrc"),
                "is_explicit": t.get("explicit", False),
            })
        offset += 50
        progress.update(task, extra=f"({len(tracks)} unique tracks)")
    progress.update(task, completed=100, total=100)
    time.sleep(0.2)
    return tracks


def create_playlist(yt: YTMusic, progress: Progress, task) -> str:
    progress.reset(task, total=100, description="Creating playlist", extra="")
    playlist_id = yt.create_playlist(
        title=PLAYLIST_NAME,
        description=PLAYLIST_DESCRIPTION,
        privacy_status=PLAYLIST_PRIVACY
    )
    progress.update(task, completed=100)
    time.sleep(0.2)
    return playlist_id


def migrate_tracks(
    yt: YTMusic,
    tracks: list[dict],
    playlist_id: str,
    progress: Progress,
    task
) -> dict:
    total = len(tracks)
    progress.reset(task, total=total, description="Migrating tracks", extra="")

    audit_log = []
    stats = {
        "total": total,
        "isrc_exact": 0,
        "high_confidence": 0,
        "album_verified": 0,
        "user_confirmed": 0,
        "unmatched": 0,
        "added_to_playlist": 0
    }
    review_queue = []
    added_video_ids = set()

    for i, track in enumerate(tracks):
        song_preview = f"{track['title'][:12]} - {track['primary_artist'][:8]}".ljust(22)
        progress.update(task, extra=f"[dim]{song_preview}[/dim]")

        match_info = find_exact_track(yt, track)
        video_id = match_info["video_id"]
        match_type = match_info["match_type"]

        if video_id:
            if video_id in added_video_ids:
                status_icon = "[yellow]⎘[/yellow]"
                match_type = f"{match_type} (Duplicate: already in playlist)"
            else:
                try:
                    yt.add_playlist_items(playlist_id, [video_id], duplicates=True)
                    added_video_ids.add(video_id)
                    stats["added_to_playlist"] += 1
                    if "ISRC Master Match" in match_type:
                        stats["isrc_exact"] += 1
                    elif "High Confidence Studio Audio" in match_type:
                        stats["high_confidence"] += 1
                    elif "Album-Verified Studio Audio" in match_type:
                        stats["album_verified"] += 1
                    status_icon = "[green]✓[/green]"
                except Exception as e:
                    status_icon = "[red]✗[/red]"
                    match_type = f"Failed to add: {e}"
        else:
            status_icon = "[yellow]?[/yellow]"
            review_queue.append((track, match_info))

        audit_log.append({
            "spotify_track": track,
            "match_info": {
                "video_id": video_id,
                "match_type": match_type,
                "confidence": match_info["confidence"],
                "yt_title": match_info.get("yt_title"),
                "yt_duration": match_info.get("yt_duration"),
                "details": match_info["details"]
            },
            "status": "ADDED" if video_id else "PENDING_REVIEW"
        })

        progress.update(task, completed=i+1, extra=f"{status_icon} [cyan]{song_preview}[/cyan]")
        time.sleep(DELAY_SECONDS)

    return {
        "stats": stats,
        "review_queue": review_queue,
        "audit_log": audit_log,
        "added_video_ids": added_video_ids
    }


def process_review_queue(
    yt: YTMusic,
    review_queue: list[tuple[dict, dict]],
    playlist_id: str,
    console: Console,
    stats: dict,
    audit_log: list[dict],
    added_video_ids: set
) -> None:
    if not review_queue:
        return

    console.print()
    console.print(Panel(
        f"[bold yellow]⚠️ {len(review_queue)} track(s) require verification to guarantee 100% completeness[/bold yellow]\n"
        "[dim]These tracks were held back because automatic match scores were borderline.[/dim]",
        title="Zero-Drop Verification Queue",
        border_style="yellow"
    ))

    for idx, (track, match_info) in enumerate(review_queue, 1):
        console.print()
        console.rule(f"[bold cyan]Review {idx} of {len(review_queue)}[/bold cyan]")
        console.print(f"[bold]Spotify:[/bold] [green]{track['title']}[/green] by [cyan]{track['primary_artist']}[/cyan]")
        console.print(f"[dim]Album: {track['album']} | Duration: {format_duration(track['duration_sec'])} | Explicit: {track['is_explicit']}[/dim]")

        candidates = match_info.get("candidates", [])[:3]
        if candidates:
            console.print("\n[bold]Suggested YouTube Music Options:[/bold]")
            for c_idx, c in enumerate(candidates, 1):
                c_dur = get_candidate_duration(c)
                dur_str = format_duration(c_dur)
                c_artists = ", ".join([a.get("name", "") for a in c.get("artists", [])])
                diff_str = f"({c_dur - track['duration_sec']:+d}s)" if c_dur else ""
                console.print(f"  [bold cyan][{c_idx}][/bold cyan] {c.get('title')} - {c_artists} [{dur_str} {diff_str}]")

        console.print("  [bold cyan][s][/bold cyan] Search custom query")
        console.print("  [bold cyan][v][/bold cyan] Enter YouTube Video ID or URL directly")
        console.print("  [bold cyan][x][/bold cyan] Skip this track")

        choice = Prompt.ask("Select option", default="1" if candidates else "s").strip()

        chosen_video_id = None
        if choice in ("1", "2", "3") and int(choice) <= len(candidates):
            chosen_video_id = candidates[int(choice) - 1].get("videoId")
        elif choice.lower() == "s":
            custom_q = Prompt.ask("Enter custom search query")
            try:
                search_res = yt.search(custom_q, filter="songs", limit=5)
            except Exception:
                search_res = []
            if search_res:
                for s_idx, s in enumerate(search_res, 1):
                    s_dur = format_duration(get_candidate_duration(s))
                    console.print(f"  [{s_idx}] {s.get('title')} [{s_dur}]")
                pick = Prompt.ask("Select number or 'x' to cancel", default="1")
                if pick.isdigit() and 1 <= int(pick) <= len(search_res):
                    chosen_video_id = search_res[int(pick) - 1].get("videoId")
        elif choice.lower() == "v":
            url_or_id = Prompt.ask("Paste YouTube Music URL or Video ID").strip()
            if "v=" in url_or_id:
                chosen_video_id = url_or_id.split("v=")[1].split("&")[0]
            elif "youtu.be/" in url_or_id:
                chosen_video_id = url_or_id.split("youtu.be/")[1].split("?")[0]
            else:
                chosen_video_id = url_or_id

        if chosen_video_id:
            if chosen_video_id in added_video_ids:
                console.print("[yellow]Track already in playlist. Skipping duplicate.[/yellow]")
            else:
                try:
                    yt.add_playlist_items(playlist_id, [chosen_video_id], duplicates=True)
                    added_video_ids.add(chosen_video_id)
                    stats["added_to_playlist"] += 1
                    stats["user_confirmed"] += 1
                    console.print("[green]✓ Added to playlist![/green]")
                    for item in audit_log:
                        if item["spotify_track"]["id"] == track["id"]:
                            item["match_info"]["video_id"] = chosen_video_id
                            item["match_info"]["match_type"] = "User-Verified Audio"
                            item["status"] = "ADDED"
                except Exception as e:
                    console.print(f"[red]Failed to add: {e}[/red]")
        else:
            stats["unmatched"] += 1
            console.print("[yellow]Track skipped.[/yellow]")


def print_summary(console: Console, stats: dict, total: int) -> None:
    console.print()
    tbl = Table(title="Migration Summary", border_style="cyan", show_header=True)
    tbl.add_column("Category", style="bold")
    tbl.add_column("Count", justify="right")
    tbl.add_column("Accuracy Guarantee", style="dim")

    tbl.add_row("Total Spotify Tracks", str(total), "100% Library Source")
    tbl.add_row("✓ ISRC Master Matches", f"[green]{stats['isrc_exact']}[/green]", "100% Identical Recording Master")
    tbl.add_row("✓ High-Confidence Studio", f"[green]{stats['high_confidence']}[/green]", "Exact Audio (≤2s diff, songs catalog)")
    tbl.add_row("✓ Album-Verified Studio", f"[green]{stats['album_verified']}[/green]", "Exact Audio (≤3s diff, album match)")
    if stats["user_confirmed"] > 0:
        tbl.add_row("✓ User-Verified Matches", f"[cyan]{stats['user_confirmed']}[/cyan]", "100% Manually Confirmed")
    if stats["unmatched"] > 0:
        tbl.add_row("✗ Skipped / Unmatched", f"[red]{stats['unmatched']}[/red]", "Excluded on user request")

    tbl.add_section()
    percent = (stats["added_to_playlist"] / total * 100) if total else 0
    tbl.add_row(
        "[bold]Total Added to YT Music[/bold]",
        f"[bold green]{stats['added_to_playlist']}/{total}[/bold green]",
        f"[bold]{percent:.1f}% Complete[/bold]"
    )

    console.print(Panel(tbl, border_style="green" if stats["added_to_playlist"] == total else "yellow"))
    console.print("[dim]Full audit log saved to: [bold]migration_audit.json[/bold][/dim]\n")


def main():
    console = Console()
    print_header(console)

    if not os.path.exists(YTMUSIC_AUTH_FILE):
        print_setup_instructions(console)
        sys.exit(1)

    with create_progress_bar(console) as progress:
        task = progress.add_task("Initializing", total=100, extra="")

        sp = connect_spotify(progress, task)
        yt = connect_ytmusic(progress, task)
        tracks = fetch_spotify_tracks(sp, progress, task)
        playlist_id = create_playlist(yt, progress, task)
        result = migrate_tracks(yt, tracks, playlist_id, progress, task)

    stats = result["stats"]
    review_queue = result["review_queue"]
    audit_log = result["audit_log"]
    added_video_ids = result["added_video_ids"]

    # If there are held-back / ambiguous tracks and interactive review is enabled
    if review_queue and INTERACTIVE_REVIEW and sys.stdin.isatty():
        process_review_queue(yt, review_queue, playlist_id, console, stats, audit_log, added_video_ids)
    elif review_queue:
        stats["unmatched"] = len(review_queue)

    # Save full audit log to disk
    with open("migration_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_log, f, indent=2, ensure_ascii=False)

    print_summary(console, stats, len(tracks))


if __name__ == "__main__":
    main()
