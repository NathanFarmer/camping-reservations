"""Data models for campsite reservation data."""
from datetime import datetime, date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AvailabilityStatus(str, Enum):
    AVAILABLE = "Available"
    RESERVED = "Reserved"
    NOT_YET_RELEASED = "Not Yet Released"
    FIRST_COME_FIRST_SERVED = "First-Come, First-Served"
    NOT_AVAILABLE = "Not Available"
    CLOSED = "Closed"
    UNKNOWN = "Unknown"


class Campsite(BaseModel):
    """Individual campsite within a campground."""
    site_id: str
    site_name: str
    loop: str
    site_type: str
    max_occupants: int = 0
    min_occupants: int = 0
    accessible: bool = False


class SiteAvailability(BaseModel):
    """Availability information for a specific site on a specific date."""
    site_id: str
    date: date
    status: AvailabilityStatus
    reservation_opens_at: Optional[datetime] = None


class Campground(BaseModel):
    """Campground metadata."""
    id: str
    name: str
    description: str = ""
    parent_name: str = ""
    location: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    elevation_ft: int = 0
    rating: float = 0.0
    review_count: int = 0
    price_min: float = 0.0
    price_max: float = 0.0
    reservable: bool = True
    url: str = ""
    campsites: list[Campsite] = Field(default_factory=list)


class ScrapedCampground(BaseModel):
    """Complete scraped data for a campground."""
    campground: Campground
    availability: dict[str, dict[str, SiteAvailability]] = Field(default_factory=dict)
    scraped_at: datetime = Field(default_factory=datetime.now)


class ScrapeConfig(BaseModel):
    """Configuration for the scrape operation."""
    months_to_scrape: int = 6
    request_delay_seconds: float = 10.0
    include_fcfs_sites: bool = True
    max_campgrounds: Optional[int] = None  # None = scrape all
    target_campground_id: Optional[str] = None  # Scrape only this campground
