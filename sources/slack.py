"""Slack data source — stub for future implementation."""


class SlackSource:
    """Slack workspace message fetcher (Coming Soon)."""

    def get_channels(self, token: str) -> list[dict]:
        """Get list of channels in the workspace."""
        raise NotImplementedError("Slack integration coming soon")

    def fetch_messages(self, token: str, channel_id: str, days: int = 3) -> list[dict]:
        """Fetch messages from a channel."""
        raise NotImplementedError("Slack integration coming soon")

    def oauth_authorize(self, client_id: str, redirect_uri: str) -> str:
        """Generate OAuth authorization URL."""
        raise NotImplementedError("Slack integration coming soon")

    def oauth_callback(self, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
        """Handle OAuth callback and return token."""
        raise NotImplementedError("Slack integration coming soon")
