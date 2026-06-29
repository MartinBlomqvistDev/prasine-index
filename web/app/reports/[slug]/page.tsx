import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { notFound } from 'next/navigation'

// ── Types ────────────────────────────────────────────────────────────────────

interface EvidenceItem {
  num: number
  source: string
  body: string
  supports: 'Yes' | 'No' | 'N/A' | string
  confidence: number
  url?: string
}

interface ClaimRow {
  num: number
  score: number
  verdict: string
  text: string
}

interface ParsedReport {
  company: string
  claimCount: number
  overallScore: number
  scoreRange: string
  verdict: string
  confidence: number
  claims: ClaimRow[]
  // Featured claim detail
  detailVerdict: string
  detailScore: number
  detailRange: string
  detailConfidence: number
  publishDate: string
  traceId: string
  claim: string
  claimSource: string
  evidence: EvidenceItem[]
  assessmentParas: string[]
  keyFinding: string
  dataGaps: string[]
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function verdictFromScore(score: number): { cls: string; label: string } {
  if (score <= 20) return { cls: 'substantiated', label: 'Substantiated claim' }
  if (score <= 40) return { cls: 'insufficient',  label: 'Unverifiable claim'  }
  if (score <= 60) return { cls: 'misleading',    label: 'Misleading claim'    }
  if (score <= 80) return { cls: 'greenwashing',  label: 'Likely greenwashing' }
  return             { cls: 'confirmed',    label: 'Confirmed greenwashing' }
}

function evidenceWeight(supports: string): string {
  if (supports === 'No') return 'contra'
  if (supports === 'Yes') return 'support'
  return 'legislative'
}

function evidenceWeightLabel(supports: string, confidence: number): string {
  const pct = Math.round(confidence * 100)
  if (supports === 'No') return `Contradicts · ${pct}%`
  if (supports === 'Yes') return `Supports · ${pct}%`
  return `Context · ${pct}%`
}

// Render a paragraph that may contain **bold** spans
function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
}

// ── Parser ───────────────────────────────────────────────────────────────────

function parseReport(md: string): ParsedReport {
  // Aggregate header: "## Company — Company Assessment (N claims)"
  const headerMatch = md.match(/^## (.+?) — Company Assessment \((\d+) claim/m)
  const company = headerMatch?.[1] ?? 'Unknown Company'
  const claimCount = parseInt(headerMatch?.[2] ?? '1')

  const overallScore = parseInt(md.match(/\*\*Overall Score: (\d+)\/100\*\*/)?.[1] ?? '0')
  const scoreRange = md.match(/\*\*Score range:\*\* ([^\n]+)/)?.[1]?.trim() ?? ''
  const verdict = md.match(/\*\*Verdict:\*\* ([^\n*]+)/)?.[1]?.trim() ?? ''
  const confidence = parseInt(md.match(/\*\*Confidence:\*\* (\d+)%/)?.[1] ?? '0')

  // Claims table rows (skip header and separator)
  const claims: ClaimRow[] = md
    .split('\n')
    .filter(l => /^\| \d+/.test(l))
    .map(l => {
      const cells = l.split('|').map(c => c.trim()).filter(Boolean)
      return {
        num: parseInt(cells[0]),
        score: parseInt(cells[1]),
        verdict: cells[2],
        text: cells[3] ?? '',
      }
    })

  // Detail header: "**Verdict: X** | Score: N/100 (range: A–B) | Confidence: C%"
  const detailHeader = md.match(/\*\*Verdict: ([^*]+)\*\* \| Score: ([\d.]+)\/100 \(range: ([^)]+)\) \| Confidence: (\d+)%/)
  const detailVerdict = detailHeader?.[1]?.trim() ?? verdict
  const detailScore = parseFloat(detailHeader?.[2] ?? String(overallScore))
  const detailRange = detailHeader?.[3]?.trim() ?? scoreRange
  const detailConfidence = parseInt(detailHeader?.[4] ?? String(confidence))

  const publishMatch = md.match(/\*Published: ([^|]+) \| Prasine Index \| Trace ID: ([^*\n]+)\*/)
  const publishDate = publishMatch?.[1]?.trim() ?? ''
  const traceId = publishMatch?.[2]?.trim() ?? ''

  // Claim blockquote: > "..."
  const claimMatch = md.match(/> "([^"]+)"/)
  const claim = claimMatch?.[1] ?? ''

  // Claim source line: *Source: ...*
  const claimSource = md.match(/\*Source: ([^\n*]+)\*/)?.[1]?.trim() ?? ''

  // Evidence section
  const evStart = md.indexOf('### Evidence')
  const evEnd = md.indexOf('### Assessment')
  const evSection = evStart > -1 && evEnd > -1 ? md.slice(evStart, evEnd) : ''

  const evidence: EvidenceItem[] = evSection
    .split(/\n\n(?=\*\*\[\d+\])/)
    .filter(chunk => /^\*\*\[\d+\]/.test(chunk.trim()))
    .map(chunk => {
      const hm = chunk.match(/^\*\*\[(\d+)\] ([^*]+)\*\* ([\s\S]+)$/)
      if (!hm) return null
      const num = parseInt(hm[1])
      const source = hm[2].trim().replace(/\.$/, '')
      let body = hm[3].trim()

      const supportsMatch = body.match(/Supports claim: ([^.]+)\./)
      const supports = supportsMatch?.[1]?.trim() ?? 'N/A'
      const confMatch = body.match(/Confidence: ([\d.]+)\./)
      const conf = parseFloat(confMatch?.[1] ?? '0')
      const urlMatch = body.match(/(https?:\/\/\S+)$/)
      const url = urlMatch?.[1]

      // Clean body: strip trailing metadata
      body = body
        .replace(/\s*Supports claim: [^.]+\.\s*/g, ' ')
        .replace(/\s*Confidence: [\d.]+\.\s*/g, ' ')
        .replace(/(https?:\/\/\S+)$/, '')
        .trim()

      return { num, source, body, supports, confidence: conf, url }
    })
    .filter((e): e is NonNullable<typeof e> => e !== null)

  // Assessment paragraphs
  const assStart = md.indexOf('### Assessment')
  const kfStart = md.indexOf('### Key Finding')
  const assessmentParas = assStart > -1 && kfStart > -1
    ? md.slice(assStart + '### Assessment\n'.length, kfStart)
        .split(/\n\n+/)
        .map(p => p.trim())
        .filter(p => p.length > 0 && !p.startsWith('#'))
    : []

  // Key Finding
  const dgStart = md.indexOf('### Data Gaps')
  const keyFinding = kfStart > -1
    ? md.slice(kfStart + '### Key Finding\n'.length, dgStart > -1 ? dgStart : undefined)
        .split(/\n\n+/)
        .map(p => p.trim())
        .filter(p => p.length > 0 && !p.startsWith('#'))
        .join(' ')
    : ''

  // Data Gaps
  const methStart = md.indexOf('### Methodology')
  const dataGapsRaw = dgStart > -1
    ? md.slice(dgStart + '### Data Gaps\n'.length, methStart > -1 ? methStart : undefined)
    : ''
  const dataGaps = dataGapsRaw
    .split('\n')
    .filter(l => l.startsWith('- '))
    .map(l => l.slice(2).trim())

  return {
    company, claimCount, overallScore, scoreRange, verdict, confidence, claims,
    detailVerdict, detailScore, detailRange, detailConfidence,
    publishDate, traceId, claim, claimSource,
    evidence, assessmentParas, keyFinding, dataGaps,
  }
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
  ]
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const name = slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return {
    title: `${name} — Prasine Index`,
    description: `EU greenwashing assessment for ${name} — evidence from 22 open data sources.`,
  }
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default async function ReportPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const reportPath = join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)
  if (!existsSync(reportPath)) notFound()

  const md = readFileSync(reportPath, 'utf-8')
  const r = parseReport(md)
  const agg    = verdictFromScore(r.overallScore)
  const detail = verdictFromScore(r.detailScore)

  return (
    <>
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

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>

        {/* ── Report meta ── */}
        <div className="report-meta">
          <span className="report-label">Assessment</span>
          {r.publishDate && <span className="report-date">{r.publishDate}</span>}
        </div>

        <h1 className="report-company">{r.company}</h1>
        <p className="report-details">
          {r.claimCount} claim{r.claimCount !== 1 ? 's' : ''} assessed · Prasine Index
          {r.traceId && <> · <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 11 }}>trace {r.traceId.slice(0, 8)}</span></>}
        </p>

        {/* ── Aggregate verdict ── */}
        <div className="report-verdict-line" style={{ marginTop: '1.5rem' }}>
          <span className={`verdict-word ${agg.cls}`}>{agg.label}</span>
          <span className="verdict-score">{r.overallScore} / 100</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, marginBottom: '1.5rem' }}>
          Confidence-weighted aggregate across {r.claimCount} claim{r.claimCount !== 1 ? 's' : ''} · range {r.scoreRange}
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
                          {boldMatch?.[1] ?? '—'}
                        </td>
                        <td>{boldMatch?.[2] ?? gap}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}

          {/* ── Sources ── */}
          {r.evidence.filter(e => e.url).length > 0 && (
            <>
              <h2>Sources</h2>
              <ol className="sources-list">
                {r.evidence.filter(e => e.url).map(ev => (
                  <li key={ev.num}>
                    {ev.source} — <a href={ev.url} target="_blank" rel="noopener">{ev.url}</a>
                  </li>
                ))}
              </ol>
            </>
          )}

        </div>
      </main>

      <footer>
        <div className="footer-inner">
          <span>© 2026 Prasine Index — Martin Blomqvist</span>
          <div style={{ display: 'flex', gap: 20 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
