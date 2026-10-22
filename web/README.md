# Prasine Index: Web Frontend

Next.js 16 (App Router) frontend for the Prasine Index greenwashing monitoring pipeline. Live at [prasineindex.com](https://prasineindex.com) since late June 2026.

## Routes

| Route | What it renders |
| ----- | --------------- |
| `/` | Public index of assessed companies (score, verdict, sector), the featured assessment with its full evidence chain, and the contact form. |
| `/methodology` | Score bands, evidence weighting, and what each verdict means. |
| `/reports/[slug]` | One page per published company: aggregate verdict, claim summary table, per-claim evidence and judge reasoning. |

## Where the data comes from

No database, no API call, no runtime dependency beyond Next.js. `lib/parse-report.ts` reads the canonical Markdown reports the Python pipeline writes to `../docs/reports/<slug>.md` and parses them at build time. Scores, verdicts, and evidence on the site are the pipeline's own output; they cannot drift from the reports.

Index membership is the `SLUGS` array in `app/page.tsx`. To publish a new company: run the pipeline, confirm `docs/reports/<slug>.md` exists, add the slug, push. Verdict labels are derived from the numeric score (`verdictFromScore`), never taken from prose.

## Stack

| Layer | Choice |
| ----- | ------ |
| Framework | Next.js 16 App Router, React 19 |
| Styling | plain CSS in `app/globals.css` (no Tailwind) |
| Forms | Formspree (`app/apply-form.tsx`) |
| Hosting | Vercel, auto-deploy on push to `main` |

No authentication. The earlier Clerk-gated dashboard and sign-in routes were removed in July 2026 along with the rest of the commercial framing; the site is public and free.

## Development

```bash
cd web
npm install
npm run dev     # http://localhost:3000
npm run build   # production build into .next/
```

The build reads `../docs/reports/`, so run it inside the repo, not from a copy of `web/` on its own.
