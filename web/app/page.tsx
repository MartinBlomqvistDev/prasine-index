import ApplyForm from './apply-form'
import ExampleAssessment from './example-assessment'
import ScoreComparison from './score-comparison'
import { assessedDates, findingFromString, loadPublishedReports, loadReportSummaries } from '../lib/parse-report'
import { AWAITING_REASSESSMENT, PUBLISHED_SLUGS } from '../lib/site'

export const metadata = {
  alternates: { canonical: '/' },
}

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

function capitalised(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1)
}

export default function HomePage() {
  // Alphabetical: small differences between scores are not a ranking.
  const summaries = loadReportSummaries(PUBLISHED_SLUGS).sort((a, b) =>
    a.company.localeCompare(b.company, 'en'),
  )
  // A missing report would drop a company silently and move both ends of the comparison.
  const published = loadPublishedReports(PUBLISHED_SLUGS, AWAITING_REASSESSMENT)
  if (summaries.length !== PUBLISHED_SLUGS.length) {
    throw new Error(`${summaries.length} report summaries for ${PUBLISHED_SLUGS.length} published companies`)
  }
  // The date the page states is read from the reports, so a run that crosses midnight
  // cannot leave a hand-written date behind.
  const assessedText = assessedDates(published)

  return (
    <>
      {/* ── Nav ── */}
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo"><span>P</span>rasine Index</div>
          <div className="nav-links">
            <a href="/methodology" className="nav-link">Methodology</a>
            <a href="/about" className="nav-link">About</a>
            <a href="#apply" className="nav-btn">Request an assessment</a>
          </div>
        </div>
      </nav>

      <main>
      {/* ── Intro ── */}
      <section className="intro">
        <div className="doc-container">
          <h1 className="visually-hidden">Prasine Index</h1>
          <p className="intro-text">
            Prasine Index checks the climate claims of large European companies against
            public records: verified emissions in the EU Emissions Trading System,
            enforcement records on environmental marketing, the SBTi target register,
            lobbying assessments and open climate datasets. Each assessment is published
            with its evidence and sources, and the code is open source.
          </p>
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how" className="report-section">
        <div className="doc-container">
          <h2 className="index-heading">How an assessment works</h2>
          <div className="report-body">
            <ul>
              <li>
                Up to seven climate claims are collected from the company&apos;s own pages or
                reports, each with its source.
              </li>
              <li>
                Every claim is checked against 21 open data sources and against its own source
                document. Two of those sources, CDP and the EU Innovation Fund, hold no data in
                this version. A model reads the records
                and scores the claim. Fixed rules in code then set how far a score can go: above
                60 requires a record about the claim itself, and above 80 an official record that
                shows it to be false.
              </li>
              <li>
                Each assessment also sets out the company&apos;s record: lobbying, new fossil
                fuel supply, verified emissions, targets, investor assessments and earlier
                decisions on its environmental marketing. For a climate pledge, records of new
                fossil fuel supply and of lobbying count as records about the pledge, following
                two of the integrity criteria of the UN High-Level Expert Group on net-zero
                commitments. Investors&apos; assessments of the pledge count as records about it
                too.
              </li>
            </ul>
            <p>
              The <a href="/methodology">methodology</a> sets out the rules in full, and the{' '}
              <a href="/corrections">corrections log</a> lists the corrections made to
              published assessments.
            </p>
          </div>
        </div>
      </section>

      {/* ── Example (dynamic) ── */}
      <ExampleAssessment reports={published} />

      {/* ── Index (dynamic) ── */}
      <section id="index" className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">Assessments</h2>
          <p className="index-sub">
            {capitalised(NUMBER_WORDS[summaries.length] ?? String(summaries.length))} European{' '}
            {summaries.length === 1 ? 'company' : 'companies'}, assessed on {assessedText}. Each report sets out the claims, the evidence
            and the company record.
          </p>
          <table className="assessments-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Sector</th>
                <th>Score</th>
                <th>Finding</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map(({ company, slug, sector, score, verdict }) => {
                const vf = findingFromString(verdict)
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
            Scores from a model can vary between runs. Some of the claims that decide a company&apos;s band
            were scored more than once to test the judge&apos;s consistency; where the runs fall in
            two bands, the index publishes the lower band. The{' '}
            <a href="/methodology">methodology</a> gives the runs and names the companies whose
            claims were not tested. Small differences between
            companies should not be read as a ranking.
          </p>
          <ScoreComparison reports={published} assessedOn={assessedText} />
        </div>
      </section>

      {/* ── Apply ── */}
      <section id="apply" className="apply-section">
        <div className="doc-container">
          <h2>Request an assessment</h2>
          <p className="apply-sub">
            Name a company or a claim you want assessed, or ask a question, and I will reply
            by email.
          </p>
          <ApplyForm />
        </div>
      </section>

      </main>

      {/* ── Footer ── */}
      <footer>
        <div className="footer-inner">
          <div>
            <span>Prasine Index · Martin Blomqvist, 2026</span>
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
