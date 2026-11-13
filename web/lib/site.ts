// The canonical origin. prasineindex.com redirects here.
export const SITE_URL = 'https://www.prasineindex.com'

// The Open Graph block of a page. A page that sets openGraph replaces the one in the
// root layout, so each page repeats the site name, type and image; the image is the card
// of app/opengraph-image.tsx, and the page's own path is its url.
export function openGraphFor(title: string, description: string, path: string) {
  return {
    title,
    description,
    url: path,
    siteName: 'Prasine Index',
    type: 'website' as const,
    images: [
      {
        url: '/opengraph-image',
        width: 1200,
        height: 630,
        alt: 'Prasine Index · Climate claims, checked against public records',
      },
    ],
  }
}

// Assessments currently published on the index.
export const PUBLISHED_SLUGS = [
  'bp-plc',
  'enel-spa',
  'glencore-plc',
  'h-m-group',
  'ikea-group',
  'orsted-a-s',
  'ryanair-holdings-plc',
  'ssab-ab',
]

// Version 1 assessments taken down when the index moved to version 2, until the
// company has been assessed again. Empty once every company is reassessed.
export const AWAITING_REASSESSMENT: Record<string, string> = {}

// The date version 2 went live on the site.
export const PUBLISHED_ON = '13 November 2026'

// Claims that were assessed and are left out of a company's score, by slug. Each must be
// stated in a note under the report's claims table; the build fails when the notes and
// this list disagree.
export const UNCOUNTED_CLAIMS: Record<string, number> = {
  'enel-spa': 1,
}

export const WITHDRAWN_ON = '5 November 2026'

// The version 1 assessments withdrawn on WITHDRAWN_ON, with the reasons given in
// the corrections log. All three companies were assessed again with version 2.
export const WITHDRAWN_REASONS: Record<string, { company: string; reason: string }> = {
  'ryanair-holdings-plc': {
    company: 'Ryanair Holdings plc',
    reason:
      "The report cited ASA ruling G20-1089921, which concerns a 2021 advertisement about Covid-19 vaccination. The ASA's ruling on Ryanair's emissions advertising is dated 5 February 2020. The report also called the EU consumer authorities' action on airline climate claims unresolved; Ryanair's part was resolved with commitments in November 2025.",
  },
  'glencore-plc': {
    company: 'Glencore plc',
    reason:
      'The report cited an open investigation by the UK Competition and Markets Authority. No such investigation could be found.',
  },
  'bp-plc': {
    company: 'BP plc',
    reason:
      "The report cited an ASA ruling from July 2019 as a prior finding against BP's advertising. No such ruling could be found.",
  },
}

// Assessments currently withdrawn. A withdrawn URL shows the withdrawal instead
// of a 404, so anyone holding an old link reads why.
export const WITHDRAWN: Record<string, { company: string; reason: string }> = Object.fromEntries(
  Object.entries(AWAITING_REASSESSMENT).map(([slug, company]) => [
    slug,
    {
      company,
      reason: `The version 1 assessment of ${company} was taken down on ${PUBLISHED_ON}, when the index moved to version 2 of the method. ${company} will be assessed again with version 2.`,
    },
  ]),
)

// Company scores of the version 1 assessments that stayed online until version 2, for
// the corrections log. The three withdrawn ones are shown as withdrawn, without a score.
export const VERSION_1_SCORES: Record<string, number> = {
  'enel-spa': 55,
  'ikea-group': 50,
  'ssab-ab': 45,
  'h-m-group': 41,
  'orsted-a-s': 18,
}
