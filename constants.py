"""Fixed JSearch request values and client-side filtering rules."""

from datetime import timedelta


JSEARCH_URL = "https://jsearch.p.rapidapi.com/search-v2"
JSEARCH_HOST = "jsearch.p.rapidapi.com"

SEARCH_PARAMS = {
    "query": "Full Stack Backend Software Engineer in Bangalore",
    "country": "in",
    "language": "en",
    "date_posted": "month",
}

ALLOWED_CITIES = frozenset({"bangalore", "bengaluru"})
ALLOWED_ROLE_PHRASES = (
    "full stack engineer",
    "software engineer",
    "software developer",
    "backend engineer",
    "backend developer",
    "software",
)
MAX_JOB_AGE = timedelta(days=30)
JSEARCH_RESULTS_PER_PAGE = 5
MAX_RESULTS_PER_FETCH = 100
MAX_PAGES_PER_FETCH = MAX_RESULTS_PER_FETCH // JSEARCH_RESULTS_PER_PAGE
