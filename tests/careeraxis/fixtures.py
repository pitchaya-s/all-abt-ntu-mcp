"""Synthetic rendered CareerAxis records; no credentials or network."""

from datetime import datetime, timezone

from careeraxis.models import AuthStatus


BASE = "https://careeraxis.ntu.edu.sg"
SNAPSHOT = {"retrieved_at": datetime(2030, 1, 1, tzinfo=timezone.utc), "source_url": BASE + "/students/jobs/search", "cached": False}
PATHS = {"events": "/students/events/detail/", "resources": "/students/docs/detail/",
         "organisations": "/students/organisations/detail/", "appointment_topics": "/students/appointments/topics/",
         "internship_jobs": "/workgroups/internship/Jobs/detail/"}


def records(section=None):
    return [{"title": "Synthetic role " + str(i), "url": BASE + (PATHS[section] if section else "/students/jobs/") + str(i) + ("/example" if section == "organisations" else ""),
             "summary" if section else "details": "Fictional posting description"} for i in range(1, 5)]


class FixtureSession:
    def status(self):
        return AuthStatus(credentials_configured=False, credential_storage="os_keyring", credential_error=None,
                          session_verified=False, last_verified_at=None)

    def search(self, query, page, limit, refresh):
        return {"data": {"opportunities": records(), "no_results": False, "has_next_page": False}, "snapshot": SNAPSHOT}

    def search_section(self, section, query, page, limit, refresh, **kwargs):
        return {"data": {"items": records(section), "no_results": False, "has_next_page": False}, "snapshot": SNAPSHOT}

    def get_opportunity(self, url, refresh):
        return {"data": {"title": "Fictional engineer role", "text": "A synthetic opportunity description.",
                         "application_links": ["https://employer.example/apply", "javascript:alert(1)"]}, "snapshot": SNAPSHOT}

    def get_portal_record(self, url, refresh):
        return {"data": {"title": "Fictional career workshop", "text": "A synthetic event description.",
                         "links": ["https://employer.example/event", "http://insecure.invalid"]}, "snapshot": SNAPSHOT}
