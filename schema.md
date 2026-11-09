# burnctl — canonical DB schema

**Moved.** The canonical schema reference is [`docs/schema.md`](docs/schema.md),
which is where `burnctl-schema-guard` and `burnctl-auditor` both look for it.

This file was the schema reference from 2026-04-20 to 2026-11-09. It is kept only
as a redirect: having two schema documents at two paths is what let the
table-scoped `token_cost` / `fix_id` correction sit unread for seven months while
`burnctl-auditor` Check 4 kept reporting those real columns as drift.

Do not add schema facts here. Regenerate `docs/schema.md` instead.
