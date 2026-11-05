import ApplyForm from './apply-form'
import { loadReportSummaries } from '../lib/parse-report'
import { PUBLISHED_SLUGS, WITHDRAWN_ON } from '../lib/site'

export const metadata = {
  alternates: { canonical: '/' },
}

function verdictFromString(v: string): { cls: string; label: string } {
  const u = v.toUpperCase()
  if (u.includes('CONFIRMED'))    return { cls: 'confirmed',    label: 'Confirmed'          }
  if (u.includes('LIKELY'))       return { cls: 'greenwashing', label: 'Likely greenwashing' }
  if (u.includes('MISLEADING'))   return { cls: 'misleading',   label: 'Misleading claim'   }
  if (u.includes('UNVERIFIABLE')) return { cls: 'insufficient', label: 'Unverifiable claim'  }
  return                                 { cls: 'substantiated', label: 'Substantiated claim' }
}

export default function HomePage() {
  const summaries = loadReportSummaries(PUBLISHED_SLUGS).sort((a, b) => b.score - a.score)

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
            <a href="/about" className="nav-link">About</a>
            <a href="#apply" className="nav-btn">Get in touch</a>
          </div>
        </div>
      </nav>

      {/* ── Intro ── */}
      <section className="intro">
        <div className="doc-container">
          <p className="intro-text">
            Prasine Index verifies EU corporate sustainability claims against enforcement
            records, regulatory filings, lobbying data, and open climate datasets. Research
            built for journalists, NGOs, and researchers investigating greenwashing.
          </p>
        </div>
      </section>

      {/* ── Notice ── */}
      <section id="notice" className="report-section">
        <div className="doc-container">
          <div className="report-meta">
            <span className="report-label">Notice</span>
            <span className="report-date">{WITHDRAWN_ON}</span>
          </div>
          <h1 className="report-company">Three assessments withdrawn</h1>
          <div className="report-body">
            <p>
              The assessments of Ryanair, Glencore and BP have been withdrawn. A review of
              the published reports on 3 November 2026 found that their confirmed verdicts
              rested on enforcement records that were wrong or could not be found:
            </p>
            <ul>
              <li>
                <strong>Ryanair:</strong> the report cited ASA ruling G20-1089921, which
                concerns a 2021 advertisement about Covid-19 vaccination. The ASA&apos;s
                ruling on Ryanair&apos;s emissions advertising is dated 5 February 2020. The
                report also called the EU consumer authorities&apos; action on airline
                climate claims unresolved; Ryanair&apos;s part was resolved with commitments
                in November 2025.
              </li>
              <li>
                <strong>BP:</strong> the report cited an ASA ruling from July 2019 as a prior
                finding against BP&apos;s advertising. No such ruling could be found.
              </li>
              <li>
                <strong>Glencore:</strong> the report cited an open investigation by the UK
                Competition and Markets Authority. No such investigation could be found.
              </li>
            </ul>
            <p>
              The review also found that a single company-level rating could place every
              claim from the same company in the confirmed band. The verdicts cannot stand
              as published.
            </p>
            <p>
              The five remaining reports stay online while they are corrected, and each is
              marked as under revision. All eight reports describe the Green Claims
              Directive as enforced from September 2026; it was never adopted. Seven state
              that a claim violates the Empowering Consumers Directive, (EU) 2024/825. The
              reports were published in July, and that directive applies from 27 September
              2026, to marketing aimed at consumers.
            </p>
            <p>
              The pipeline is being changed so that an enforcement record can only be cited
              with a verbatim quotation from the authority&apos;s own page. Corrected
              assessments will be published with a log of what changed.
            </p>
            <p>
              Questions and corrections:{' '}
              <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>
            </p>
          </div>
        </div>
      </section>

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
                        <span style={{ display: 'table-cell', padding: '10px 12px', color: 'var(--muted)', fontFamily: "var(--font-mono), ui-monospace, monospace", fontSize: 12 }}>{sector}</span>
                        <span style={{ display: 'table-cell', padding: '10px 12px', fontFamily: "var(--font-mono), ui-monospace, monospace", fontWeight: 700 }}>{score}</span>
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
            Click any row for the full evidence chain. All five assessments are under
            revision; see the notice above.
          </p>
        </div>
      </section>

      {/* ── Apply ── */}
      <section id="apply" className="apply-section">
        <div className="doc-container">
          <h2>Suggest a company</h2>
          <p className="apply-sub">
            Investigating a company&apos;s green claims? Send a company, a claim, or
            just describe what you&apos;re looking into. If it fits the index,
            I&apos;ll run it through the pipeline and publish the evidence chain.
          </p>
          <ApplyForm />
        </div>
      </section>

      {/* ── Footer ── */}
      <footer>
        <div className="footer-inner">
          <div>
            <span>Prasine Index · Martin Blomqvist, 2026</span>
            <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              EU greenwashing analyst · Prasine Index
            </p>
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="https://linkedin.com/in/martin-blomqvist" target="_blank" rel="noopener">LinkedIn</a>
            <a href="/about">About</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
