import { openGraphFor } from '../../lib/site'

export const metadata = {
  title: 'About | Prasine Index',
  description:
    'Who runs Prasine Index, how an assessment is made, where corrections are listed, how to cite it, and how personal data is handled.',
  alternates: { canonical: '/about' },
  openGraph: openGraphFor(
    'About | Prasine Index',
    'Who runs Prasine Index, how an assessment is made, where corrections are listed, how to cite it, and how personal data is handled.',
    '/about',
  ),
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
            <a href="/#apply" className="nav-btn">Request an assessment</a>
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
          how to cite it, and how personal data is handled.
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
            and scores how the evidence relates to each claim. Each report was reviewed against its
            records and sources before publication. The{' '}
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
            Cite an assessment with the company, the date of the assessment, its address and the
            date you accessed it, for example: Prasine Index (2026). [Company]: company
            assessment, assessed [date]. [Address of the report]. Accessed [date].
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

          <h2 id="privacy">Privacy</h2>
          <p>
            Prasine Index is run by me, Martin Blomqvist, and I am responsible for the personal data
            it handles (<a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>).
          </p>
          <ul>
            <li>
              The contact form sends your name, email address, any link and your message to me
              through Formspree, a form service, which stores them and forwards them to me by email. They are used only
              to answer you, on the basis of the legitimate interest in answering a message you
              chose to send. I keep a message for as long as the matter it concerns is open, and
              at most two years.
            </li>
            <li>
              The site is hosted by Vercel, which also counts page views with Vercel Web
              Analytics, so that I can see which pages are read. That rests on the legitimate
              interest in knowing how the site is used.
            </li>
            <li>
              Formspree and Vercel are based in the United States and may process the data
              there.
            </li>
            <li>
              You can ask which data about you is held, and have it corrected or deleted, by
              writing to <a href="mailto:cm.blomqvist@gmail.com">cm.blomqvist@gmail.com</a>. You
              can also complain to the Swedish Authority for Privacy Protection (IMY),{' '}
              <a href="https://www.imy.se" target="_blank" rel="noopener">https://www.imy.se</a>.
            </li>
          </ul>

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
