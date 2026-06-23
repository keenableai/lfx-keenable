# lfx-keenable

[Keenable](https://keenable.ai) web-search and page-fetch components for
[Langflow](https://langflow.org), packaged as a standalone **Langflow Extension
Bundle**. Two components ship in the `keenable` bundle group:

- **Keenable Search** — web search built for AI agents.
- **Keenable Fetch** — fetch a page and return its main content as markdown.

Both are **keyless by default**: with no API key they call Keenable's public
endpoints; provide a key to use the authenticated endpoints (for higher rate limits).

## Install

```bash
pip install lfx-keenable
```

The bundle registers automatically via the `langflow.extensions` entry-point.
Restart your Langflow server; the components appear in the palette under the
**keenable** group, and work as agent tools (the query / URL inputs are
tool-enabled).

## Configuration

- **API key (optional).** Set it on the component, or via the `KEENABLE_API_KEY`
  environment variable. Blank → the keyless public endpoint is used.
- **Endpoint (optional).** `KEENABLE_API_URL` overrides the base URL (HTTPS
  enforced; plain `http` only for loopback). The base URL is never a
  component/LLM-settable input — that would be an SSRF foothold.

## Components

### Keenable Search

`query` plus optional per-query filters — `site`, `mode` (`pro`),
and publication / index date bounds (`published_after`/`before`,
`acquired_after`/`before`). Returns a table of results
(`title`, `url`, `description`, `published_at`, `acquired_at`). There is no
`max_results` input — the API returns a fixed-size result set as-is.

### Keenable Fetch

`url` → the page's main content as markdown plus metadata (`title`,
`description`, `author`, `published_at` when available). Rejects non-`http(s)`
schemes and private/internal hosts client-side before sending.

## Develop

```bash
cd lfx-keenable
pip install -e .
lfx extension validate .
pytest                       # unit tests (offline; transport mocked)
```

## License

MIT © Keenable
