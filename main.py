"""Expose the combined cybersecurity and ML assessment to the extension."""

from fastapi import FastAPI
from pydantic import BaseModel, Field, model_validator

from analysis_service import analyze_job_with_ml, get_analysis_status
from risk_engine import validate_listing_url


app = FastAPI(title="JobProof API")


class JobListing(BaseModel):
    """The job fields extracted by the extension's content script."""

    url: str | None = Field(default=None, min_length=1, max_length=8192)
    listing_url: str | None = Field(default=None, min_length=1, max_length=8192)
    title: str = Field(default="", max_length=500)
    company: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=100000)
    company_profile: str = Field(default="", max_length=100000)
    requirements: str = Field(default="", max_length=100000)
    benefits: str = Field(default="", max_length=100000)
    recruiter_email: str | None = Field(default=None, max_length=320)
    description_complete: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def validate_urls(self):
        if not (self.url and self.url.strip()) and self.listing_url is None:
            raise ValueError("Provide an application URL or a supported platform listing URL.")
        if self.listing_url is not None:
            validate_listing_url(self.listing_url)
        return self


@app.get("/health")
def health() -> dict:
    return get_analysis_status()


@app.post("/analyze")
def analyze(job: JobListing) -> dict:
    # A regular def lets FastAPI run potentially blocking catalog refreshes in
    # its worker threadpool while the event loop continues serving requests.
    return analyze_job_with_ml(job.model_dump())
