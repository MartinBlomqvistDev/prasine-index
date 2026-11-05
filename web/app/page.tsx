import ApplyForm from './apply-form'
import { loadReportSummaries } from '../lib/parse-report'
import { PUBLISHED_SLUGS, WITHDRAWN_ON } from '../lib/site'

export const metadata = {
  alternates: { canonical: '/' },
}

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

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
            Prasine Index checks the climate claims of large European companies against
            public records: verified emissions in the EU Emissions Trading System,
            enforcement records on environmental marketing, climate target registries,
            lobbying assessments and open climate datasets. Each assessment is published
            with its evidence and sources, and the code is open source.
          </p>
        </div>
      </section>

      {/* ── Status ── */}
      <section id="status" className="report-section">
        <div className="doc-container">
          <div className="report-meta">
            <span className="report-label">Status</span>
            <span className="report-date">{WITHDRAWN_ON}</span>
          </div>
          <h2 className="index-heading">Version 2 in progress</h2>
          <div className="report-body">
            <p>
              In November 2026 every published assessment was reviewed against its
              sources. Since then, each enforcement record in the pipeline has been checked
              twice against its official source and now carries a verbatim quotation. The
              scoring is being redesigned so that a score can be traced to the records
              behind it.
            </p>
            <p>
              Three assessments were withdrawn after the review, and the{' '}
              <a href="/corrections">corrections page</a> explains why. The five below are
              under revision.
            </p>
          </div>
        </div>
      </section>

      {/* ── Index (dynamic) ── */}
      <section id="index" className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">Version 1 assessments</h2>
          <p className="index-sub">
            These {NUMBER_WORDS[summaries.length] ?? summaries.length} assessments were made
            with the version 1 method. Each report sets out the claims, the evidence and its
            sources.
          </p>
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
            Each report is under revision and will be reassessed with version 2.
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
            <a href="/corrections">Corrections</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
