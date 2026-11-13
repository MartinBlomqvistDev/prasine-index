import {
  type EvidenceItem,
  type PublishedReport,
  detailClaimIndex,
  findingFromString,
  formatLongDate,
  rangeNumbers,
  verdictFromScore,
} from '../lib/parse-report'
import { aggregateNote, claimCountText, count, renderInline, renderLinked } from '../lib/render'

function records(n: number): string {
  return `${count(n)} ${n === 1 ? 'record' : 'records'}`
}

// "A, B (2) and C": each source once, in order of first appearance, linked to its first record.
function sourceList(items: EvidenceItem[]): React.ReactNode {
  if (items.length === 0) return 'none'
  const groups: { source: string; url?: string; n: number }[] = []
  for (const item of items) {
    const group = groups.find(g => g.source === item.source)
    if (group) group.n += 1
    else groups.push({ source: item.source, url: item.url, n: 1 })
  }
  return groups.map((g, i) => (
    <span key={g.source}>
      {i > 0 && ', '}
      {g.url ? <a href={g.url} target="_blank" rel="noopener">{g.source}</a> : g.source}
      {g.n > 1 && ` (${g.n})`}
    </span>
  ))
}

function joinParts(parts: string[]): string {
  if (parts.length <= 1) return parts.join('')
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/** One real assessment, shown on the home page: the first company in alphabetical order. */
export default function ExampleAssessment({ reports }: { reports: PublishedReport[] }) {
  if (reports.length === 0) return null
  const { slug, report: r } = [...reports].sort((a, b) =>
    a.report.company.localeCompare(b.report.company, 'en'),
  )[0]

  const detailIndex = detailClaimIndex(r)
  if (!r.claim || !r.keyFinding || r.evidence.length === 0 || detailIndex === -1) {
    // The example never falls through to another company: that would be an unstated choice.
    throw new Error(`Example assessment ${slug}: the report lacks a claim, key finding, evidence or detailed row`)
  }

  const agg = findingFromString(r.verdict)
  const detail = findingFromString(r.detailVerdict)
  const range = rangeNumbers(r.scoreRange)
  const contradicts = r.evidence.filter(e => e.supports === 'No')
  const supports = r.evidence.filter(e => e.supports === 'Yes')
  const context = r.evidence.length - contradicts.length - supports.length

  const fullReport = [
    r.evidence.length === 1
      ? 'the text and source of the one record'
      : `the text and source of all ${records(r.evidence.length)}`,
    ...(r.assessmentParas.length ? ['the reasoning behind the score'] : []),
    ...(r.regulatoryContext.length ? ['the regulatory context'] : []),
    ...(r.dataGaps.length ? [`${count(r.dataGaps.length)} data ${r.dataGaps.length === 1 ? 'gap' : 'gaps'}`] : []),
  ]

  return (
    <section id="example" className="index-section">
      <div className="doc-container">
        <h2 className="index-heading">An example assessment</h2>
        <p className="index-sub">
          {reports.length === 1
            ? `${r.company} is the only company in the index, and its assessment is shown here.`
            : `Of the companies in the index, ${r.company} comes first in alphabetical order, so its assessment is shown here.`}
        </p>

        <div className="example-frame">
          <div className="report-meta">
            <span className="report-label">Extract from the assessment</span>
            {r.publishDate && <span className="report-date">{formatLongDate(r.publishDate)}</span>}
          </div>
          <h3 className="example-company">
            <a href={`/reports/${slug}`}>{r.company}</a>
          </h3>
          <p className="report-details example-details">
            {claimCountText(r)} · Prasine Index
          </p>

          <h4 className="example-label">Company score</h4>
          <div className="report-verdict-line example-verdict">
            <span className={`verdict-word ${agg.cls}`}>{agg.label}</span>
            <span className="verdict-score">{r.overallScore} / 100</span>
          </div>
          <p className="example-meta">
            {aggregateNote({ ...r, range })}
          </p>

          <h4 className="example-label example-gap">Claims</h4>
          <table className="dimension-table text-table example-claims">
            <thead>
              <tr><th>Score</th><th>Finding</th><th>Claim assessed</th></tr>
            </thead>
            <tbody>
              {r.claims.map((c, i) => {
                const f = verdictFromScore(c.score)
                return (
                  <tr key={c.num} className={i === detailIndex ? 'example-detail-row' : undefined}>
                    <td>{c.score} / 100</td>
                    <td><span className={`verdict-badge badge-${f.cls}`}>{f.label}</span></td>
                    <td>
                      {i === detailIndex
                        ? <strong>&ldquo;{c.text}&rdquo; (detailed below)</strong>
                        : <>&ldquo;{c.text}&rdquo;</>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {r.claimsNotes.length > 0 && (
            <div className="claims-notes">
              {r.claimsNotes.map((note, i) => (
                <p key={i}>{renderLinked(note)}</p>
              ))}
            </div>
          )}

          <h4 className="example-label example-gap">
            Highest-scoring{r.uncounted ? ' counted' : ''} claim
          </h4>
          <div className="report-claim example-claim">
            {r.claimSource && <div className="claim-attr">{renderLinked(r.claimSource)}</div>}
            <blockquote>&ldquo;{r.claim}&rdquo;</blockquote>
          </div>
          <div className="report-verdict-line example-verdict">
            <span className={`verdict-word ${detail.cls}`}>{detail.label}</span>
            <span className="verdict-score">{r.detailScore} / 100</span>
          </div>
          <p className="example-meta">
            The model&apos;s range {r.detailRange} · Confidence {r.detailConfidence}%
          </p>

          <p className="example-meta example-records-caption">
            How the model read the {records(r.evidence.length)} listed for this claim:
          </p>
          <dl className="example-records">
            <dt>Contradicts the claim</dt>
            <dd>{sourceList(contradicts)}</dd>
            <dt>Supports the claim</dt>
            <dd>{sourceList(supports)}</dd>
            <dt>Context</dt>
            <dd>{context === 0 ? 'none' : records(context)}</dd>
          </dl>

          <div className="key-finding example-key-finding">
            <p className="key-finding-label">Key finding</p>
            <p>{renderInline(r.keyFinding)}</p>
          </div>

          <details className="example-record">
            <summary>
              <span className="example-label">Company record</span>
              <span className="example-record-topics">
                Lobbying, new fossil fuel supply, verified emissions, targets, investor
                assessments and earlier decisions on environmental marketing
              </span>
            </summary>
            <div className="report-body">
              <p>
                The company record is built in code from the records and checked before
                publication. In some reports the review added context to it. It carries no score.
              </p>
              {r.companyRecord.paras.map((para, i) => (
                <p key={i}>{renderLinked(para)}</p>
              ))}
              <ul>
                {r.companyRecord.items.map((item, i) => (
                  <li key={i}>{renderLinked(item)}</li>
                ))}
              </ul>
            </div>
          </details>

          <div className="example-foot">
            <a className="example-btn" href={`/reports/${slug}`}>
              Read the full assessment of {r.company}
            </a>
            <p className="example-note">The full report also has {joinParts(fullReport)}.</p>
            <p className="example-note">
              A score describes how the records relate to a claim. It is not a legal finding. To
              report an error, write to{' '}
              <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
