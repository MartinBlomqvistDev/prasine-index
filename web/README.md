# Prasine Index: Web Frontend

Next.js 16 (App Router) frontend for Prasine Index, which checks the climate claims of large European companies against public records. Live at [prasineindex.com](https://prasineindex.com) since late June 2026.

## Routes

| Route | What it renders |
| ----- | --------------- |
| `/` | How an assessment works, an example assessment, the published assessments with a score comparison, and the form for requesting an assessment. |
| `/methodology` | Score bands, evidence weighting, and what each finding means. |
| `/corrections` | The corrections log: what changed between version 1 and version 2, the prototype scores of June 2026, and the notice of 5 November 2026. |
| `/about` | Who runs the index, how an assessment is made, corrections, how to cite, the licence, the privacy note and contact details. |
| `/reports/[slug]` | One page per published company: score, finding, claims table, company record and the evidence for the highest-scoring claim. |

## Where the data comes from

No database and no server-side data fetching; the browser loads Vercel Web Analytics, and the request form posts to Formspree. `lib/parse-report.ts` reads the canonical Markdown reports the Python pipeline writes to `../docs/reports/<slug>.md` and parses them at build time. Scores, findings and evidence on the site are read from the reports at build time, so the site cannot drift from them. The reports are the pipeline's output after review; see Published Assessments in the root README.

Index membership is `PUBLISHED_SLUGS` in `lib/site.ts`, which also holds `PUBLISHED_ON`, `WITHDRAWN_ON`, `AWAITING_REASSESSMENT` and `UNCOUNTED_CLAIMS` (claims assessed and left out of a company's score, each stated in a note under the report's claims table). The date of the assessments is read from the reports. To publish a new company: run the pipeline, review `docs/reports/<slug>.md`, add the slug to `PUBLISHED_SLUGS` in `lib/site.ts` and the company's sector to `SECTOR_MAP` in `lib/parse-report.ts`, then push. The finding is derived from the numeric score (`verdictFromScore`).

## Stack

| Layer | Choice |
| ----- | ------ |
| Framework | Next.js 16 App Router, React 19 |
| Styling | plain CSS in `app/globals.css` (no Tailwind) |
| Forms | Formspree (`app/apply-form.tsx`) |
| Analytics | Vercel Web Analytics |
| Hosting | Vercel, auto-deploy on push to `main` |

No authentication. The Clerk-gated dashboard and sign-in routes were removed in July 2026.

## Development

```bash
cd web
npm install
npm run dev     # http://localhost:3000
npm run build   # production build into .next/
```

The build reads `../docs/reports/`, so run it inside the repo, not from a copy of `web/` on its own.
