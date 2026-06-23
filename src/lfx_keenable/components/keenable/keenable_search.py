"""Keenable web-search component for Langflow."""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, FloatInput, MessageTextInput, Output, SecretStrInput
from lfx.log.logger import logger
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame

from lfx_keenable.components.keenable._client import (
    KeenableError,
    _redact,
    keenable_post,
    resolve_api_key,
)


class KeenableSearchComponent(Component):
    """Query the Keenable web-search API built for AI agents.

    Keyless by default: with no API key the keyless public endpoint
    (``/v1/search/public``) is used. Provide an API key (or set
    ``KEENABLE_API_KEY``) to use the authenticated endpoint (for higher rate limits).
    """

    display_name = "Keenable Search"
    description = "Web search built for AI agents, powered by Keenable. Keyless by default."
    documentation = "https://github.com/keenableai/lfx-keenable"
    icon = "Keenable"

    inputs = [
        SecretStrInput(
            name="api_key",
            display_name="Keenable API Key",
            required=False,
            info=(
                "Optional. With no key the keyless public search endpoint is used. "
                "Falls back to the KEENABLE_API_KEY environment variable. A key lifts rate limits."
            ),
        ),
        MessageTextInput(
            name="query",
            display_name="Search Query",
            info="The search query to run.",
            tool_mode=True,
        ),
        MessageTextInput(
            name="site",
            display_name="Site",
            info="Restrict results to a single domain, e.g. 'github.com'.",
            advanced=True,
            tool_mode=True,
        ),
        DropdownInput(
            name="mode",
            display_name="Search Mode",
            info="'pro' (default).",
            options=["pro"],
            value="pro",
            advanced=True,
        ),
        MessageTextInput(
            name="published_after",
            display_name="Published After",
            info="Only pages published on or after this date (YYYY-MM-DD).",
            advanced=True,
            tool_mode=True,
        ),
        MessageTextInput(
            name="published_before",
            display_name="Published Before",
            info="Only pages published on or before this date (YYYY-MM-DD).",
            advanced=True,
            tool_mode=True,
        ),
        MessageTextInput(
            name="acquired_after",
            display_name="Indexed After",
            info="Only pages indexed by Keenable on or after this date (YYYY-MM-DD).",
            advanced=True,
            tool_mode=True,
        ),
        MessageTextInput(
            name="acquired_before",
            display_name="Indexed Before",
            info="Only pages indexed by Keenable on or before this date (YYYY-MM-DD).",
            advanced=True,
            tool_mode=True,
        ),
        FloatInput(
            name="timeout",
            display_name="Timeout (s)",
            info="Request timeout in seconds.",
            value=30.0,
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Results", name="dataframe", method="search"),
    ]

    def fetch_results(self) -> list[Data]:
        """Call the Keenable search API and return one Data per result."""
        try:
            api_key = resolve_api_key(self.api_key)
            payload: dict = {"query": self.query, "mode": self.mode or "pro"}
            for field in (
                "site",
                "published_after",
                "published_before",
                "acquired_after",
                "acquired_before",
            ):
                value = getattr(self, field, None)
                if value:
                    payload[field] = value

            data = keenable_post(
                "/v1/search/public",
                "/v1/search",
                payload,
                api_key,
                float(self.timeout or 30.0),
            )
            results = data.get("results")
            if not isinstance(results, list):
                msg = f"Unexpected response from the Keenable search API: {_redact(repr(data)[:200], api_key)}"
                raise KeenableError(msg)
            # The API returns a fixed-size result set as-is (no max_results param).
            out = [Data(text=(item.get("title") or item.get("url") or ""), data=item) for item in results]
            self.status = out
        except KeenableError as e:
            logger.error(str(e))
            error = Data(data={"error": str(e)})
            self.status = error
            return [error]
        else:
            return out

    def search(self) -> DataFrame:
        """Search results as a DataFrame (the component's table output)."""
        return DataFrame(self.fetch_results())

    def run_model(self) -> DataFrame:
        return self.search()
