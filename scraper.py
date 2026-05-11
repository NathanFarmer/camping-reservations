"""Recreation.gov campsite scraper using their API."""
import asyncio
import re
from datetime import datetime, date, timedelta
from typing import Optional, Callable
import httpx
from rich.console import Console

from models import (
    AvailabilityStatus, Campground, Campsite, SiteAvailability,
    ScrapedCampground, ScrapeConfig
)

console = Console()

BASE_URL = "https://www.recreation.gov"
API_URL = f"{BASE_URL}/api"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def parse_availability_status(status: str) -> AvailabilityStatus:
    """Parse API status string to enum."""
    status_map = {
        "Available": AvailabilityStatus.AVAILABLE,
        "Open": AvailabilityStatus.AVAILABLE,  # "Open" = available to book
        "Reserved": AvailabilityStatus.RESERVED,
        "NYR": AvailabilityStatus.NOT_YET_RELEASED,  # API abbreviation
        "Not Yet Released": AvailabilityStatus.NOT_YET_RELEASED,
        "Not Reservable": AvailabilityStatus.FIRST_COME_FIRST_SERVED,  # Can't reserve online = FCFS
        "Not Available": AvailabilityStatus.NOT_AVAILABLE,
        "Closed": AvailabilityStatus.CLOSED,
    }
    if "First-come" in status:
        return AvailabilityStatus.FIRST_COME_FIRST_SERVED
    return status_map.get(status, AvailabilityStatus.UNKNOWN)


class RecreationGovScraper:
    """Scraper for recreation.gov campsite data."""
    
    def __init__(self, config: ScrapeConfig, status_callback=None, save_callback=None):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
        self.status_callback = status_callback
        self.save_callback = save_callback  # Called after each campground is scraped
    
    def _update_status(self, message: str) -> None:
        """Update status via callback if provided."""
        if self.status_callback:
            self.status_callback(message)
        console.print(f"[cyan]{message}")
        
    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True
        )
        return self
        
    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()
            
    async def _request(self, url: str) -> dict:
        """Make a rate-limited request."""
        await asyncio.sleep(self.config.request_delay_seconds)
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()
    
    async def search_colorado_campgrounds(self) -> list[dict]:
        """Search for all camping facilities in Colorado."""
        from urllib.parse import urlencode
        
        campgrounds = []
        start = 0
        size = 100
        
        # Colorado center coordinates
        CO_LAT = "39.5501"
        CO_LNG = "-105.7821"
        
        while True:
            params = {
                "fq": "entity_type:campground",
                "lat": CO_LAT,
                "lng": CO_LNG,
                "radius": "500",  # miles - covers all of Colorado
                "start": str(start),
                "size": str(size),
            }
            url = f"{API_URL}/search?{urlencode(params)}"
            
            try:
                data = await self._request(url)
                results = data.get("results", [])
                
                # Filter to only Colorado results (API returns by distance, not state)
                co_results = [
                    r for r in results 
                    if self._is_colorado_campground(r)
                ]
                
                if not results:
                    break
                    
                campgrounds.extend(co_results)
                total = data.get("total", "?")
                self._update_status(
                    f"Found {len(campgrounds)} CO campgrounds (page {start//size + 1}, {total} total in region)..."
                )
                
                if len(results) < size:
                    break
                start += size
                
                # Safety limit - don't fetch more than 2000 results
                if start >= 2000:
                    break
                    
            except Exception as e:
                console.print(f"[red]Error searching campgrounds: {e}")
                break
                
        return campgrounds
    
    def _is_colorado_campground(self, result: dict) -> bool:
        """Check if a search result is in Colorado."""
        # Check addresses
        addresses = result.get("addresses", [])
        for addr in addresses:
            if addr.get("state_code") == "CO":
                return True
        
        # Check city field
        city = result.get("city", "")
        if ", CO" in city or ", Colorado" in city:
            return True
        
        # Check parent_name for Colorado references
        parent = result.get("parent_name", "")
        if "Colorado" in parent:
            return True
            
        # Check coordinates - rough Colorado bounding box
        lat = result.get("lat", 0)
        lng = result.get("lng", 0)
        if lat and lng:
            # Colorado bounds: lat 37-41, lng -109 to -102
            if 37 <= lat <= 41 and -109 <= lng <= -102:
                return True
        
        return False
    
    async def get_campground_details(self, campground_id: str) -> Optional[dict]:
        """Get detailed info for a campground."""
        try:
            url = f"{API_URL}/camps/campgrounds/{campground_id}"
            return await self._request(url)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not get details for {campground_id}: {e}")
            return None
    
    async def get_release_schedule(self, campground_id: str) -> dict:
        """Get reservation release schedule for a campground."""
        try:
            url = f"{API_URL}/camps/campgrounds/{campground_id}/releases"
            data = await self._request(url)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            console.print(f"[yellow]Warning: Could not get release schedule for {campground_id}: {e}")
            return {}
    
    async def get_monthly_availability(
        self, campground_id: str, start_date: date
    ) -> dict:
        """Get availability for a campground for a month."""
        from urllib.parse import quote
        try:
            date_str = start_date.strftime("%Y-%m-01T00:00:00.000Z")
            encoded_date = quote(date_str, safe='')
            url = f"{API_URL}/camps/availability/campground/{campground_id}/month?start_date={encoded_date}"
            return await self._request(url)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not get availability for {campground_id}: {e}")
            return {}
    
    def _parse_campground(self, search_result: dict, details: Optional[dict]) -> Campground:
        """Parse campground from search result and optional details."""
        entity = search_result.get("entity_id", search_result.get("id", ""))
        
        # Extract from search result
        name = search_result.get("name", search_result.get("entity_name", "Unknown"))
        
        # Try to get coordinates from search result
        lat = 0.0
        lon = 0.0
        if "location" in search_result:
            coords = search_result["location"]
            if isinstance(coords, dict):
                lat = coords.get("lat", coords.get("latitude", 0.0))
                lon = coords.get("lon", coords.get("longitude", 0.0))
        
        # Get parent/agency info
        parent = search_result.get("parent_name", "")
        
        # Get rating info
        rating = search_result.get("average_rating", 0.0)
        review_count = search_result.get("number_of_ratings", 0)
        
        # Fill in from details if available
        description = ""
        elevation = 0
        if details:
            cg = details.get("campground", {})
            
            # Get name from details if search_result had a placeholder
            if name.startswith("Campground ") and cg.get("facility_name"):
                name = cg.get("facility_name", name)
            
            # Get description from facility_description_map
            desc_map = cg.get("facility_description_map", {})
            description = desc_map.get("Overview", "")
            
            # Try to extract elevation from description
            elev_match = re.search(r"(\d{1,2},?\d{3})\s*(?:feet|ft)", description, re.I)
            if elev_match:
                elevation = int(elev_match.group(1).replace(",", ""))
            
            # Get coordinates from details if not in search
            if lat == 0.0:
                lat = float(cg.get("facility_latitude", 0) or 0)
                lon = float(cg.get("facility_longitude", 0) or 0)
            
            # Update parent name if available
            if not parent:
                parent = cg.get("facility_name", "")
        
        return Campground(
            id=str(entity),
            name=name,
            description=description[:500] if description else "",
            parent_name=parent,
            location="Colorado",
            latitude=lat,
            longitude=lon,
            elevation_ft=elevation,
            rating=rating,
            review_count=review_count,
            price_min=0.0,
            price_max=0.0,
            url=f"{BASE_URL}/camping/campgrounds/{entity}"
        )
    
    def _parse_availability(
        self, 
        availability_data: dict,
        existing_campsites: list[Campsite],
        release_map: dict[date, datetime] = None
    ) -> tuple[dict[str, dict[str, SiteAvailability]], list[Campsite]]:
        """Parse monthly availability data into structured format.
        
        Args:
            availability_data: Raw API response
            existing_campsites: Already-parsed campsites
            release_map: Map of stay_date -> release_datetime from release schedule API
        
        Returns (availability_dict, updated_campsites).
        """
        result = {}
        campsites_dict = availability_data.get("campsites", {})
        release_map = release_map or {}
        
        # Track seen site IDs to avoid duplicates
        seen_site_ids = {s.site_id for s in existing_campsites}
        new_campsites = list(existing_campsites)
        
        for site_id, site_data in campsites_dict.items():
            # Create campsite entry if not seen
            if site_id not in seen_site_ids:
                seen_site_ids.add(site_id)
                new_campsites.append(Campsite(
                    site_id=site_id,
                    site_name=str(site_data.get("site", site_id)),
                    loop=site_data.get("loop", ""),
                    site_type=site_data.get("campsite_type", "Standard"),
                    max_occupants=site_data.get("max_num_people", 0),
                    min_occupants=site_data.get("min_num_people", 0),
                    accessible=False
                ))
            
            availabilities = site_data.get("availabilities", {})
            site_avail = {}
            
            # Check if site is reservable (Site-Specific) vs FCFS
            reserve_type = site_data.get("campsite_reserve_type", "")
            is_reservable_site = reserve_type == "Site-Specific"
            
            for date_str, status in availabilities.items():
                try:
                    avail_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                    parsed_status = parse_availability_status(status)
                    
                    # If a reservable site shows "Not Reservable", it's actually NYR
                    if is_reservable_site and parsed_status == AvailabilityStatus.FIRST_COME_FIRST_SERVED:
                        parsed_status = AvailabilityStatus.NOT_YET_RELEASED
                    
                    # Get release date from schedule, fall back to 6-month calculation
                    release_dt = release_map.get(avail_date) or self._calculate_release_time(avail_date)
                    
                    site_avail[date_str] = SiteAvailability(
                        site_id=site_id,
                        date=avail_date,
                        status=parsed_status,
                        reservation_opens_at=release_dt
                    )
                except (ValueError, KeyError):
                    continue
                    
            if site_avail:
                result[site_id] = site_avail
                
        return result, new_campsites
    
    def _calculate_release_time(self, stay_date: date) -> datetime:
        """Calculate when a stay date will be released for booking.
        
        Recreation.gov uses a 6-month rolling window, releasing dates daily at 10am ET.
        """
        from dateutil.relativedelta import relativedelta
        
        # Release date is approximately 6 months before stay date
        release_date = stay_date - relativedelta(months=6)
        
        # Releases happen at 10:00 AM Eastern Time
        # Using -05:00 for EST (could be -04:00 for EDT)
        release_dt = datetime(
            release_date.year, 
            release_date.month, 
            release_date.day,
            10, 0, 0
        )
        # Add timezone info (EST = UTC-5)
        from datetime import timezone
        est = timezone(timedelta(hours=-5))
        return release_dt.replace(tzinfo=est)
    
    def _parse_release_schedule(self, releases_data: dict) -> dict[date, datetime]:
        """Parse release schedule to map stay dates to release times.
        
        Returns dict mapping stay_date -> release_datetime.
        """
        release_map = {}
        
        try:
            next_release = releases_data.get("next_release", {})
            if next_release:
                release_time_str = next_release.get("release_time", "")
                sliding_end_str = next_release.get("sliding_end", "")
                
                if release_time_str and sliding_end_str:
                    release_time = datetime.fromisoformat(release_time_str.replace("Z", "+00:00"))
                    sliding_end = datetime.fromisoformat(sliding_end_str.replace("Z", "+00:00")).date()
                    
                    # Get current release end to know where next release starts
                    current_release = releases_data.get("current_release", {})
                    current_end_str = current_release.get("end", "")
                    
                    if current_end_str:
                        current_end = datetime.fromisoformat(current_end_str.replace("Z", "+00:00")).date()
                        
                        # All dates from current_end+1 through sliding_end release at release_time
                        current_date = current_end + timedelta(days=1)
                        while current_date <= sliding_end:
                            release_map[current_date] = release_time
                            current_date += timedelta(days=1)
        except (ValueError, KeyError, TypeError) as e:
            console.print(f"[yellow]Warning parsing release schedule: {e}")
        
        return release_map
    
    async def scrape_campground(
        self,
        search_result: dict,
        index: int = 0,
        total: int = 0
    ) -> Optional[ScrapedCampground]:
        """Scrape full data for a single campground."""
        campground_id = str(search_result.get("entity_id", search_result.get("id", "")))
        name = search_result.get("name", "Unknown")
        
        self._update_status(f"[{index}/{total}] Scraping {name}...")
        
        # Get campground details and release schedule
        details = await self.get_campground_details(campground_id)
        releases_data = await self.get_release_schedule(campground_id)
        
        campground = self._parse_campground(search_result, details)
        release_map = self._parse_release_schedule(releases_data)
        
        # Get availability for configured months
        all_availability = {}
        all_campsites: list[Campsite] = []
        today = date.today()
        
        for month_offset in range(self.config.months_to_scrape):
            month_start = date(today.year, today.month, 1) + timedelta(days=32 * month_offset)
            month_start = date(month_start.year, month_start.month, 1)
            
            monthly_data = await self.get_monthly_availability(campground_id, month_start)
            parsed, all_campsites = self._parse_availability(monthly_data, all_campsites, release_map)
            
            # Merge into all_availability
            for site_id, dates in parsed.items():
                if site_id not in all_availability:
                    all_availability[site_id] = {}
                all_availability[site_id].update(dates)
        
        campground.campsites = all_campsites
        
        return ScrapedCampground(
            campground=campground,
            availability=all_availability
        )
    
    def _save_result(self, scraped: ScrapedCampground) -> None:
        """Save a scraped campground via callback if provided."""
        if self.save_callback:
            self.save_callback(scraped)
    
    async def run(self) -> list[ScrapedCampground]:
        """Run the full scrape operation.
        
        Saves each campground incrementally via save_callback.
        On error, raises exception without saving (already-saved data is preserved).
        """
        results = []
        
        # If targeting a specific campground, skip search
        if self.config.target_campground_id:
            cg_id = self.config.target_campground_id
            self._update_status(f"Scraping single campground: {cg_id}")
            
            search_result = {"entity_id": cg_id, "name": f"Campground {cg_id}"}
            scraped = await self.scrape_campground(search_result, index=1, total=1)
            if scraped:
                results.append(scraped)
                self._save_result(scraped)
            return results
        
        # Otherwise, search for all Colorado campgrounds
        self._update_status("Searching for Colorado campgrounds...")
        campgrounds = await self.search_colorado_campgrounds()
        
        # Apply max_campgrounds limit if set
        if self.config.max_campgrounds and self.config.max_campgrounds < len(campgrounds):
            self._update_status(
                f"Found {len(campgrounds)} campgrounds, limiting to {self.config.max_campgrounds}"
            )
            campgrounds = campgrounds[:self.config.max_campgrounds]
        else:
            self._update_status(f"Found {len(campgrounds)} campgrounds to scrape")
        
        # Scrape each campground
        total = len(campgrounds)
        for i, cg in enumerate(campgrounds):
            try:
                scraped = await self.scrape_campground(cg, index=i+1, total=total)
                if scraped:
                    results.append(scraped)
                    self._save_result(scraped)
            except Exception as e:
                name = cg.get("name", "Unknown")
                console.print(f"[red]Error scraping {name}: {e}")
                # Continue to next campground, already-saved data is preserved
        
        return results


async def main():
    """Test the scraper."""
    config = ScrapeConfig(
        months_to_scrape=3,
        request_delay_seconds=10.0
    )
    
    async with RecreationGovScraper(config) as scraper:
        results = await scraper.run()
        
    console.print(f"\n[green]Scraped {len(results)} campgrounds successfully!")
    
    for r in results[:5]:
        console.print(f"  - {r.campground.name}: {len(r.campground.campsites)} sites")


if __name__ == "__main__":
    asyncio.run(main())
