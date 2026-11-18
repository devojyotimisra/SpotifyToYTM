# 🎵 Spotify to YouTube Music Migration Tool

> *Because life's too short to manually search 628 songs one by one.*

[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![uv](https://img.shields.io/badge/uv-Package%20Manager-blueviolet?style=flat-square)](https://github.com/astral-sh/uv)
[![Rich](https://img.shields.io/badge/Rich-Terminal%20UI-green?style=flat-square)](https://github.com/Textualize/rich)

---

## 🤔 What is this?

So you finally decided to break up with Spotify? Maybe YouTube Music gave you that irresistible family plan deal, or you just want to consolidate your subscriptions. Whatever your reason, **congratulations on making a life choice that involves migrating 500+ songs manually!**

Just kidding. That's what this tool is for.

This script takes all your **Liked Songs from Spotify** and migrates them to a shiny new **YouTube Music playlist**. With a beautiful Rich terminal UI, progress bars, and zero manual labor required.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎯 **100% Audio Accuracy** | Enforces studio `songs` catalog only, ISRC matching, strict duration check (±2–3s), and negative keyword filtering (no music videos, live bootlegs, or covers) |
| 🔄 **Full Migration** | Transfers all your Spotify Liked Songs to YouTube Music |
| 🛡️ **Zero-Drop Verification** | Interactive queue for borderline tracks so no song is silently lost or incorrectly matched |
| 📋 **Audit Report** | Exports `migration_audit.json` with every track's match confidence, audio type, and duration delta |
| 📊 **Beautiful UI** | Rich terminal progress bars and detailed summary tables |
| ⚡ **Rate Limiting** | Built-in delays to avoid getting rate-limited |

---

## 📋 Prerequisites

Before you start, make sure you have:

- 🐍 **Python 3.8+** installed
- 📦 **uv** package manager ([install guide](https://github.com/astral-sh/uv))
- 🎵 A **Spotify account** with songs you actually like
- 🎬 A **YouTube Music account** (and a YouTube channel)

---

## 🚀 Installation

### Step 1: Clone this bad boy

```bash
git clone https://github.com/YOUR_USERNAME/spotify-to-ytmusic.git
cd spotify-to-ytmusic
```

### Step 2: Install dependencies

```bash
uv sync
```

That's it. uv is fast. Like, *really* fast.

---

## ⚙️ Configuration

### Step 1: Create your `.env` file

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

Your `.env` should look like this:

```env
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
YTMUSIC_AUTH_FILE=browser.json
DELAY_SECONDS=1
PLAYLIST_NAME=Spotify Liked Songs
PLAYLIST_DESCRIPTION=Migrated from Spotify
PLAYLIST_PRIVACY=PRIVATE
```

### Step 2: Get Spotify Credentials 🎵

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Click **Create App**
3. Fill in:
   - **App Name**: `Spotify to YTMusic` (or whatever makes you happy)
   - **Redirect URI**: `http://127.0.0.1:8888/callback`
4. Click **Save**
5. Copy your **Client ID** and **Client Secret** to `.env`

> 💡 **Pro tip**: Don't share your Client Secret. It's called a *secret* for a reason.

### Step 3: Set up YouTube Music Authentication 🎬

This is where things get ✨ *spicy* ✨

YouTube Music doesn't have a nice OAuth flow for us mortals, so we're going to steal... I mean, *borrow* your browser session.

1. Open **YouTube Music** in your browser: https://music.youtube.com
2. Make sure you're **logged in** (check that your profile picture is in the top right)
3. Open **Developer Tools**:
   - Windows/Linux: `F12` or `Ctrl + Shift + I`
   - Mac: `Cmd + Option + I`
4. Go to the **Network** tab
5. In the filter box, type: `browse`
6. Click around in YouTube Music (go to Library, click a playlist, anything)
7. You should see requests appearing that say `browse?...`
8. **Right-click** on one of them → **Copy** → **Copy request headers**

Now run this command and paste those headers:

```bash
uv run ytmusicapi browser
```

It'll ask you to paste the headers. Do it, then press:
- `Enter`
- `Ctrl + Z`
- `Enter`

Boom! You now have a `browser.json` file. Guard it with your life. (Just kidding, but don't commit it to git.)

---

## 🏃 Running the Migration

The moment of truth:

```bash
uv run app.py
```

You'll see a beautiful Rich progress bar that looks like this:

```
╭──────────────────────────────────────────────────────────────────────────────╮
│                          🎵 Spotify → YouTube Music                          │
╰──────────────────────────────────────────────────────────────────────────────╯

⠋ Migrating ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  42% ✓267 ✗3 0:04:32
```

And when it's done:

```
╭────── Done ──────╮
│ ✓ Migrated  624  │
│ ✗ Failed    4    │
╰──────────────────╯

Failed:
  • Some Obscure Song by Unknown Artist
  • That One Track You Downloaded from SoundCloud in 2015
```

---

## 🔧 Troubleshooting

### "browser.json not found!"

You skipped the YouTube Music authentication step. Go back and read it. I'll wait.

### "HTTP 400: Bad Request"

Your `browser.json` has expired. YouTube sessions last about 2 years, but if you logged out of YouTube, you'll need to redo the auth step.

### "Some songs aren't being found"

YouTube Music's search isn't perfect. If a song has a weird title or is super obscure, it might not find a match. The script shows you which ones failed at the end.

### "I got rate limited"

Increase `DELAY_SECONDS` in your `.env` file. Try `2` or `3` seconds. Yes, it'll take longer. Good things come to those who wait.

---

## 📁 Project Structure

```
spotify-to-ytmusic/
├── app.py              # The main script (the magic happens here)
├── .env                # Your secrets (don't commit this!)
├── .env.example        # Template for .env
├── browser.json        # YouTube Music auth (don't commit this either!)
├── pyproject.toml      # Project dependencies
├── uv.lock             # Lock file
└── README.md           # You are here 📍
```

---

## 🤝 Contributing

Found a bug? Want to add a feature? Open a PR! Just make sure to:

1. Not commit your `.env` or `browser.json` files (seriously)
2. Test your changes before submitting
3. Be nice in your commit messages

---

## 📜 License

MIT License - Do whatever you want with this code. Just don't blame me if something breaks.

---

## 🙏 Acknowledgments

- **[ytmusicapi](https://github.com/sigma67/ytmusicapi)** - For making YouTube Music API accessible
- **[spotipy](https://github.com/plamere/spotipy)** - For the Spotify API wrapper
- **[Rich](https://github.com/Textualize/rich)** - For making terminals beautiful
- **Coffee** - For fueling this entire project

---

<div align="center">

**Made with ❤️ and too much caffeine**

*If this saved you hours of manual work, consider starring the repo!* ⭐

</div>
