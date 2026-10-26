# Security

This repository is public, and the demo will be a public URL that anyone can call. Everything
below follows from those two facts.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/KLKH7/the-ninety-labs/security/advisories/new).

## Rules for contributors

### Secrets
- **No secret ever enters the repo**: no keys, connection strings, tokens or `.env` files. `.env*`
  is gitignored, and GitHub secret scanning with push protection is on, so a push containing a
  known key format is blocked.
- **Azure uses managed identity**, not keys. Container Apps call Foundry, Speech, Cosmos DB and
  Event Hubs as a managed identity with least-privilege role assignments. Anything that truly
  needs a secret lives in Azure Key Vault.
- **If a secret is committed, rotate it first**, then remove it. Deleting the commit does not
  un-publish it; forks and caches keep it.

### The public demo
- **Spend is capped.** Every model call goes through one client with a per-session and per-day
  budget; when the budget is spent the demo serves cached results. An Azure budget alert fires at
  $20.
- **Expensive routes are gated.** Live generation (agent runs, speech) needs a demo passcode;
  replaying a cached match does not. On the big screen the passcode is typed in the ••• menu (or
  given once as `?pass=`, taken off the address at once) and kept on that device only, in
  localStorage `ninety.passcode`; it is never logged or written into the page, and is posted only
  to the embedded companion, with this origin as the target (`web/viewer/src/dock.ts`).
- **Rate limits** on every API route, by IP and by session.
- **Strict CORS and input validation.** Every request body is validated against a schema; unknown
  fields are rejected.
- **Same-origin pages.** Every page is served with `default-src 'self'` (no inline or third-party
  script anywhere, no framing). The phone's pages alone add `style-src 'self' 'unsafe-inline'`,
  because its Ionic components write their own `<style>` elements; it never writes viewer text as
  markup (`ninety/api/app.py`, tested in `tests/test_api_site.py`).

### The agents (prompt injection)
- **Agents read typed facts, not free text.** Events, stats and viewer preferences reach a model
  as structured data inside a clearly delimited block, never concatenated into instructions.
- **Viewer input is data.** Free text a viewer types (a favourite player, a question) is
  length-capped, validated against the roster or an allow-list where possible, and never treated
  as an instruction.
- **Tools are read-only and scoped.** The MCP server exposes match-query tools only, over a fixed list of precomputed matches, and its public endpoint answers only with the key held in Key Vault and the Foundry connection: no file
  system, shell, network fetch or write access.
- **The fact-checking agent gates output.** Any sentence whose numbers or entities are not in the
  evidence is rejected before it reaches the screen.

### Data and privacy
- **Synthetic data only.** No real players, clubs, matches or footage. No personal data is
  collected beyond optional viewer preferences, which stay in the browser.

### Supply chain
- **Dependencies are pinned** (`uv.lock`) and limited to permissive licences, with three narrow
  exceptions for runtimes bundled in a dependency's wheel; never GPL or AGPL otherwise. The full rule
  is in [AGENTS.md](AGENTS.md) (Hard rules); every locked package and its licence is listed in
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), checked by `tests/test_third_party_notices.py`.
- **Dependabot alerts and security updates** are on.
- **CI** runs tests and a secret scan on every push.
