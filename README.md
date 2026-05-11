# Recreation.gov Campsite Reservation Finder

A TUI application for scraping and filtering Colorado campsite availability from Recreation.gov, with a focus on finding sites that open for reservation at specific times (like midnight tonight).

## Features

- **Scrapes Colorado campgrounds** from Recreation.gov using their API
- **Follows robots.txt** with 10-second delays between requests
- **TUI interface** for configuration and browsing results
- **Filter by release date** to find sites opening for reservation
- **Filter by day of week** to find Friday/Saturday night availability
- **Target specific campgrounds** by ID for quick updates
- **Auto-refresh** when data file changes during scraping
- **Incremental saves** - each campground saved immediately after scraping
- **Caches data locally** for fast re-filtering without re-scraping

## Installation

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Development

### Run with Hot Reloading

For development, use Textual's dev mode which hot-reloads CSS and Python changes:

```bash
textual run --dev app:app
```

To prevent Mac sleep during long scrapes while developing:

```bash
caffeinate -i textual run --dev app:app
```

### Dev Console (Optional)

For advanced debugging, you can use Textual's dev console. This requires two terminals:

**Terminal 1** - Start the console (leave it running):
```bash
textual console
```

**Terminal 2** - Run your app with `--dev`:
```bash
textual run --dev app:app
```

Logs, events, and CSS info from your app will appear in Terminal 1.

> **Note:** The `textual` command comes from the `textual-dev` package (included in requirements.txt).

## Usage

### Run the TUI (Production)

```bash
python app.py
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | Start a new scrape |
| `Ctrl+Q` | Quit |
| `Escape` | Unfocus input fields |

### Workflow

1. Click "New Scrape" or press `Ctrl+N` to configure:
   - **Months to scrape**: How far ahead to look (default 6)
   - **Request delay**: Seconds between API requests (default 10, per robots.txt)
   - **Include FCFS sites**: Whether to include first-come-first-served sites
   - **Max campgrounds**: Limit for testing (leave empty for all)
   - **Target campground ID**: Scrape only one campground (e.g., `232368`)

2. Wait for scraping to complete (this takes a while due to rate limiting)

3. Use filters in the sidebar:
   - **Release date**: Show only campgrounds with sites opening on this date
   - **Tomorrow**: Quick-fill tomorrow's date (next 8am MT release)
   - **Name**: Filter by campground name
   - **Stay from**: Jump to a specific stay date in the availability table
   - **Day checkboxes**: Filter by day of week (M/Tu/W/Th/F/Sa/Su)
   - **Apply**: Apply all filters
   - **Clear**: Reset all filters

4. Click a campground to see availability:
   - **A** = Available now
   - **R** = Reserved
   - **NR** = Not Yet Released (opens in future)
   - **NR★** = Opens on your filter date
   - **FF** = First-come, first-served

### Availability Status Legend

| Code | Meaning |
|------|---------|
| A | Available to book now |
| R | Already reserved |
| NR | Not yet released - opens 6 months before stay date at 10am ET |
| NR★ | Not yet released, but opens on your filtered release date |
| FF | First-come, first-served (no reservation needed) |
| - | Not available or closed |

## Data Storage

Scraped data is saved to `campsite_data.json` in the current directory. This allows you to:
- Re-filter without re-scraping
- Run quick queries on cached data
- Re-scrape fresh data when needed

## Rate Limiting

This tool respects Recreation.gov's robots.txt:
- Minimum 10-second delay between requests
- Does not access /account/* or /cart/* endpoints
- Uses only public API endpoints

## Architecture

- `models.py` - Pydantic data models
- `scraper.py` - Recreation.gov API scraper
- `app.py` - Textual TUI application

## Long-Running Scrapes

A full scrape of all Colorado campgrounds can take several hours due to the 10-second rate limit. To prevent your Mac from sleeping during a scrape, use the `caffeinate` command:

```bash
# Production
caffeinate -i python app.py

# Development (with hot reloading)
caffeinate -i textual run --dev app:app
```

The `-i` flag prevents idle sleep while the process is running. Other useful flags:
- `-d` - Prevent display sleep
- `-s` - Prevent system sleep (even on AC power)
- `-u` - Simulate user activity

Alternatively, use System Settings → Energy to temporarily disable sleep.

## Tips for Booking

Recreation.gov releases reservations on a **6-month rolling window** at **10:00 AM Eastern Time** daily. For example, to book a site for August 1st, reservations open on February 1st at 10am ET.

1. Scrape data to find campgrounds with sites opening soon
2. Use the release date filter to find sites opening on a specific date
3. Use day-of-week checkboxes (F/Sa) to find weekend availability
4. Use "Stay from" to jump to your target dates in the availability table
5. Note the campgrounds and sites you want
6. Be ready on Recreation.gov at 10:00 AM ET on the release date
7. Re-scrape a specific campground by ID for last-minute updates
