export const metadata = {
  title: 'About | Prasine Index',
  description:
    'Who runs Prasine Index, how an assessment is made, where corrections are listed, and how to cite it.',
  alternates: { canonical: '/about' },
}

export default function AboutPage() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <a href="/"><span>P</span>rasine Index</a>
          </div>
          <div className="nav-links">
            <a href="/methodology" className="nav-link">Methodology</a>
            <a href="/about" className="nav-link" style={{ color: 'var(--text)' }}>About</a>
            <a href="/#apply" className="nav-btn">Get in touch</a>
          </div>
        </div>
      </nav>

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>
        <div className="report-meta">
          <span className="report-label">About</span>
        </div>
        <h1 className="report-company" style={{ marginBottom: '0.5rem' }}>About Prasine Index</h1>
        <p style={{ color: 'var(--muted)', fontSize: 15, marginBottom: '3rem', lineHeight: 1.6 }}>
          Who runs Prasine Index, how an assessment is made, where corrections are listed,
          and how to cite it.
        </p>

        <div className="report-body">
          <h2>Who runs it</h2>
          <p>
            Prasine Index is built and run by Martin Blomqvist, a data scientist based in
            Sweden.
          </p>

          <h2>How an assessment is made</h2>
          <p>
            An automated pipeline collects public data about a company&apos;s climate claims
            and scores how the evidence relates to each claim. The{' '}
            <a href="/methodology">methodology page</a> describes the sources, the scoring
            and the known limits. A score describes the evidence and does not amount to a
            legal finding.
          </p>

          <h2>Corrections</h2>
          <p>
            Corrections to published assessments are listed on the{' '}
            <a href="/corrections">corrections page</a>. To report an error, write to{' '}
            <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>.
          </p>

          <h2>How to cite</h2>
          <p>
            Cite an assessment with the company, the year of the assessment and its address,
            for example: Prasine Index (2026). [Company]: company assessment.
            https://www.prasineindex.com/reports/[company]. Accessed [date].
          </p>
          <p>
            Cite the software with the{' '}
            <a href="https://github.com/MartinBlomqvistDev/prasine-index/blob/main/CITATION.cff" target="_blank" rel="noopener">CITATION.cff</a>{' '}
            file in the repository.
          </p>

          <h2>Licence</h2>
          <p>
            The assessments and the text on this site are licensed under{' '}
            <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>.
            The code is open source under the MIT licence. Third-party data quoted in the
            assessments keeps its own licence.
          </p>

          <h2>Contact</h2>
          <p>
            <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>
          </p>
        </div>
      </main>

      <footer>
        <div className="footer-inner">
          <span>© 2026 Prasine Index · Martin Blomqvist</span>
          <div style={{ display: 'flex', gap: 20 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
