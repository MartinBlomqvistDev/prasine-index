import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { notFound } from 'next/navigation'
import { type ParsedReport, type EvidenceItem, type ClaimRow, detailClaimIndex, findingFromString, formatLongDate, parseReport, rangeNumbers, verdictFromScore } from '../../../lib/parse-report'
import { PUBLISHED_SLUGS, WITHDRAWN, WITHDRAWN_ON, openGraphFor } from '../../../lib/site'
import { Blocks, aggregateNote, claimCountText, renderInline, renderLinked } from '../../../lib/render'


function evidenceWeight(supports: string): string {
  if (supports === 'No') return 'contra'
  if (supports === 'Yes') return 'support'
  return 'legislative'
}

// How the judge read a record. A record's confidence is a fixed value per source and
// reading, not a measure of the data, so it is not shown.
function evidenceWeightLabel(supports: string): string {
  if (supports === 'No') return 'Contradicts'
  if (supports === 'Yes') return 'Supports'
  return 'Context'
}


// ── Static params ─────────────────────────────────────────────────────────────

export function generateStaticParams() {
  return [...Object.keys(WITHDRAWN), ...PUBLISHED_SLUGS].map(slug => ({ slug }))
}

function reportPathFor(slug: string): string {
  return join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const canonical = `/reports/${slug}`
  const withdrawn = WITHDRAWN[slug]
  if (withdrawn) {
    const title = `${withdrawn.company}: assessment withdrawn | Prasine Index`
    const description = `${withdrawn.reason.split('. ')[0].replace(/\.$/, '')}.`
    return { title, description, alternates: { canonical }, openGraph: openGraphFor(title, description, canonical) }
  }
  const path = reportPathFor(slug)
  if (!existsSync(path)) return {}
  const r = parseReport(readFileSync(path, 'utf-8'))
  const title = `${r.company}: company assessment | Prasine Index`
  const finding = r.keyFinding.replace(/\*\*/g, '')
  const description = finding.length > 155 ? `${finding.slice(0, 152).trimEnd()}...` : finding
  return { title, description, alternates: { canonical }, openGraph: openGraphFor(title, description, canonical) }
}

// ── Shared chrome ────────────────────────────────────────────────────────────

function ReportNav() {
  return (
    <nav className="nav">
      <div className="nav-inner">
        <div className="nav-logo">
          <a href="/"><span>P</span>rasine Index</a>
        </div>
        <div className="nav-links">
          <a href="/#index" className="nav-link">All companies</a>
          <a href="/methodology" className="nav-link">Methodology</a>
          <a href="/about" className="nav-link">About</a>
          <a href="/#apply" className="nav-btn">Request an assessment</a>
        </div>
      </div>
    </nav>
  )
}

function ReportFooter() {
  return (
    <footer>
      <div className="footer-inner">
        <span>© 2026 Prasine Index · Martin Blomqvist</span>
        <div style={{ display: 'flex', gap: 20 }}>
          <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
          <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
        </div>
      </div>
    </footer>
  )
}

function WithdrawnPage({ company, reason }: { company: string; reason: string }) {
  return (
    <>
      <ReportNav />
      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>
        <div className="report-meta">
          <span className="report-label">Withdrawn</span>
          <span className="report-date">{WITHDRAWN_ON}</span>
        </div>
        <h1 className="report-company">{company}: assessment withdrawn</h1>
        <div className="report-body">
          <p>{reason}</p>
          <p>
            The <a href="/corrections">corrections log</a> lists the corrections made to published
            assessments.
          </p>
          <p>
            Questions and corrections:{' '}
            <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>
          </p>
        </div>
      </main>
      <ReportFooter />
    </>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default async function ReportPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const withdrawn = WITHDRAWN[slug]
  if (withdrawn) return <WithdrawnPage company={withdrawn.company} reason={withdrawn.reason} />

  const reportPath = reportPathFor(slug)
  if (!existsSync(reportPath)) notFound()

  const md = readFileSync(reportPath, 'utf-8')
  const r = parseReport(md)
  const agg    = findingFromString(r.verdict)
  const detail = findingFromString(r.detailVerdict)
  // The table previews each claim; mark the one the detailed section covers.
  const detailIndex = detailClaimIndex(r)
  const range = rangeNumbers(r.scoreRange)
  // Every distinct URL of every record, each once, in the order the records give them: a
  // record's own page and any document its text cites, such as the PDF a page reference
  // points into.
  const sources = r.evidence
    .flatMap(ev => ev.urls.map(url => ({ source: ev.source, url })))
    .filter((s, i, all) => all.findIndex(o => o.url === s.url) === i)

  return (
    <>
      <ReportNav />

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>

        {/* ── Report meta ── */}
        <div className="report-meta">
          <span className="report-label">Assessment</span>
          {r.publishDate && <span className="report-date">{formatLongDate(r.publishDate)}</span>}
        </div>

        <h1 className="report-company">{r.company}</h1>
        <p className="report-details">
          {claimCountText(r)} · Prasine Index
          {r.traceId && <> · <span style={{ fontFamily: "var(--font-mono), ui-monospace, monospace", fontSize: 11 }}>trace {r.traceId.slice(0, 8)}</span></>}
        </p>

        {/* ── Aggregate verdict ── */}
        <div className="report-verdict-line" style={{ marginTop: '1.5rem' }}>
          <span className={`verdict-word ${agg.cls}`}>{agg.label}</span>
          <span className="verdict-score">{r.overallScore} / 100</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, marginBottom: '1.5rem' }}>
          {aggregateNote({ ...r, range })}
        </p>

        {/* ── Claim overview table ── */}
        {r.claims.length > 0 && (
          <table className="dimension-table text-table" style={{ marginBottom: '1.5rem' }}>
            <thead>
              <tr><th>Score</th><th>Finding</th><th>Claim assessed</th></tr>
            </thead>
            <tbody>
              {r.claims.map((c, i) => (
                <tr
                  key={c.num}
                  style={i === detailIndex ? { background: 'var(--surface-alt, #f7f7f7)' } : {}}
                >
                  <td style={i === detailIndex ? { fontWeight: 700 } : {}}>
                    {c.score} / 100
                  </td>
                  <td>
                    <span className={`verdict-badge badge-${verdictFromScore(c.score).cls}`}>
                      {verdictFromScore(c.score).label}
                    </span>
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {i === detailIndex
                      ? <strong>&ldquo;{c.text}&rdquo; (detailed below)</strong>
                      : <>&ldquo;{c.text}&rdquo;</>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {r.claimsNotes.length > 0 && (
          <div className="claims-notes">
            {r.claimsNotes.map((note, i) => (
              <p key={i}>{renderLinked(note)}</p>
            ))}
          </div>
        )}

        {/* ── Company record ── */}
        {r.companyRecord.items.length > 0 && (
          <div className="report-body" style={{ marginBottom: '2rem' }}>
            <h2>Company record</h2>
            {r.companyRecord.paras.map((para, i) => (
              <p key={i}>{renderLinked(para)}</p>
            ))}
            <ul>
              {r.companyRecord.items.map((item, i) => (
                <li key={i}>{renderLinked(item)}</li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Divider ── */}
        <p style={{ fontSize: 12, color: 'var(--muted)', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
          Detailed assessment of the highest-scoring{r.uncounted ? ' counted' : ''} claim ({r.detailScore} / 100) follows.
        </p>

        {/* ── Featured claim ── */}
        {r.claim && (
          <div className="report-claim">
            {r.claimSource && <div className="claim-attr">{renderLinked(r.claimSource)}</div>}
            <blockquote>&ldquo;{r.claim}&rdquo;</blockquote>
          </div>
        )}

        {/* ── Claim verdict ── */}
        <div className="report-verdict-line">
          <span className={`verdict-word ${detail.cls}`}>{detail.label}</span>
          <span className="verdict-score">{r.detailScore} / 100</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>
          The model&apos;s range {r.detailRange} · Confidence {r.detailConfidence}%
        </p>

        <div className="report-body">

          {/* ── Evidence ── */}
          {r.evidence.length > 0 && (
            <>
              <h2>Evidence</h2>
              <div className="evidence-doc">
                {r.evidence.map(ev => (
                  <div className="ev-entry" key={ev.num}>
                    <div className="ev-number">{ev.num}</div>
                    <div className="ev-content">
                      <p className="ev-source-name">
                        {ev.url
                          ? <a href={ev.url} target="_blank" rel="noopener">{ev.source}</a>
                          : ev.source
                        }
                      </p>
                      <p className="ev-finding">{renderLinked(ev.body)}</p>
                      <p className={`ev-weight ${evidenceWeight(ev.supports)}`}>
                        {evidenceWeightLabel(ev.supports)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ── Assessment ── */}
          {r.assessmentParas.length > 0 && (
            <>
              <h2>Assessment</h2>
              <div className="report-reasoning">
                <Blocks blocks={r.assessmentParas} />
              </div>
            </>
          )}

          {/* ── Company context ── */}
          {r.companyContext.length > 0 && (
            <>
              <h2>Company context</h2>
              <div className="report-reasoning">
                <Blocks blocks={r.companyContext} />
              </div>
            </>
          )}

          {/* ── Regulatory context ── */}
          {r.regulatoryContext.length > 0 && (
            <>
              <h2>Regulatory context</h2>
              <div className="report-reasoning">
                <Blocks blocks={r.regulatoryContext} />
              </div>
            </>
          )}

          {/* ── Key finding ── */}
          {r.keyFinding && (
            <div className="key-finding">
              <p className="key-finding-label">Key finding</p>
              <p>{renderInline(r.keyFinding)}</p>
            </div>
          )}

          {/* ── Data gaps ── */}
          {r.dataGaps.length > 0 && (
            <>
              <h2>Data gaps</h2>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-gaps-table">
                  <thead>
                    <tr><th>Gap</th><th>Detail</th></tr>
                  </thead>
                  <tbody>
                    {r.dataGaps.map((gap, i) => {
                      const boldMatch = gap.match(/^\*\*([^*]+)\*\*:?\s*(.*)$/)
                      return (
                        <tr key={i}>
                          <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                            {boldMatch?.[1] ?? 'n/a'}
                          </td>
                          <td>{boldMatch?.[2] ?? gap}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* ── Sources ── */}
          {sources.length > 0 && (
            <>
              <h2>Sources</h2>
              <ol className="sources-list">
                {sources.map(({ source, url }) => (
                  <li key={url}>
                    {source}: <a href={url} target="_blank" rel="noopener">{url}</a>
                  </li>
                ))}
              </ol>
            </>
          )}

          {/* ── Disclaimer ── */}
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: '2.5rem', lineHeight: 1.6 }}>
            This assessment was produced by an automated pipeline from the sources listed
            above and reviewed before publication; errors found in the review were corrected.
            The score describes how the evidence relates to the claim. It is not a legal
            finding. To report an error, write to{' '}
            <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>. The{' '}
            <a href="/corrections">corrections log</a> lists the corrections made to published
            assessments.
          </p>

        </div>
      </main>

      <ReportFooter />
    </>
  )
}
