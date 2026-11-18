# Host environment

Machine constraints that are not product requirements (e.g. ports for `factory preview`,
CPU architecture, services that already run on this host).

## Default Non-Overlapping Preview Ports (`hermes-factory`)

To avoid colliding with sibling factories running concurrently on the same host (`CONTRACT.md §4`),
use Hermes Factory's default preview port block in `compose.preview.yaml`:

- `WEB_PORT=3400`
- `API_PORT=3401`
- `DB_PORT=54324`
- `NEO4J_HTTP_PORT=47474`
- `NEO4J_BOLT_PORT=47687`
