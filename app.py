"""TUI application for configuring and running the campsite scraper."""
import asyncio
import orjson
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button, Checkbox, DataTable, Footer, Header, Input, Label, 
    OptionList, Static, Switch
)
from textual.widgets.option_list import Option
from rich.text import Text

from models import ScrapeConfig, ScrapedCampground, AvailabilityStatus
from scraper import RecreationGovScraper


DATA_FILE = Path("campsite_data.json")


class ConfigScreen(Screen):
    """Configuration screen for scrape settings."""
    
    CSS = """
    ConfigScreen {
        align: center middle;
    }
    
    #config-container {
        width: 80;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    
    .config-row {
        height: 3;
        margin-bottom: 1;
    }
    
    .config-label {
        width: 30;
        height: 3;
        content-align: left middle;
    }
    
    .config-input {
        width: 1fr;
    }
    
    #button-row {
        height: 3;
        margin-top: 2;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Container(id="config-container"):
            yield Label("[b]Scrape Configuration[/b]", id="config-title")
            
            with Horizontal(classes="config-row"):
                yield Label("Months to scrape:", classes="config-label")
                yield Input("6", id="months-input", classes="config-input")
            
            with Horizontal(classes="config-row"):
                yield Label("Request delay (seconds):", classes="config-label")
                yield Input("10", id="delay-input", classes="config-input")
            
            with Horizontal(classes="config-row"):
                yield Label("Include FCFS sites:", classes="config-label")
                yield Switch(value=True, id="fcfs-switch")
            
            with Horizontal(classes="config-row"):
                yield Label("Max campgrounds:", classes="config-label")
                yield Input(
                    placeholder="Leave empty for all (use 3-5 for testing)",
                    id="max-campgrounds-input",
                    classes="config-input"
                )
            
            with Horizontal(classes="config-row"):
                yield Label("Target campground ID:", classes="config-label")
                yield Input(
                    placeholder="e.g. 232368 (leave empty for all CO)",
                    id="target-campground-input",
                    classes="config-input"
                )
            
            with Horizontal(id="button-row"):
                yield Button("Start Scrape", variant="primary", id="start-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")
    
    @on(Button.Pressed, "#start-btn")
    def on_start(self) -> None:
        months = int(self.query_one("#months-input", Input).value or "6")
        delay = float(self.query_one("#delay-input", Input).value or "10")
        fcfs = self.query_one("#fcfs-switch", Switch).value
        max_cg_str = self.query_one("#max-campgrounds-input", Input).value.strip()
        target_cg = self.query_one("#target-campground-input", Input).value.strip() or None
        
        max_campgrounds = None
        if max_cg_str:
            try:
                max_campgrounds = int(max_cg_str)
            except ValueError:
                pass
        
        config = ScrapeConfig(
            months_to_scrape=months,
            request_delay_seconds=delay,
            include_fcfs_sites=fcfs,
            max_campgrounds=max_campgrounds,
            target_campground_id=target_cg
        )
        
        self.dismiss(config)
    
    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        self.dismiss(None)


class CampsiteApp(App):
    """Main TUI application for campsite reservation finder."""
    
    CSS = """
    #main-container {
        height: 1fr;
    }
    
    #sidebar {
        width: 42;
        height: 100%;
        border-right: solid $primary;
        padding: 0 1;
    }
    
    #content {
        width: 1fr;
        height: 100%;
        padding: 0 1;
    }
    
    #filter-container {
        height: auto;
        border-bottom: solid $primary-darken-2;
        padding-bottom: 1;
        margin-bottom: 1;
    }
    
    .filter-row {
        height: 3;
        margin-bottom: 1;
    }
    
    .filter-label {
        width: 12;
        content-align: left middle;
    }
    
    .filter-input {
        width: 1fr;
    }
    
    #days-row-1, #days-row-2, #status-row {
        height: 3;
    }
    
    #days-row-1 Checkbox, #days-row-2 Checkbox, #status-row Checkbox {
        width: auto;
        margin-right: 1;
    }
    
    #filter-buttons {
        height: 3;
        margin-top: 1;
    }
    
    #filter-buttons Button {
        width: 1fr;
    }
    
    #scrape-btn {
        margin-top: 1;
    }
    
    #campground-list {
        height: 1fr;
    }
    
    #availability-table {
        height: 1fr;
    }
    
    #legend {
        height: auto;
        padding: 1;
        border: solid $primary-darken-2;
        margin-bottom: 1;
    }
    
    #status-bar {
        height: 3;
        background: $surface;
        border-top: solid $primary-darken-2;
        padding: 0 1;
        content-align: left middle;
    }
    
    #release-info {
        height: auto;
        max-height: 15;
        border: solid $accent;
        padding: 1;
        margin-top: 1;
    }
    """
    
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+n", "configure", "New Scrape"),
        Binding("escape", "unfocus", "Unfocus", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self.scraped_data: list[ScrapedCampground] = []
        self.filtered_data: list[ScrapedCampground] = []
        self.selected_campground: Optional[ScrapedCampground] = None
        self.filter_date: Optional[date] = None  # Release date filter
        self.filter_stay_date: Optional[date] = None  # Stay date filter
        self.filter_days: set[int] = set()  # Days of week (0=Mon, 4=Fri, etc.)
        self.filter_statuses: set[AvailabilityStatus] = set()  # Status filter
        self._last_file_mtime: float = 0.0
        
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Horizontal(id="main-container"):
            with Vertical(id="sidebar"):
                with Container(id="filter-container"):
                    yield Label("[b]Filters[/b]")
                    
                    with Horizontal(classes="filter-row"):
                        yield Label("Release:", classes="filter-label")
                        yield Input(
                            placeholder="YYYY-MM-DD",
                            id="filter-date",
                            classes="filter-input"
                        )
                    yield Button("Tomorrow", id="tonight-btn", variant="success")
                    
                    with Horizontal(classes="filter-row"):
                        yield Label("Name:", classes="filter-label")
                        yield Input(
                            placeholder="Campground",
                            id="filter-name",
                            classes="filter-input"
                        )
                    
                    with Horizontal(classes="filter-row"):
                        yield Label("Stay from:", classes="filter-label")
                        yield Input(
                            placeholder="YYYY-MM-DD",
                            id="filter-stay-date",
                            classes="filter-input"
                        )
                    
                    yield Label("Stay nights:")
                    with Horizontal(id="days-row-1"):
                        yield Checkbox("M", id="day-mon")
                        yield Checkbox("Tu", id="day-tue")
                        yield Checkbox("W", id="day-wed")
                        yield Checkbox("Th", id="day-thu")
                    with Horizontal(id="days-row-2"):
                        yield Checkbox("F", id="day-fri")
                        yield Checkbox("Sa", id="day-sat")
                        yield Checkbox("Su", id="day-sun")
                    
                    yield Label("Status:")
                    with Horizontal(id="status-row"):
                        yield Checkbox("A", id="status-available")
                        yield Checkbox("NR", id="status-nyr")
                        yield Checkbox("FF", id="status-fcfs")
                    
                    with Horizontal(id="filter-buttons"):
                        yield Button("Apply", id="apply-filter-btn", variant="primary")
                        yield Button("Clear", id="clear-filter-btn", variant="default")
                    
                    yield Button("New Scrape", id="configure-btn", variant="warning")
                
                yield Label("[b]Campgrounds[/b]")
                yield OptionList(id="campground-list")
            
            with Vertical(id="content"):
                yield Static(
                    "[b]Legend:[/b] [green]A[/]=Available [red]R[/]=Reserved "
                    "[yellow]NR[/]=Not Yet Released [blue]FF[/]=First-Come [dim]-[/]=Closed/N/A",
                    id="legend"
                )
                yield Label("[b]Availability[/b]", id="content-title")
                yield DataTable(id="availability-table")
                yield Static(id="release-info")
        
        yield Static("Ready. Press Ctrl+N to start a new scrape.", id="status-bar")
        yield Footer()
    
    async def on_mount(self) -> None:
        """Load existing data if available and start file watcher."""
        if DATA_FILE.exists():
            await self.load_data()
        # Check for file changes every 2 seconds
        self.set_interval(2.0, self._check_file_changes)
    
    def _check_file_changes(self) -> None:
        """Check if data file has been modified and reload if so."""
        if not DATA_FILE.exists():
            return
        try:
            mtime = DATA_FILE.stat().st_mtime
            if mtime > self._last_file_mtime:
                self._last_file_mtime = mtime
                self.run_worker(self.load_data())
        except OSError:
            pass
    
    async def load_data(self) -> None:
        """Load scraped data from file."""
        try:
            if not DATA_FILE.exists():
                return
            self._last_file_mtime = DATA_FILE.stat().st_mtime
            data = orjson.loads(DATA_FILE.read_bytes())
            self.scraped_data = [
                ScrapedCampground.model_validate(item) 
                for item in data
            ]
            self.filtered_data = self.scraped_data.copy()
            self.update_status(f"Loaded {len(self.scraped_data)} campgrounds")
            self.populate_campground_list()
        except Exception as e:
            self.update_status(f"Error loading data: {e}")
    
    def save_data(self) -> None:
        """Save scraped data to file."""
        data = [item.model_dump(mode="json") for item in self.scraped_data]
        DATA_FILE.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
    
    def merge_and_save(self, scraped: ScrapedCampground) -> None:
        """Merge a single scraped campground into existing data and save."""
        # Find existing entry by ID and replace, or append if new
        cg_id = scraped.campground.id
        found = False
        for i, existing in enumerate(self.scraped_data):
            if existing.campground.id == cg_id:
                self.scraped_data[i] = scraped
                found = True
                break
        
        if not found:
            self.scraped_data.append(scraped)
        
        self.save_data()
    
    def update_status(self, message: str) -> None:
        """Update the status bar."""
        self.query_one("#status-bar", Static).update(message)
    
    def populate_campground_list(self) -> None:
        """Populate the campground list from filtered data."""
        option_list = self.query_one("#campground-list", OptionList)
        option_list.clear_options()
        
        for cg_data in self.filtered_data:
            cg = cg_data.campground
            
            # Count sites opening on filter date (respecting day filter)
            opening_count = 0
            if self.filter_date:
                for site_avail in cg_data.availability.values():
                    for avail in site_avail.values():
                        if (avail.reservation_opens_at and 
                            avail.reservation_opens_at.date() == self.filter_date):
                            if self.filter_days and avail.date.weekday() not in self.filter_days:
                                continue
                            opening_count += 1
            
            label = f"{cg.name}"
            if opening_count > 0:
                label = f"★ {cg.name} ({opening_count} opening)"
            elif cg.rating > 0:
                label = f"{cg.name} ({cg.rating:.1f}★)"
            
            option_list.add_option(Option(label, id=cg.id))
    
    @on(OptionList.OptionSelected, "#campground-list")
    def on_campground_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle campground selection."""
        selected_id = event.option.id
        
        for cg_data in self.filtered_data:
            if cg_data.campground.id == selected_id:
                self.selected_campground = cg_data
                self.show_campground_details()
                break
    
    def clear_campground_details(self) -> None:
        """Clear the campground details panel."""
        self.selected_campground = None
        self.query_one("#content-title", Label).update("Select a campground")
        table = self.query_one("#availability-table", DataTable)
        table.clear(columns=True)
        self.query_one("#release-info", Static).update("")
    
    def show_campground_details(self) -> None:
        """Display details for selected campground."""
        if not self.selected_campground:
            return
        
        cg = self.selected_campground.campground
        
        # Update title
        title = self.query_one("#content-title", Label)
        title.update(f"[b]{cg.name}[/b] - {cg.parent_name}")
        
        # Populate availability table
        table = self.query_one("#availability-table", DataTable)
        table.clear(columns=True)
        
        # Add columns
        table.add_column("Site", key="site")
        table.add_column("Type", key="type")
        
        # Get date range from availability data
        all_dates = set()
        for site_avail in self.selected_campground.availability.values():
            for avail in site_avail.values():
                # Filter by day of week if set
                if self.filter_days and avail.date.weekday() not in self.filter_days:
                    continue
                all_dates.add(avail.date)
        
        sorted_dates = sorted(all_dates)
        
        # If stay date filter is set, start from that date
        if self.filter_stay_date:
            sorted_dates = [d for d in sorted_dates if d >= self.filter_stay_date]
        
        sorted_dates = sorted_dates[:14]  # Show up to 14 matching dates
        
        for d in sorted_dates:
            table.add_column(d.strftime("%m/%d"), key=d.isoformat())
        
        # Add rows for each campsite
        for site in cg.campsites:
            site_avail = self.selected_campground.availability.get(site.site_id, {})
            
            row: list[str | Text] = [site.site_name, site.site_type[:10]]
            
            for d in sorted_dates:
                date_key = f"{d.isoformat()}T00:00:00Z"
                avail_entry = site_avail.get(date_key)
                
                if avail_entry:
                    if avail_entry.status == AvailabilityStatus.AVAILABLE:
                        cell = Text("A", style="green bold")
                    elif avail_entry.status == AvailabilityStatus.RESERVED:
                        cell = Text("R", style="red")
                    elif avail_entry.status == AvailabilityStatus.NOT_YET_RELEASED:
                        # Highlight if opening on filter date
                        if (self.filter_date and avail_entry.reservation_opens_at and
                            avail_entry.reservation_opens_at.date() == self.filter_date):
                            cell = Text("NR★", style="yellow bold on green")
                        else:
                            cell = Text("NR", style="yellow")
                    elif avail_entry.status == AvailabilityStatus.FIRST_COME_FIRST_SERVED:
                        cell = Text("FF", style="blue")
                    else:
                        cell = Text("-", style="dim")
                else:
                    cell = Text("-", style="dim")
                
                row.append(cell)
            
            table.add_row(*row)
        
        # Show release info
        self.show_release_info()
    
    def show_release_info(self) -> None:
        """Show release schedule information."""
        if not self.selected_campground:
            return
        
        info_widget = self.query_one("#release-info", Static)
        cg = self.selected_campground.campground
        
        # Find sites opening on filter date (respecting day filter)
        opening_sites = []
        if self.filter_date:
            for site in cg.campsites:
                site_avail = self.selected_campground.availability.get(site.site_id, {})
                for avail in site_avail.values():
                    if (avail.reservation_opens_at and 
                        avail.reservation_opens_at.date() == self.filter_date):
                        # Skip if day filter is set and this day doesn't match
                        if self.filter_days and avail.date.weekday() not in self.filter_days:
                            continue
                        day_name = avail.date.strftime("%a")
                        opening_sites.append((site.site_name, avail.date, avail.reservation_opens_at, day_name))
        
        if opening_sites:
            day_filter_str = ""
            if self.filter_days:
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                day_filter_str = f" ({'+'.join(day_names[d] for d in sorted(self.filter_days))} only)"
            
            lines = [f"[b]Sites opening {self.filter_date}{day_filter_str}:[/b]"]
            for site_name, stay_date, release_dt, day_name in opening_sites[:10]:
                lines.append(
                    f"  • {site_name}: {day_name} {stay_date} "
                    f"(opens {release_dt.strftime('%I:%M %p')})"
                )
            if len(opening_sites) > 10:
                lines.append(f"  ... and {len(opening_sites) - 10} more")
            
            info_widget.update("\n".join(lines))
        else:
            info_widget.update(
                f"[b]Campground Info:[/b]\n"
                f"  Elevation: {cg.elevation_ft:,} ft\n"
                f"  Rating: {cg.rating:.1f} ({cg.review_count} reviews)\n"
                f"  Sites: {len(cg.campsites)}\n"
                f"  {cg.description[:200]}..."
            )
    
    def _get_day_filter(self) -> set[int]:
        """Get selected days of week (0=Mon through 6=Sun)."""
        days = set()
        day_checkboxes = [
            ("day-mon", 0), ("day-tue", 1), ("day-wed", 2), ("day-thu", 3),
            ("day-fri", 4), ("day-sat", 5), ("day-sun", 6)
        ]
        for checkbox_id, day_num in day_checkboxes:
            if self.query_one(f"#{checkbox_id}", Checkbox).value:
                days.add(day_num)
        return days
    
    def _get_status_filter(self) -> set[AvailabilityStatus]:
        """Get selected availability statuses."""
        statuses = set()
        status_checkboxes = [
            ("status-available", AvailabilityStatus.AVAILABLE),
            ("status-nyr", AvailabilityStatus.NOT_YET_RELEASED),
            ("status-fcfs", AvailabilityStatus.FIRST_COME_FIRST_SERVED),
        ]
        for checkbox_id, status in status_checkboxes:
            if self.query_one(f"#{checkbox_id}", Checkbox).value:
                statuses.add(status)
        return statuses
    
    @on(Button.Pressed, "#apply-filter-btn")
    def on_apply_filter(self) -> None:
        """Apply filters to the campground list."""
        date_input = self.query_one("#filter-date", Input).value.strip()
        stay_date_input = self.query_one("#filter-stay-date", Input).value.strip()
        name_input = self.query_one("#filter-name", Input).value.strip().lower()
        day_filter = self._get_day_filter()
        status_filter = self._get_status_filter()
        self.filter_days = day_filter  # Store for other methods
        self.filter_statuses = status_filter
        
        # Parse release date filter
        self.filter_date = None
        if date_input:
            try:
                self.filter_date = date.fromisoformat(date_input)
            except ValueError:
                self.update_status("Invalid release date format. Use YYYY-MM-DD")
                return
        
        # Parse stay date filter
        self.filter_stay_date = None
        if stay_date_input:
            try:
                self.filter_stay_date = date.fromisoformat(stay_date_input)
            except ValueError:
                self.update_status("Invalid stay date format. Use YYYY-MM-DD")
                return
        
        # Apply filters
        self.filtered_data = []
        
        for cg_data in self.scraped_data:
            cg = cg_data.campground
            
            # Name filter
            if name_input and name_input not in cg.name.lower():
                continue
            
            # Status filter - campground must have at least one site with matching status
            if status_filter:
                has_matching_status = False
                for site_avail in cg_data.availability.values():
                    for avail in site_avail.values():
                        if avail.status in status_filter:
                            # Also check day of week filter if set
                            if day_filter and avail.date.weekday() not in day_filter:
                                continue
                            has_matching_status = True
                            break
                    if has_matching_status:
                        break
                if not has_matching_status:
                    continue
            
            # Date filter - only include campgrounds with sites opening on that date
            if self.filter_date:
                has_opening = False
                for site_avail in cg_data.availability.values():
                    for avail in site_avail.values():
                        if (avail.reservation_opens_at and 
                            avail.reservation_opens_at.date() == self.filter_date):
                            # Also check day of week filter if set
                            if day_filter and avail.date.weekday() not in day_filter:
                                continue
                            has_opening = True
                            break
                    if has_opening:
                        break
                
                if not has_opening:
                    continue
            
            # Day of week filter (without release date or status filter)
            elif day_filter and not status_filter:
                has_matching_day = False
                for site_avail in cg_data.availability.values():
                    for avail in site_avail.values():
                        if avail.date.weekday() in day_filter:
                            has_matching_day = True
                            break
                    if has_matching_day:
                        break
                if not has_matching_day:
                    continue
            
            self.filtered_data.append(cg_data)
        
        # Sort by number of openings on filter date (respecting day filter)
        if self.filter_date:
            def count_openings(cg_data):
                count = 0
                for site_avail in cg_data.availability.values():
                    for avail in site_avail.values():
                        if (avail.reservation_opens_at and 
                            avail.reservation_opens_at.date() == self.filter_date):
                            if day_filter and avail.date.weekday() not in day_filter:
                                continue
                            count += 1
                return count
            
            self.filtered_data.sort(key=count_openings, reverse=True)
        
        self.populate_campground_list()
        
        # Build status message
        filters_active = []
        if self.filter_date:
            filters_active.append(f"release={self.filter_date}")
        if self.filter_stay_date:
            filters_active.append(f"stay≥{self.filter_stay_date}")
        if day_filter:
            day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            filters_active.append("+".join(day_names[d] for d in sorted(day_filter)))
        if name_input:
            filters_active.append(f"name='{name_input}'")
        if status_filter:
            status_names = {"Available": "A", "Not Yet Released": "NR", "First-Come, First-Served": "FF"}
            filters_active.append("+".join(status_names.get(s.value, s.value) for s in status_filter))
        
        filter_str = f" ({', '.join(filters_active)})" if filters_active else ""
        self.update_status(f"Showing {len(self.filtered_data)} of {len(self.scraped_data)} campgrounds{filter_str}")
        
        # Clear details if no results or selected campground is no longer in filtered list
        if self.selected_campground:
            selected_ids = {cg.campground.id for cg in self.filtered_data}
            if self.selected_campground.campground.id not in selected_ids:
                self.clear_campground_details()
            else:
                self.show_campground_details()
    
    @on(Button.Pressed, "#tonight-btn")
    def on_tonight_filter(self) -> None:
        """Set filter to tonight at midnight (tomorrow's date)."""
        tomorrow = date.today() + timedelta(days=1)
        self.query_one("#filter-date", Input).value = tomorrow.isoformat()
    
    @on(Button.Pressed, "#clear-filter-btn")
    def on_clear_filter(self) -> None:
        """Clear all filters."""
        self.query_one("#filter-date", Input).value = ""
        self.query_one("#filter-stay-date", Input).value = ""
        self.query_one("#filter-name", Input).value = ""
        for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            self.query_one(f"#day-{day}", Checkbox).value = False
        for status in ["available", "nyr", "fcfs"]:
            self.query_one(f"#status-{status}", Checkbox).value = False
        self.filter_date = None
        self.filter_stay_date = None
        self.filter_days = set()
        self.filter_statuses = set()
        self.filtered_data = self.scraped_data.copy()
        self.populate_campground_list()
        self.update_status(f"Showing all {len(self.scraped_data)} campgrounds")
        
        # Refresh details view if a campground is selected
        if self.selected_campground:
            self.show_campground_details()
    
    @on(Button.Pressed, "#configure-btn")
    def on_configure_btn(self) -> None:
        """Handle configure button press."""
        self.action_configure()
    
    def action_configure(self) -> None:
        """Show configuration screen."""
        self.push_screen(ConfigScreen(), self._on_config_dismiss)
    
    def _on_config_dismiss(self, config: ScrapeConfig | None) -> None:
        """Handle config screen dismissal."""
        if config:
            self.update_status("Starting scrape... (this will take a while)")
            self._run_scraper(config)
    
    @work(exclusive=True, thread=True)
    def _run_scraper(self, config: ScrapeConfig) -> None:
        """Run the scraper in a worker thread.
        
        Saves each campground incrementally as it's scraped.
        Merges with existing data so single-campground scrapes don't overwrite.
        """
        import asyncio
        
        # Load existing data first
        if DATA_FILE.exists():
            try:
                data = orjson.loads(DATA_FILE.read_bytes())
                self.scraped_data = [
                    ScrapedCampground.model_validate(item) for item in data
                ]
            except Exception:
                self.scraped_data = []
        
        def status_update(msg: str) -> None:
            self.call_from_thread(self.update_status, msg)
        
        def save_campground(scraped: ScrapedCampground) -> None:
            self.merge_and_save(scraped)
            self.call_from_thread(
                self.update_status,
                f"Saved {scraped.campground.name} ({len(self.scraped_data)} total)"
            )
        
        async def do_scrape():
            async with RecreationGovScraper(
                config, 
                status_callback=status_update,
                save_callback=save_campground
            ) as scraper:
                return await scraper.run()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(do_scrape())
            loop.close()
            
            self.filtered_data = self.scraped_data.copy()
            self.call_from_thread(self.populate_campground_list)
            self.call_from_thread(
                self.update_status, 
                f"Done! {len(self.scraped_data)} campgrounds in campsite_data.json"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.call_from_thread(self.update_status, f"Scrape error: {e}")
    
    def action_unfocus(self) -> None:
        """Remove focus from current widget."""
        self.set_focus(None)


# Module-level app instance for `textual run --dev app:app`
app = CampsiteApp()


def main():
    app.run()


if __name__ == "__main__":
    main()
