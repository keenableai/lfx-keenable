"""Keenable page-fetch component for Langflow."""

from lfx.custom.custom_component.component import Component
from lfx.io import FloatInput, MessageTextInput, Output, SecretStrInput
from lfx.log.logger import logger
from lfx.schema.data import Data
from lfx.schema.dataframe import DataFrame

from lfx_keenable.components.keenable._client import (
    KeenableError,
    keenable_get,
    reject_private_fetch_target,
    resolve_api_key,
)


class KeenableFetchComponent(Component):
    """Fetch a web page via Keenable and return its main content as markdown.

    The companion to :class:`KeenableSearchComponent`: give it a URL (e.g. one
    found via search) and it returns ``{url, title, content, ...}``. Keyless by
    default; rejects non-http(s) and private/internal URLs before sending.
    """

    display_name = "Keenable Fetch"
    description = "Fetch a web page via Keenable and return its content as markdown. Keyless by default."
    documentation = "https://github.com/keenableai/lfx-keenable"
    icon = "Keenable"

    inputs = [
        SecretStrInput(
            name="api_key",
            display_name="Keenable API Key",
            required=False,
            info=(
                "Optional. With no key the keyless public fetch endpoint is used. "
                "Falls back to the KEENABLE_API_KEY environment variable."
            ),
        ),
        MessageTextInput(
            name="url",
            display_name="URL",
            info="The URL of the page to fetch and extract as markdown.",
            required=True,
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
        Output(display_name="Page", name="dataframe", method="fetch"),
    ]

    def fetch_page(self) -> list[Data]:
        """Fetch one page and return its extracted content as a single Data."""
        try:
            url = (self.url or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                msg = f"Refusing to fetch a non-http(s) URL: {url!r}"
                raise KeenableError(msg)
            reject_private_fetch_target(url)

            api_key = resolve_api_key(self.api_key)
            data = keenable_get(
                "/v1/fetch/public",
                "/v1/fetch",
                {"url": url},
                api_key,
                float(self.timeout or 30.0),
            )
            result = Data(text=data.get("content") or "", data=data)
            self.status = result
        except KeenableError as e:
            logger.error(str(e))
            error = Data(data={"error": str(e)})
            self.status = error
            return [error]
        else:
            return [result]

    def fetch(self) -> DataFrame:
        """Fetched page as a single-row DataFrame (the component's output)."""
        return DataFrame(self.fetch_page())

    def run_model(self) -> DataFrame:
        return self.fetch()
