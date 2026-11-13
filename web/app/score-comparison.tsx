import {
  BAND_RANGES,
  type PublishedReport,
  bandIndex,
  findingFromString,
} from '../lib/parse-report'

const TEXT_COLOUR: Record<string, string> = {
  supported: 'var(--green-text)',
  unverified: 'var(--blue-text)',
  partial: 'var(--amber-text)',
  conflicts: 'var(--orange-text)',
  contradicted: 'var(--red-text)',
}

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

interface Row {
  slug: string
  company: string
  score: number
  cls: string
  label: string
  band: number
  claims: number
  // Claims assessed and left out of the company score.
  uncounted: number
  lowest: number
  highest: number
  floor: boolean
}

function claimsLine(row: Row): string {
  const scored =
    row.lowest === row.highest ? `scored ${row.lowest}` : `scored ${row.lowest} to ${row.highest}`
  const base = row.uncounted
    ? `${row.claims + row.uncounted} claims assessed; the ${row.claims} counted ${row.claims === 1 ? 'was' : 'were'} ${scored}`
    : row.claims === 1
      ? `1 claim, scored ${row.lowest}`
      : row.lowest === row.highest
        ? `${row.claims} claims, all scored ${row.lowest}`
        : `${row.claims} claims, scored ${row.lowest} to ${row.highest}`
  // A company score raised to its band's lower bound says so, because the raise is
  // what can put a company on one side or the other.
  return row.floor
    ? `${base}; company score raised to ${row.score}, the lower bound of the band of the highest-scoring claim`
    : base
}

function Side({ tag, rows }: { tag: string; rows: Row[] }) {
  const { cls, label, band } = rows[0]
  return (
    <div className="compare-side">
      <p className="compare-tag">{tag}</p>
      <p className="compare-band">
        <span className={`verdict-badge badge-${cls}`}>{label}</span>
        <span className="compare-range">{BAND_RANGES[band]}</span>
      </p>
      <ul className="compare-rows">
        {rows.map(row => (
          <li key={row.slug}>
            <div className="compare-row">
              <a href={`/reports/${row.slug}`}>{row.company}</a>
              <span className="compare-score" style={{ color: TEXT_COLOUR[row.cls] }}>
                {row.score}
              </span>
            </div>
            <span className="compare-bar" aria-hidden="true">
              <span
                className="compare-fill"
                style={{ width: `${row.score}%`, background: TEXT_COLOUR[row.cls] }}
              />
              {[20, 40, 60, 80].map(edge => (
                <span key={edge} className="compare-edge" style={{ left: `${edge}%` }} />
              ))}
            </span>
            <p className="compare-sub">{claimsLine(row)}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The lowest and the highest company scores, grouped by finding. A side holds every
 * company in its finding, in alphabetical order, so no company is named lowest or
 * highest on a margin of a point or two.
 */
export default function ScoreComparison({
  reports,
  assessedOn,
}: {
  reports: PublishedReport[]
  assessedOn: string
}) {
  if (reports.length < 2) return null

  const rows: Row[] = reports
    .map(({ slug, report: r }) => {
      const finding = findingFromString(r.verdict)
      const scores = r.claims.map(c => c.score)
      return {
        slug,
        company: r.company,
        score: r.overallScore,
        cls: finding.cls,
        label: finding.label,
        band: bandIndex(finding.label),
        claims: r.claims.length,
        uncounted: r.uncounted,
        lowest: Math.min(...scores),
        highest: Math.max(...scores),
        floor: r.floorApplied,
      }
    })
    .sort((a, b) => a.company.localeCompare(b.company, 'en'))

  const lowBand = Math.min(...rows.map(r => r.band))
  const highBand = Math.max(...rows.map(r => r.band))
  const lowest = Math.min(...rows.map(r => r.score))
  const highest = Math.max(...rows.map(r => r.score))
  const between = rows.filter(r => r.band > lowBand && r.band < highBand).length
  const single = lowBand === highBand
  const low = rows.filter(r => r.band === lowBand)
  const high = rows.filter(r => r.band === highBand)

  return (
    <div className="compare">
      <div className="compare-head">
        <h3 className="compare-heading">Lowest and highest company scores</h3>
        <span className="report-date">Prasine Index · {assessedOn}</span>
        <p className="compare-intro">
          {lowest === highest
            ? `Every company has a score of ${lowest} out of 100`
            : `Company scores run from ${lowest} to ${highest} out of 100`}
          , and a higher score means the records go further against the company&apos;s claims.
          The companies below are listed in alphabetical order under each finding, because small
          differences between scores should not be read as a ranking. Some of the claims that decide a
          company&apos;s band were scored more than once to test the judge&apos;s consistency;
          where the runs fall in two bands, the index publishes the lower band. The{' '}
          <a href="/methodology">methodology</a> gives the runs, names the companies whose claims
          were not tested and defines each finding.
        </p>
      </div>
      <div className={`compare-grid${single ? ' compare-grid-one' : ''}`}>
        {single ? (
          <Side tag="All companies, in alphabetical order" rows={rows} />
        ) : (
          <>
            <Side
              tag={low.length === 1 ? 'Lowest score' : 'Lowest scores, in alphabetical order'}
              rows={low}
            />
            <Side
              tag={high.length === 1 ? 'Highest score' : 'Highest scores, in alphabetical order'}
              rows={high}
            />
          </>
        )}
      </div>
      <div className="compare-foot">
        {between > 0 && (
          <p>
            The table above also lists {NUMBER_WORDS[between] ?? between}{' '}
            {between === 1 ? 'company whose finding lies' : 'companies whose findings lie'}{' '}
            between the lowest and the highest.
          </p>
        )}
        <p>No finding states that a company has broken any law.</p>
      </div>
    </div>
  )
}
