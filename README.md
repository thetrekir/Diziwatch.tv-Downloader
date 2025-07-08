# Diziwatch.tv Downloader

This isn't Dizibox. Diziwatch tries way too hard to block automation with a pile of overly-engineered protections: headless detection, dynamic URL chains, debugger traps. It's a mess.

This script is designed to cut through all that noise and just get you the video file.

### The Obstacles

This script exists because Diziwatch uses these annoying defensive layers. Here's what we get around:

*   **GHOST MODE (Headless Detection):** The most son-of-a-bitch layer. The moment it thinks you're a common bot, it plays dead and never sends the critical `source2.php` request. **The fix:** `get_url.js` runs a full-fledged, stealthy browser (Puppeteer) that mimics a real user, bypassing the detection.
*   **MATRYOSHKA DOLLS (Dynamic URL Chain):** `source2.php -> m.php -> l.php`... Each step needs a key from the last one. **The fix:** The script follows the entire chain to get the final playlist.
*   **FAKE `.jpg` SEGMENTS:** It tries to fool standard tools by serving video as fake image files with a `.jpg` extension. **The fix:** We don't fall for it. The script knows these are video segments and downloads them correctly.
*   **PASSPORT CONTROL (Referer & Cloudflare):** It wants to see the right "passport" (Referer) at every step. **The fix:** `cloudscraper` and custom headers get us through without issue.
*   **OTHER NUISANCES:** All other distractions like `debugger;` traps and JavaScript obfuscation are disabled or bypassed from the start.

### How It Works

This isn't a simple, single-file script. It needs two components working together:

1.  **Python (`diziwatch.py`):** The main script. It orchestrates the process, gets episode lists, manages downloads, organizes files, and uses **FFmpeg** to assemble the final video.

2.  **Node.js (`get_url.js`) - The Radar:** This is the specialized tool for Diziwatch's anti-bot measures. It launches the stealth browser to get past **GHOST MODE**, finds the real video and subtitle URLs, and passes them to the Python script. **This is why Node.js is a requirement, not an option.**

### Installation

You need a few things set up first:

1.  **Python 3:**
    Install the required libraries:
    ```bash
    pip install requests beautifulsoup4 tqdm cloudscraper
    ```

2.  **Node.js and Puppeteer:**
    Install Node.js. Then, in the script's directory, install Puppeteer:
    ```bash
    npm install puppeteer
    ```

3.  **FFmpeg:**
    This is **mandatory**, not a suggestion. It's the tool that merges the video, audio, and subtitle streams into a single file. Get it from the [official website](https://ffmpeg.org/download.html) and add it to your system's `PATH`. Otherwise, you'll end up with a bunch of useless, separate files.

### Usage

*   **To Download a Single Episode:**
    ```bash
    python diziwatch.py "https://diziwatch.tv/series/a-series/season-1/episode-1"
    ```

*   **To Download a Full Season:**
    ```bash
    python diziwatch.py "https://diziwatch.tv/series/a-series/season-1/episode-5" --sezon
    ```

When it's done, you'll get a simple report of what downloaded and what failed. Clean and precise.
