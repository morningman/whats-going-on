"""Email fetcher modules - plugin architecture for different mailing list systems."""

from abc import ABC, abstractmethod


class BaseFetcher(ABC):
    """Base class for all email fetchers."""

    fetcher_type: str = ""

    @abstractmethod
    def fetch_emails(self, config: dict, date: str, cookie: str = "") -> list[dict]:
        """Fetch emails for a given date. Returns unified format."""
        raise NotImplementedError

    @abstractmethod
    def test_connection(self, config: dict, cookie: str = "") -> dict:
        """Test if the connection works. Returns {"ok": bool, "message": str}."""
        raise NotImplementedError


def get_fetcher(fetcher_type: str) -> BaseFetcher:
    """Factory function to get a fetcher by type."""
    from .ponymail import PonyMailFetcher
    from .pipermail import PipermailFetcher

    fetchers = {
        "ponymail": PonyMailFetcher,
        "pipermail": PipermailFetcher,
    }
    cls = fetchers.get(fetcher_type)
    if cls is None:
        raise ValueError(f"Unknown fetcher type: {fetcher_type}")
    return cls()
