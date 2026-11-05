import { WITHDRAWN_ON } from '../../lib/site'

export const metadata = {
  title: 'Corrections | Prasine Index',
  description: 'Corrections to assessments published on Prasine Index.',
  alternates: { canonical: '/corrections' },
}

export default function CorrectionsPage() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <a href="/"><span>P</span>rasine Index</a>
          </div>
          <div className="nav-links">
            <a href="/methodology" className="nav-link">Methodology</a>
            <a href="/about" className="nav-link">About</a>
            <a href="/#apply" className="nav-btn">Get in touch</a>
          </div>
        </div>
      </nav>

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>
        <div className="report-meta">
          <span className="report-label">Corrections</span>
        </div>
        <h1 className="report-company" style={{ marginBottom: '0.5rem' }}>Corrections</h1>
        <p style={{ color: 'var(--muted)', fontSize: 15, marginBottom: '3rem', lineHeight: 1.6 }}>
          Corrections to assessments published on Prasine Index, newest first.
        </p>

        <div className="report-body">
          <h2 id="notice">{WITHDRAWN_ON}: three assessments withdrawn</h2>
          <p>
            The assessments of Ryanair, Glencore and BP have been withdrawn. A review of
            the published reports on 3 November 2026 found that their confirmed verdicts
            rested on enforcement records that were wrong or could not be found:
          </p>
          <ul>
            <li>
              <strong>Ryanair:</strong>{' '}the report cited ASA ruling G20-1089921, which
              concerns a 2021 advertisement about Covid-19 vaccination. The ASA&apos;s
              ruling on Ryanair&apos;s emissions advertising is dated 5 February 2020. The
              report also called the EU consumer authorities&apos; action on airline
              climate claims unresolved; Ryanair&apos;s part was resolved with commitments
              in November 2025.
            </li>
            <li>
              <strong>BP:</strong>{' '}the report cited an ASA ruling from July 2019 as a prior
              finding against BP&apos;s advertising. No such ruling could be found. An ASA
              ruling on BP&apos;s fuel advertising from 2 October 2019, G16-1014902, did
              not uphold the complaints.
            </li>
            <li>
              <strong>Glencore:</strong>{' '}the report cited an open investigation by the UK
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
            marked as under revision. All eight reports described the Green Claims
            Directive as enforced from September 2026; it was never adopted. Seven stated
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
