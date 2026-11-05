// The canonical origin. prasineindex.com redirects here.
export const SITE_URL = 'https://www.prasineindex.com'

// Assessments currently published on the index.
export const PUBLISHED_SLUGS = [
  'enel-spa',
  'ikea-group',
  'h-m-group',
  'orsted-a-s',
  'ssab-ab',
]

export const WITHDRAWN_ON = '5 November 2026'

// Assessments withdrawn on WITHDRAWN_ON. Their URLs stay live so that anyone
// holding an old link reads the withdrawal instead of a 404.
export const WITHDRAWN: Record<string, { company: string; reason: string }> = {
  'ryanair-holdings-plc': {
    company: 'Ryanair Holdings plc',
    reason:
      "The report cited ASA ruling G20-1089921, which concerns a 2021 advertisement about Covid-19 vaccination. The ASA's ruling on Ryanair's emissions advertising is dated 5 February 2020. The report also called the EU consumer authorities' action on airline climate claims unresolved; Ryanair's part was resolved with commitments in November 2025.",
  },
  'bp-plc': {
    company: 'BP plc',
    reason:
      "The report cited an ASA ruling from July 2019 as a prior finding against BP's advertising. No such ruling could be found.",
  },
  'glencore-plc': {
    company: 'Glencore plc',
    reason:
      'The report cited an open investigation by the UK Competition and Markets Authority. No such investigation could be found.',
  },
}
