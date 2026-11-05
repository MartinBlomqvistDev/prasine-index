import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { notFound } from 'next/navigation'
import { type ParsedReport, type EvidenceItem, type ClaimRow, parseReport, verdictFromScore } from '../../../lib/parse-report'


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

function verdictFromString(v: string): { cls: string; label: string } {
  const u = v.toUpperCase()
  if (u.includes('CONFIRMED'))   return { cls: 'confirmed',    label: 'Confirmed greenwashing' }
  if (u.includes('LIKELY'))      return { cls: 'greenwashing', label: 'Likely greenwashing'    }
  if (u.includes('MISLEADING'))  return { cls: 'misleading',   label: 'Misleading claim'       }
  if (u.includes('UNVERIFIABLE'))return { cls: 'insufficient', label: 'Unverifiable claim'     }
  return                                { cls: 'substantiated', label: 'Substantiated claim'    }
}

// ── Withdrawn assessments ────────────────────────────────────────────────────

const WITHDRAWN_ON = '5 November 2026'

// The URLs stay live so that anyone holding an old link reads the withdrawal
// instead of a 404. The report files themselves are removed.
const WITHDRAWN: Record<string, { company: string; reason: string }> = {
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

// ── Static params ─────────────────────────────────────────────────────────────

export function generateStaticParams() {
  return [
    { slug: 'ryanair-holdings-plc' },
    { slug: 'bp-plc' },
    { slug: 'glencore-plc' },
    { slug: 'enel-spa' },
    { slug: 'ikea-group' },
    { slug: 'h-m-group' },
    { slug: 'orsted-a-s' },
    { slug: 'ssab-ab' },
  ]
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const withdrawn = WITHDRAWN[slug]
  if (withdrawn) {
    return {
      title: `${withdrawn.company}: assessment withdrawn | Prasine Index`,
      description: `Withdrawn on ${WITHDRAWN_ON}: the assessment cited enforcement records that were wrong or could not be found.`,
    }
  }
  const name = slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return {
    title: `${name} | Prasine Index`,
    description: `EU greenwashing assessment for ${name}: evidence from 22 open data sources.`,
  }
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
            <a href="/#notice">Read the full notice</a>.
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

  const reportPath = join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)
  if (!existsSync(reportPath)) notFound()

  const md = readFileSync(reportPath, 'utf-8')
  const r = parseReport(md)
  const agg    = verdictFromString(r.verdict)
  const detail = verdictFromString(r.detailVerdict)

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
            changed. <a href="/#notice">Read the notice</a>.
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
              <tr><th>Score</th><th>Verdict</th><th>Claim assessed</th></tr>
            </thead>
            <tbody>
              {r.claims.map(c => (
                <tr
                  key={c.num}
                  style={c.score === r.detailScore ? { background: 'var(--surface-alt, #f7f7f7)' } : {}}
                >
                  <td style={c.score === r.detailScore ? { fontWeight: 700 } : {}}>
                    {c.score} / 100
                  </td>
                  <td>
                    <span className={`verdict-badge badge-${verdictFromScore(c.score).cls}`}>
                      {verdictFromScore(c.score).label}
                    </span>
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {c.score === r.detailScore
                      ? <strong>&ldquo;{c.text}&rdquo; &mdash; detailed below</strong>
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

        </div>
      </main>

      <ReportFooter />
    </>
  )
}
