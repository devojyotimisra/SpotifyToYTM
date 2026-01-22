import os
import time
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
YTMUSIC_AUTH_FILE = os.getenv("YTMUSIC_AUTH_FILE")
DELAY_SECONDS = int(os.getenv("DELAY_SECONDS"))
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME")
PLAYLIST_DESCRIPTION = os.getenv("PLAYLIST_DESCRIPTION")
PLAYLIST_PRIVACY = os.getenv("PLAYLIST_PRIVACY")


def create_progress_bar(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(bar_width=30, complete_style="green"),
        TaskProgressColumn(),
        TextColumn("{task.fields[extra]}"),
        TimeElapsedColumn(),
        console=console,
        refresh_per_second=10
    )


def print_header(console: Console) -> None:
    console.print()
    console.print(Panel(
        Text("🎵 Spotify → YouTube Music", justify="center", style="bold magenta"),
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


def print_summary(console: Console, success: int, failed: int, failed_tracks: list) -> None:
    console.print()
    tbl = Table.grid(padding=(0, 2))
    tbl.add_column(style="bold")
    tbl.add_column()
    tbl.add_row("✓ Migrated", f"[green]{success}[/green]")
    tbl.add_row("✗ Failed", f"[red]{failed}[/red]")
    console.print(Panel(tbl, title="[bold]Done[/bold]", border_style="green"))

    if failed_tracks:
        console.print("\n[bold red]Failed:[/bold red]")
        for t in failed_tracks[:10]:
            console.print(f"  [dim]•[/dim] {t}")
        if len(failed_tracks) > 10:
            console.print(f"  [dim]...{len(failed_tracks) - 10} more[/dim]")


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


def fetch_spotify_tracks(sp: spotipy.Spotify, progress: Progress, task) -> list:
    progress.reset(task, total=None, description="Fetching tracks", extra="")
    tracks = []
    offset = 0
    while True:
        results = sp.current_user_saved_tracks(limit=50, offset=offset)
        if not results['items']:
            break
        for item in results['items']:
            track = item['track']
            tracks.append(f"{track['name']} {track['artists'][0]['name']}")
        offset += 50
        progress.update(task, extra=f"({len(tracks)})")
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


def migrate_tracks(yt: YTMusic, tracks: list, playlist_id: str, progress: Progress, task) -> tuple:
    success = 0
    failed = 0
    failed_tracks = []
    
    total = len(tracks)
    progress.reset(task, total=total, description="Migrating", extra="[green]✓0[/green] [red]✗0[/red]")
    
    for i, query in enumerate(tracks):
        results = yt.search(query, limit=5)
        video_id = next((r['videoId'] for r in results if r.get('videoId')), None)
        
        if video_id:
            yt.add_playlist_items(playlist_id, [video_id])
            success += 1
        else:
            failed += 1
            failed_tracks.append(query)
        
        progress.update(task, completed=i+1, extra=f"[green]✓{success}[/green] [red]✗{failed}[/red]")
        time.sleep(DELAY_SECONDS)
    
    return success, failed, failed_tracks


def main():
    console = Console()
    print_header(console)

    if not os.path.exists(YTMUSIC_AUTH_FILE):
        print_setup_instructions(console)
        exit(1)

    with create_progress_bar(console) as progress:
        task = progress.add_task("Initializing", total=100, extra="")
        
        sp = connect_spotify(progress, task)
        yt = connect_ytmusic(progress, task)
        tracks = fetch_spotify_tracks(sp, progress, task)
        playlist_id = create_playlist(yt, progress, task)
        success, failed, failed_tracks = migrate_tracks(yt, tracks, playlist_id, progress, task)

    print_summary(console, success, failed, failed_tracks)


if __name__ == "__main__":
    main()
