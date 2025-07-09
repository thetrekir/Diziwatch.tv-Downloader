# Diziwatch.tv Downloader

This isn't Dizibox. Diziwatch tries way too hard to block automation with a pile of overly-engineered protections: headless detection, dynamic URL chains, debugger traps. It's a mess.

This script is designed to cut through all that noise and just get you the video file.

### What's New

*   **Automated Filler-Skipping:** Use the `--only-canon` flag when downloading an anime season. The script will check `animefillerlist.com` and automatically skip any episode explicitly marked as **"filler."**
*   **Smarter Anti-Detection:** The script now simulates a mouse click on the page. This tricks players that hide the video source until you interact with them.
*   **Rate-Limit Control:** The download process includes pauses to avoid IP blocks. If you want to go full speed and don't care about the risk, you can disable this with the `--ignore-rate-limit` flag.

### The Obstacles It Overcomes

This script exists because Diziwatch uses these annoying defensive layers. Here's what we get around:

*   **GHOST MODE (Headless Detection):** The most son-of-a-bitch layer. The moment it thinks you're a bot, it plays dead. **The Fix:** `get_url.js` uses `puppeteer-extra` with a stealth plugin and simulates a mouse click, making it indistinguishable from a real user.
*   **SERVER-SIDE RATE LIMITING:** Making too many requests too quickly gets your IP temporarily blocked. **The Fix:** The script downloads in controlled bursts with randomized pauses. Slower, but safer. This can be disabled with a flag.
*   **MATRYOSHKA DOLLS (Dynamic URL Chain):** `source2.php -> m.php -> l.php...` The path to the video is a chain. **The Fix:** The script follows the entire chain to the end.
*   **FAKE `.jpg` SEGMENTS:** Serves video as fake image files. **The Fix:** We don't fall for it. The script knows it's video.
*   **PASSPORT CONTROL (Referer & Cloudflare):** Requires the correct "passport" at every step. **The Fix:** `cloudscraper` and custom headers get us through.

### How It Works

This is a two-part system, and both are required:

1.  **Python (`diziwatch.py`) - The Orchestrator:** Manages the overall process: gets episode lists, handles the downloads, organizes files, and uses **FFmpeg** to assemble the final video.
2.  **Node.js (`get_url.js`) - The Radar:** The specialist for Diziwatch's anti-bot systems. It launches the stealth browser to get past **GHOST MODE**, finds the real video/subtitle URLs, and scrapes the filler list. **This is why Node.js is a requirement.**

### Installation

You need a few things set up first:

1.  **Python 3:** Install all the required Python libraries using the requirements.txt file:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Node.js:** After installing Node.js, run this command in the script's directory. It will automatically install all the necessary packages listed in package.json.
    ```bash
    npm install
    ```

3.  **FFmpeg:** This is **mandatory**, not a suggestion. It merges the video, audio, and subtitle files. Get it from the [official website](https://ffmpeg.org/download.html) and add it to your system's `PATH`.

### Usage

*   **To Download a Single Episode:**
    ```bash
    python diziwatch.py "https://diziwatch.tv/series/a-series/season-1/episode-1"
    ```

*   **To Download a Full Season:**
    ```bash
    python diziwatch.py "https://diziwatch.tv/series/a-series/season-1/episode-5" --sezon
    ```

*   **To Download a Season, Skipping Fillers:**
    ```bash
    python diziwatch.py "https://diziwatch.tv/dizi/one-piece/1-sezon/bolum-1" --sezon --only-canon
    ```

*   **To Disable Download Pauses:**
    Add `--ignore-rate-limit` to any of the commands above.
