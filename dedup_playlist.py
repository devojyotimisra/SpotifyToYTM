import os
import sys
from dotenv import load_dotenv
from ytmusicapi import YTMusic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

YTMUSIC_AUTH_FILE = os.getenv("YTMUSIC_AUTH_FILE", "browser.json")
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME", "Songs")

def main():
    console = Console()
    console.print(Panel("[bold magenta]🧹 YouTube Music Playlist Deduplicator[/bold magenta]", border_style="cyan"))

    if not os.path.exists(YTMUSIC_AUTH_FILE):
        console.print("[red]Error: browser.json not found![/red]")
        sys.exit(1)

    yt = YTMusic(YTMUSIC_AUTH_FILE)

    console.print(f"Finding playlist: [bold cyan]{PLAYLIST_NAME}[/bold cyan]...")
    playlists = yt.get_library_playlists(limit=50)
    target_playlist = next((p for p in playlists if p.get("title") == PLAYLIST_NAME), None)

    if not target_playlist:
        console.print(f"[red]Could not find playlist named '{PLAYLIST_NAME}' in your library.[/red]")
        sys.exit(1)

    playlist_id = target_playlist["playlistId"]
    console.print(f"Fetching songs from playlist ID: [dim]{playlist_id}[/dim]...")
    playlist_data = yt.get_playlist(playlist_id, limit=None)
    tracks = playlist_data.get("tracks", [])

    console.print(f"Total songs currently in playlist: [bold green]{len(tracks)}[/bold green]")

    seen_video_ids = set()
    duplicates_to_remove = []

    for t in tracks:
        vid = t.get("videoId")
        set_vid = t.get("setVideoId")
        if not vid or not set_vid:
            continue

        if vid in seen_video_ids:
            duplicates_to_remove.append({
                "videoId": vid,
                "setVideoId": set_vid,
                "title": t.get("title", "Unknown")
            })
        else:
            seen_video_ids.add(vid)

    if not duplicates_to_remove:
        console.print("[green]✓ No duplicate video IDs found in this playlist![/green]")
        return

    console.print(f"\n[bold yellow]Found {len(duplicates_to_remove)} duplicate song entries to remove:[/bold yellow]")
    tbl = Table(title="Duplicates to Remove", show_header=True)
    tbl.add_column("No.", justify="right", style="dim")
    tbl.add_column("Title", style="bold")
    tbl.add_column("Video ID", style="cyan")

    for i, item in enumerate(duplicates_to_remove[:15], 1):
        tbl.add_row(str(i), item["title"], item["videoId"])
    if len(duplicates_to_remove) > 15:
        tbl.add_row("...", f"... and {len(duplicates_to_remove) - 15} more", "...")

    console.print(tbl)

    confirm = console.input("\n[bold yellow]Proceed with removing these duplicates from YouTube Music? (y/N): [/bold yellow]").strip().lower()
    if confirm not in ("y", "yes"):
        console.print("[yellow]Cancelled. No changes made.[/yellow]")
        return

    console.print(f"Removing {len(duplicates_to_remove)} duplicates...")
    # remove in batches of 50 to avoid request payload limits
    batch_size = 50
    for i in range(0, len(duplicates_to_remove), batch_size):
        batch = duplicates_to_remove[i : i + batch_size]
        yt.remove_playlist_items(playlist_id, batch)
        console.print(f"  Removed items {i + 1} to {min(i + batch_size, len(duplicates_to_remove))}...")

    console.print(Panel(f"[bold green]✓ Successfully removed {len(duplicates_to_remove)} duplicates! New track count: {len(tracks) - len(duplicates_to_remove)}[/bold green]", border_style="green"))

if __name__ == "__main__":
    main()
