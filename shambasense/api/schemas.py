"""Request bodies for the REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Outlook(BaseModel):
    p_below: float = Field(ge=0, le=1)
    p_normal: float = Field(ge=0, le=1)
    p_above: float = Field(ge=0, le=1)
    source: str = "user-supplied outlook"

    @model_validator(mode="after")
    def _sums_to_one(self):
        total = self.p_below + self.p_normal + self.p_above
        if abs(total - 1) > 0.02:
            raise ValueError(f"probabilities must sum to 1 (got {total:.2f})")
        return self


class RecommendRequest(BaseModel):
    lat: float | None = Field(default=None, ge=-5, le=5.5, description="Latitude (Kenya)")
    lon: float | None = Field(default=None, ge=33.5, le=42.5, description="Longitude (Kenya)")
    county: str | None = Field(default=None, description="County id, e.g. machakos; used when no point is given")
    season: Literal["long_rains", "short_rains"] | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    lang: Literal["en", "sw"] = "en"
    outlook: Outlook | None = Field(default=None, description="Override the seasonal outlook for what-if analysis")

    @model_validator(mode="after")
    def _point_or_county(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if self.lat is None and not self.county:
            raise ValueError("give lat and lon, or a county")
        return self


class OutlookUpload(BaseModel):
    county: str
    year: int
    season: Literal["long_rains", "short_rains"]
    p_below: float = Field(ge=0, le=1)
    p_normal: float = Field(ge=0, le=1)
    p_above: float = Field(ge=0, le=1)
    source: str = "KMD seasonal outlook"


class RegisterIn(BaseModel):
    phone: str = Field(min_length=9, max_length=20)
    pin: str = Field(min_length=4, max_length=4)
    name: str | None = Field(default=None, max_length=80)
    county: str | None = None
    lang: Literal["en", "sw"] = "en"


class LoginIn(BaseModel):
    phone: str = Field(min_length=9, max_length=20)
    pin: str = Field(min_length=4, max_length=4)


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    county: str | None = None
    lang: Literal["en", "sw"] | None = None
    sms_opt_in: bool | None = None


class PinChangeIn(BaseModel):
    old_pin: str = Field(min_length=4, max_length=4)
    new_pin: str = Field(min_length=4, max_length=4)


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float | None = Field(default=None, ge=-5, le=5.5)
    lon: float | None = Field(default=None, ge=33.5, le=42.5)
    county: str | None = None
    area_acres: float | None = Field(default=None, gt=0, le=100000)

    @model_validator(mode="after")
    def _place(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if self.lat is None and not self.county:
            raise ValueError("pick the farm on the map or choose a county")
        return self


class FarmPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    area_acres: float | None = Field(default=None, gt=0, le=100000)


class ReminderIn(BaseModel):
    season: Literal["long_rains", "short_rains"]
    year: int | None = Field(default=None, ge=2024, le=2100)


class TestSmsIn(BaseModel):
    phone: str
    message: str = Field(default="ShambaSense test message.", max_length=300)


class FeedbackIn(BaseModel):
    county: str
    season: Literal["long_rains", "short_rains"]
    year: int
    crop: str
    followed_advice: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    yield_bags_acre: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)
    farm_id: int | None = None
