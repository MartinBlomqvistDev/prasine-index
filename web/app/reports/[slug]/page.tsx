import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { notFound } from 'next/navigation'
import { type ParsedReport, type EvidenceItem, type ClaimRow, findingFromString, parseReport, verdictFromScore } from '../../../lib/parse-report'
import { PUBLISHED_SLUGS, WITHDRAWN, WITHDRAWN_ON } from '../../../lib/site'


function evidenceWeight(supports: string): string {
  if (supports === 'No') return 'contra'
  if (supports === 'Yes') return 'support'
  return 'legislative'
}

function evidenceWeightLabel(supports: string, confidence: number): string {
  const pct = Math.round(confidence * 100)
  const confStr = pct > 0 ? ` · ${pct}%` : ''
  if (supports === 'No') return `Contradicts${confStr}`
  if (supports === 'Yes') return `Supports${confStr}`
  return `Context${confStr}`
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
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
    const description = `Withdrawn on ${WITHDRAWN_ON}: the assessment cited enforcement records that were wrong or could not be found.`
    return { title, description, alternates: { canonical }, openGraph: { title, description, url: canonical } }
  }
  const path = reportPathFor(slug)
  if (!existsSync(path)) return {}
  const r = parseReport(readFileSync(path, 'utf-8'))
  const title = `${r.company}: claim assessment | Prasine Index`
  const finding = r.keyFinding.replace(/\*\*/g, '')
  const description = finding.length > 155 ? `${finding.slice(0, 152).trimEnd()}...` : finding
  return { title, description, alternates: { canonical }, openGraph: { title, description, url: canonical } }
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
          <p>
            This assessment was withdrawn on {WITHDRAWN_ON}. It cited enforcement records
            that were wrong or could not be found.
          </p>
          <p>{reason}</p>
          <p>
            Any corrected assessment will be published with a log of what changed.{' '}
            <a href="/corrections">Read the full notice</a>.
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
  // The table previews each claim; mark the one the detailed section covers,
  // matching on text first because several claims can share a score.
  const textIndex = r.claims.findIndex(c => {
    const preview = c.text.replace(/(\.{3}|…)$/, '').trim()
    return preview.length > 0 && r.claim.startsWith(preview.slice(0, 60))
  })
  const detailIndex = textIndex > -1 ? textIndex : r.claims.findIndex(c => c.score === r.detailScore)

  return (
    <>
      <ReportNav />

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>

        {/* ── Revision notice ── */}
        <div className="key-finding" style={{ marginBottom: '2rem' }}>
          <p className="key-finding-label">Under revision</p>
          <p style={{ fontSize: 14, lineHeight: 1.7 }}>
            A review on 3 November 2026 found errors in this report, including statements
            about EU law. A corrected version will replace it, with a log of what
            changed. <a href="/corrections">Read the notice</a>.
          </p>
        </div>

        {/* ── Report meta ── */}
        <div className="report-meta">
          <span className="report-label">Assessment</span>
          {r.publishDate && <span className="report-date">{r.publishDate}</span>}
        </div>

        <h1 className="report-company">{r.company}</h1>
        <p className="report-details">
          {r.claimCount} claim{r.claimCount !== 1 ? 's' : ''} assessed · Prasine Index
          {r.traceId && <> · <span style={{ fontFamily: "var(--font-mono), ui-monospace, monospace", fontSize: 11 }}>trace {r.traceId.slice(0, 8)}</span></>}
        </p>

        {/* ── Aggregate verdict ── */}
        <div className="report-verdict-line" style={{ marginTop: '1.5rem' }}>
          <span className={`verdict-word ${agg.cls}`}>{agg.label}</span>
          <span className="verdict-score">{r.overallScore} / 100</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, marginBottom: '1.5rem' }}>
          Aggregate across {r.claimCount} claim{r.claimCount !== 1 ? 's' : ''} · range {r.scoreRange}
        </p>

        {/* ── Claim overview table ── */}
        {r.claims.length > 0 && (
          <table className="dimension-table" style={{ marginBottom: '1.5rem' }}>
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

        {/* ── Divider ── */}
        <p style={{ fontSize: 12, color: 'var(--muted)', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
          Detailed assessment of highest-scoring claim ({r.detailScore} / 100) follows.
        </p>

        {/* ── Featured claim ── */}
        {r.claim && (
          <div className="report-claim">
            {r.claimSource && <div className="claim-attr">{r.claimSource}</div>}
            <blockquote>&ldquo;{r.claim}&rdquo;</blockquote>
          </div>
        )}

        {/* ── Claim verdict ── */}
        <div className="report-verdict-line">
          <span className={`verdict-word ${detail.cls}`}>{detail.label}</span>
          <span className="verdict-score">{r.detailScore} / 100</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>
          Range {r.detailRange} · Confidence {r.detailConfidence}%
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
                      <p className="ev-finding">{renderInline(ev.body)}</p>
                      <p className={`ev-weight ${evidenceWeight(ev.supports)}`}>
                        {evidenceWeightLabel(ev.supports, ev.confidence)}
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
                {r.assessmentParas.map((para, i) => (
                  <p key={i}>{renderInline(para)}</p>
                ))}
              </div>
            </>
          )}

          {/* ── Company context ── */}
          {r.companyContext.length > 0 && (
            <>
              <h2>Company context</h2>
              <div className="report-reasoning">
                {r.companyContext.map((para, i) => (
                  <p key={i}>{renderInline(para)}</p>
                ))}
              </div>
            </>
          )}

          {/* ── Regulatory context ── */}
          {r.regulatoryContext.length > 0 && (
            <>
              <h2>Regulatory context</h2>
              <div className="report-reasoning">
                {r.regulatoryContext.map((para, i) => (
                  <p key={i}>{renderInline(para)}</p>
                ))}
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
                    <tr><th>Source</th><th>Detail</th></tr>
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
          {r.evidence.filter(e => e.url).length > 0 && (
            <>
              <h2>Sources</h2>
              <ol className="sources-list">
                {r.evidence.filter(e => e.url).map(ev => (
                  <li key={ev.num}>
                    {ev.source}: <a href={ev.url} target="_blank" rel="noopener">{ev.url}</a>
                  </li>
                ))}
              </ol>
            </>
          )}

          {/* ── Disclaimer ── */}
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: '2.5rem', lineHeight: 1.6 }}>
            This assessment was produced by an automated pipeline from the sources listed
            above. The score describes how the evidence relates to the claim and is not a
            legal finding. Corrections and replies:{' '}
            <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>. The{' '}
            <a href="/about">about page</a> sets out the corrections policy and the right of
            reply.
          </p>

        </div>
      </main>

      <ReportFooter />
    </>
  )
}
