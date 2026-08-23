"""Google Drive / Gmail / Calendar source adapters.

All three speak the same :class:`SourceAdapter` protocol as the Git adapter.
They are network-agnostic: an ``http_fetch`` callable performs GETs against a
base URL (the real Google API or a local stub in tests), and a
``token_provider`` supplies the bearer token (real OAuth issuance is a
human-gated deployment step, never done here).
"""

from akc_source_adapters.google.drive import DriveAdapter
from akc_source_adapters.google.gmail import GmailAdapter
from akc_source_adapters.google.calendar import CalendarAdapter

__all__ = ["DriveAdapter", "GmailAdapter", "CalendarAdapter"]
