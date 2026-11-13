import {
  assessedDates,
  findingFromString,
  loadPublishedReports,
  loadReportSummaries,
} from '../../lib/parse-report'
import {
  AWAITING_REASSESSMENT,
  PUBLISHED_ON,
  openGraphFor,
  PUBLISHED_SLUGS,
  VERSION_1_SCORES,
  WITHDRAWN_ON,
  WITHDRAWN_REASONS,
} from '../../lib/site'

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

export const metadata = {
  title: 'Corrections | Prasine Index',
  description: 'Corrections to assessments published on Prasine Index.',
  alternates: { canonical: '/corrections' },
  openGraph: openGraphFor(
    'Corrections | Prasine Index',
    'Corrections to assessments published on Prasine Index.',
    '/corrections',
  ),
}

export default function CorrectionsPage() {
  const summaries = loadReportSummaries(PUBLISHED_SLUGS).sort((a, b) =>
    a.company.localeCompare(b.company, 'en'),
  )
  const awaiting = Object.entries(AWAITING_REASSESSMENT)
  const count = NUMBER_WORDS[summaries.length] ?? String(summaries.length)
  // The date of the assessments is read from the reports, as on the home page.
  const assessedText = assessedDates(loadPublishedReports(PUBLISHED_SLUGS, AWAITING_REASSESSMENT))
  // The companies whose version 1 assessments were withdrawn and that are back in the index,
  // by the first word of their names ("Ryanair", "Glencore", "BP").
  const returned = Object.entries(WITHDRAWN_REASONS)
    .filter(([slug]) => PUBLISHED_SLUGS.includes(slug) && !(slug in AWAITING_REASSESSMENT))
    .map(([, w]) => w.company.split(' ')[0])
  const returnedText =
    returned.length > 1
      ? `${returned.slice(0, -1).join(', ')} and ${returned[returned.length - 1]}`
      : returned.join('')

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
            <a href="/#apply" className="nav-btn">Request an assessment</a>
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
          <h2 id="version-2">
            {PUBLISHED_ON}: {awaiting.length ? `${count} assessments` : `all ${count} assessments`}{' '}
            republished
          </h2>
          <p>
            {awaiting.length
              ? `${count.charAt(0).toUpperCase()}${count.slice(1)} assessments have`
              : `The ${count} assessments have`}{' '}
            been replaced by new ones made with version 2 of the method, described on the{' '}
            <a href="/methodology">methodology page</a>.
            {returned.length > 0 &&
              ` ${returnedText}, withdrawn on ${WITHDRAWN_ON}, are back in the index.`}
            {awaiting.length > 0 &&
              ` The version 1 assessments of ${awaiting.map(([, c]) => c).join(' and ')} have been taken down until they are assessed again with version 2.`}{' '}
            The main changes:
          </p>
          <ul>
            <li>
              Enforcement records were rebuilt from the official pages of the authorities and
              bodies that made the decisions. Each was checked twice against its official page,
              in two separate passes made with language-model agents, and carries a verbatim
              quotation.
            </li>
            <li>
              A score above 60 now requires a record about the claim itself, and a score above
              80 an official record that shows the claim to be false. In version 1, a single
              company-wide rating could place every claim from a company in the top band.
            </li>
            <li>
              For a climate pledge, records of new fossil fuel supply and of lobbying count as
              evidence about it, following two of the integrity criteria of the UN High-Level
              Expert Group on net-zero commitments. So do investors&apos; assessments of the
              pledge.
            </li>
            <li>A pledge stated in more than one claim counts once in the company score.</li>
            <li>
              Findings are named for what the records show, from &ldquo;Supported by
              records&rdquo; to &ldquo;Contradicted by records&rdquo;.
            </li>
            <li>Each assessment includes a company record set beside the claims.</li>
            <li>
              Each report quotes the provisions of the Unfair Commercial Practices Directive, as
              amended by Directive (EU) 2024/825, that bear on its claim, gives the date the
              directive applies from and its scope, and quotes the Commission&apos;s questions and
              answers on whether sustainability reports fall within it. No report states that a
              claim breaks a law.
            </li>
            <li>
              The claims were collected again, for most companies from other pages or reports
              than in version 1.
            </li>
            <li>Claude Opus 5.5 scores the claims; version 1 used Claude Opus 4.8.</li>
          </ul>
          <p>
            The version 2 scores rest on new rules and, for most of the companies, on claims taken
            from a different page or report. A change between the two columns reflects both.
          </p>
          <p>
            One claim in the Enel assessment is not counted: it dates zero emissions to 2024,
            which Prasine reads as a misprint for 2040. Counted, it would have set Enel&apos;s
            score at 61, &ldquo;Conflicts with records&rdquo;. The report says so under its table
            of claims.
          </p>
          <table className="dimension-table text-table" style={{ margin: '1.25rem 0' }}>
            <thead>
              <tr><th>Company</th><th>Version 1, July 2026</th><th>Version 2, {assessedText}</th></tr>
            </thead>
            <tbody>
              {summaries.map(({ company, slug, score, verdict }) => (
                <tr key={slug}>
                  <td>{company}</td>
                  <td>
                    {WITHDRAWN_REASONS[slug] ? 'withdrawn' : (VERSION_1_SCORES[slug] ?? 'not assessed')}
                  </td>
                  <td>
                    <a href={`/reports/${slug}`}>{score}, {findingFromString(verdict).label}</a>
                  </td>
                </tr>
              ))}
              {awaiting.map(([slug, company]) => (
                <tr key={slug}>
                  <td>{company}</td>
                  <td>{WITHDRAWN_REASONS[slug] ? 'withdrawn' : (VERSION_1_SCORES[slug] ?? 'not assessed')}</td>
                  <td>taken down, to be assessed again</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 id="prototypes">{PUBLISHED_ON}: prototype scores of June 2026</h2>
          <p>
            Until 29 June 2026, prasineindex.com and the project&apos;s GitHub Pages page listed
            prototype scores for 18 companies, most of them from a single claim, with labels that
            called claims greenwashing or misleading. Several rested on enforcement records that
            were wrong, among them those for Eni, KLM and TotalEnergies. None of those labels
            stands. The prototype reports were removed from the repository on {PUBLISHED_ON} and
            remain in its history.
          </p>

          <h2 id="notice">{WITHDRAWN_ON}: three assessments withdrawn</h2>
          <p>
            This is the notice as published on {WITHDRAWN_ON}. The corrected assessments were published
            on {PUBLISHED_ON}, in the <a href="#version-2">version 2 entry</a> above.
          </p>
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
