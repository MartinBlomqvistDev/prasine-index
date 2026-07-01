import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import ApplyForm from './apply-form'
import { parseReport, verdictFromScore, loadReportSummaries } from '../lib/parse-report'

const SLUGS = [
  'ryanair-holdings-plc',
  'bp-plc',
  'glencore-plc',
  'enel-spa',
  'ikea-group',
  'h-m-group',
]

function verdictFromString(v: string): { cls: string; label: string } {
  const u = v.toUpperCase()
  if (u.includes('CONFIRMED'))    return { cls: 'confirmed',    label: 'Confirmed'          }
  if (u.includes('LIKELY'))       return { cls: 'greenwashing', label: 'Likely greenwashing' }
  if (u.includes('MISLEADING'))   return { cls: 'misleading',   label: 'Misleading claim'   }
  if (u.includes('UNVERIFIABLE')) return { cls: 'insufficient', label: 'Unverifiable claim'  }
  return                                 { cls: 'substantiated', label: 'Substantiated claim' }
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
}

export default function HomePage() {
  const summaries = loadReportSummaries(SLUGS).sort((a, b) => b.score - a.score)

  const featuredPath = join(process.cwd(), '..', 'docs', 'reports', 'ryanair-holdings-plc.md')
  const featured = existsSync(featuredPath)
    ? parseReport(readFileSync(featuredPath, 'utf-8'))
    : null

  const counts = { confirmed: 0, likely: 0, misleading: 0, substantiated: 0 }
  for (const s of summaries) {
    const u = s.verdict.toUpperCase()
    if (u.includes('CONFIRMED'))    counts.confirmed++
    else if (u.includes('LIKELY'))  counts.likely++
    else if (u.includes('MISLEADING') || u.includes('UNVERIFIABLE')) counts.misleading++
    else counts.substantiated++
  }

  return (
    <>
      {/* ── Nav ── */}
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo"><span>P</span>rasine Index</div>
          <div className="nav-links">
            <a href="/methodology" className="nav-link">Methodology</a>
            <a href="#apply" className="nav-btn">Request an assessment</a>
          </div>
        </div>
      </nav>

      {/* ── Intro ── */}
      <section className="intro">
        <div className="doc-container">
          <p className="intro-text">
            Prasine Index verifies EU corporate sustainability claims against enforcement
            records, regulatory filings, lobbying data, and open climate datasets. Get in
            touch with a company and a claim. I run the full evidence pipeline and deliver
            a cited assessment report — built for journalists, NGOs, law firms, and activist investors.
          </p>
          <p className="intro-sub">
            Example output: what a Prasine Index assessment looks like.
          </p>
        </div>
      </section>

      {/* ── Featured report (dynamic) ── */}
      {featured && (
        <section className="report-section">
          <div className="doc-container">

            <div className="report-meta">
              <span className="report-label">Assessment</span>
              {featured.publishDate && <span className="report-date">{featured.publishDate}</span>}
            </div>

            <h1 className="report-company">{featured.company}</h1>
            <p className="report-details">
              {featured.claimCount} claim{featured.claimCount !== 1 ? 's' : ''} assessed · Prasine Index
              {featured.traceId && (
                <> · <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 11 }}>trace {featured.traceId.slice(0, 8)}</span></>
              )}
            </p>

            <div className="report-verdict-line" style={{ marginTop: '1.5rem' }}>
              <span className={`verdict-word ${verdictFromString(featured.verdict).cls}`}>
                {verdictFromString(featured.verdict).label === 'Confirmed'
                  ? 'Confirmed greenwashing'
                  : verdictFromString(featured.verdict).label}
              </span>
              <span className="verdict-score">{featured.overallScore} / 100</span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, marginBottom: '1.25rem' }}>
              Aggregate across {featured.claimCount} claim{featured.claimCount !== 1 ? 's' : ''} · range {featured.scoreRange}
            </p>

            {featured.claims.length > 0 && (
              <table className="dimension-table" style={{ marginBottom: '1.5rem' }}>
                <thead>
                  <tr><th>Score</th><th>Verdict</th><th>Claim assessed</th></tr>
                </thead>
                <tbody>
                  {featured.claims.map(c => {
                    const isDetail = c.score === featured.detailScore
                    const vf = verdictFromScore(c.score)
                    return (
                      <tr key={c.num} style={isDetail ? { background: 'var(--surface-alt, #f7f7f7)' } : {}}>
                        <td style={isDetail ? { fontWeight: 700 } : {}}>{c.score} / 100</td>
                        <td><span className={`verdict-badge badge-${vf.cls}`}>{vf.label}</span></td>
                        <td style={{ fontSize: 12 }}>
                          {isDetail
                            ? <strong>&ldquo;{c.text}&rdquo; &mdash; detailed below</strong>
                            : <>&ldquo;{c.text}&rdquo;</>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}

            <p style={{ fontSize: 12, color: 'var(--muted)', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
              Detailed assessment of highest-scoring claim ({featured.detailScore} / 100) follows.
            </p>

            {featured.claim && (
              <div className="report-claim">
                {featured.claimSource && <div className="claim-attr">{featured.claimSource}</div>}
                <blockquote>&ldquo;{featured.claim}&rdquo;</blockquote>
              </div>
            )}

            <div className="report-verdict-line">
              <span className={`verdict-word ${verdictFromString(featured.detailVerdict).cls}`}>
                {verdictFromString(featured.detailVerdict).label === 'Confirmed'
                  ? 'Confirmed greenwashing'
                  : verdictFromString(featured.detailVerdict).label}
              </span>
              <span className="verdict-score">{featured.detailScore} / 100</span>
            </div>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>
              Range {featured.detailRange} · Confidence {featured.detailConfidence}%
            </p>

            <div className="report-body">
              {featured.keyFinding && (
                <div className="key-finding">
                  <p className="key-finding-label">Key finding</p>
                  <p>{renderInline(featured.keyFinding)}</p>
                </div>
              )}

              {featured.assessmentParas.length > 0 && (
                <>
                  <h2>Assessment</h2>
                  <div className="report-reasoning">
                    {featured.assessmentParas.map((para, i) => (
                      <p key={i}>{renderInline(para)}</p>
                    ))}
                  </div>
                </>
              )}

              <div style={{ marginTop: '1.5rem' }}>
                <a href="/reports/ryanair-holdings-plc" className="nav-btn">
                  Full evidence chain and data sources
                </a>
              </div>
            </div>

          </div>
        </section>
      )}

      {/* ── Index (dynamic) ── */}
      <section id="index" className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">The Index</h2>
          <p className="index-sub">
            {summaries.length} EU companies assessed across multiple sectors. Evidence drawn from 22 open data sources per run.
          </p>
          <div className="index-stats">
            <span className="index-stat"><strong>{counts.confirmed}</strong> confirmed</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>{counts.likely}</strong> likely greenwashing</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>{counts.misleading}</strong> misleading / unverifiable</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>{counts.substantiated}</strong> substantiated</span>
          </div>
          <table className="assessments-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Sector</th>
                <th>Score</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map(({ company, slug, sector, score, verdict }) => {
                const vf = verdictFromString(verdict)
                return (
                  <tr key={slug}>
                    <td colSpan={4} style={{ padding: 0, border: 'none' }}>
                      <a
                        href={`/reports/${slug}`}
                        style={{ display: 'table', width: '100%', tableLayout: 'fixed', textDecoration: 'none', color: 'inherit', cursor: 'pointer' }}
                      >
                        <span style={{ display: 'table-cell', padding: '10px 12px', fontWeight: 500 }}>{company}</span>
                        <span style={{ display: 'table-cell', padding: '10px 12px', color: 'var(--muted)', fontFamily: "'Space Mono', monospace", fontSize: 12 }}>{sector}</span>
                        <span style={{ display: 'table-cell', padding: '10px 12px', fontFamily: "'Space Mono', monospace", fontWeight: 700 }}>{score}</span>
                        <span style={{ display: 'table-cell', padding: '10px 12px' }}>
                          <span className={`verdict-badge badge-${vf.cls}`}>{vf.label}</span>
                        </span>
                      </a>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="index-note">
            Click any row for the full evidence chain and scoring breakdown.
          </p>
        </div>
      </section>

      {/* ── Apply ── */}
      <section id="apply" className="apply-section">
        <div className="doc-container">
          <h2>Request an assessment</h2>
          <p className="apply-sub">
            I&apos;m running a limited number of pilot assessments for journalists, NGOs,
            legal researchers, and analysts. Get in touch — send a company, a claim, or
            just describe what you&apos;re investigating. I&apos;ll come back with whether
            it&apos;s a fit and what&apos;s involved.
          </p>
          <ApplyForm />
        </div>
      </section>

      {/* ── Footer ── */}
      <footer>
        <div className="footer-inner">
          <div>
            <span>Prasine Index — Martin Blomqvist, 2026</span>
            <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              EU greenwashing analyst · Prasine Index
            </p>
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="https://linkedin.com/in/martin-blomqvist" target="_blank" rel="noopener">LinkedIn</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
