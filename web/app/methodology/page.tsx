import { PUBLISHED_ON, openGraphFor } from '../../lib/site'

export const metadata = {
  title: 'Methodology | Prasine Index',
  description:
    'How Prasine Index checks climate claims against public records: the sources, the scoring rules, the integrity criteria for climate pledges, the company record and the limits.',
  alternates: { canonical: '/methodology' },
  openGraph: openGraphFor(
    'Methodology | Prasine Index',
    'How Prasine Index checks climate claims against public records: the sources, the scoring rules, the integrity criteria for climate pledges, the company record and the limits.',
    '/methodology',
  ),
}

const BANDS: [string, string, string][] = [
  ['0–20', 'Supported by records', 'Records about the claim support it, and nothing material contradicts it.'],
  ['21–40', 'Not covered by public records', 'The records needed to check the claim are not available.'],
  ['41–60', 'Not fully supported', 'The claim lacks the specifics needed to check it, leaves out material context, or only company-wide records cut against it.'],
  ['61–80', 'Conflicts with records', "A record about the claim's own subject, scope and period contradicts it."],
  ['81–100', 'Contradicted by records', 'An official record (EU ETS, E-PRTR or the SBTi register) covering the same quantity, scope and period shows the claim to be false.'],
]

const SOURCES: [string, string][] = [
  ['Official records', 'EU Emissions Trading System verified emissions, the E-PRTR pollutant register, the SBTi target register.'],
  ['Independent estimates', 'Climate TRACE estimates of the emissions of individual installations, which count as records about a claim.'],
  ['Enforcement records', 'Decisions by advertising regulators, consumer authorities, courts and the European Commission on environmental marketing, each checked twice against its official page, in two separate passes made with language-model agents, and quoted verbatim.'],
  ['Company conduct and assessments', 'LobbyMap, the EU Transparency Register, the Global Oil and Gas Exit List, the Global Coal Exit List, the Global Energy Monitor oil and gas, coal plant and gas infrastructure trackers, Banking on Climate Chaos, Climate Action 100+, TPI and CDP.'],
  ['Context', 'EU law from EUR-Lex: the provisions of the Unfair Commercial Practices Directive as amended by Directive (EU) 2024/825, quoted with the date it applies from and its scope, and short summaries of the CSRD and the EU ETS Directive; national totals from the EEA national inventories, Eurostat, EDGAR and Climate TRACE, which appear in a report only when the score relies on them; the EU Innovation Fund.'],
  ["The company's own material", 'The page or document the claim comes from, and up to two reports the page links to, such as the newest sustainability report and a transition plan, read for baseline, scope, targets, plan and verification.'],
]

export default function MethodologyPage() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <a href="/"><span>P</span>rasine Index</a>
          </div>
          <div className="nav-links">
            <a href="/methodology" className="nav-link" style={{ color: 'var(--text)' }}>Methodology</a>
            <a href="/about" className="nav-link">About</a>
            <a href="/#apply" className="nav-btn">Request an assessment</a>
          </div>
        </div>
      </nav>

      <main className="doc-container" style={{ padding: '48px 24px 96px' }}>
        <div className="report-meta">
          <span className="report-label">Documentation</span>
        </div>
        <h1 className="report-company" style={{ marginBottom: '0.5rem' }}>Methodology</h1>
        <p style={{ color: 'var(--muted)', fontSize: 15, marginBottom: '3rem', lineHeight: 1.6 }}>
          How Prasine Index checks a company&apos;s climate claims: what it reads, how a claim is
          scored, what the findings mean, and what the scores cannot tell you. This page
          describes version 2 of the method, used for the assessments published on{' '}
          {PUBLISHED_ON}.
        </p>

        <div className="report-body">
          <h2>What an assessment covers</h2>
          <p>
            An assessment starts from a company&apos;s sustainability page or report. The
            pipeline reads it and up to 20 relevant pages it links to. It ranks the climate
            claims it finds by type, with net-zero and carbon-neutrality claims first, and by how
            specific they are. Up to seven are assessed, at most two of each type. Twenty-one
            open data sources and the company&apos;s own document are read for every claim. Many
            of the sources return no record for a given company. Two of them, CDP and the EU
            Innovation Fund, have no data file in this version, so no report carries a record
            from them. Each report lists the gaps that bear on its claim. The manifest file saved
            with each report in the repository lists a shortened SHA-256 fingerprint of each
            dataset file the assessment was run on.
          </p>

          <table className="dimension-table text-table" style={{ margin: '1.25rem 0' }}>
            <thead>
              <tr><th>Records</th><th>Sources</th></tr>
            </thead>
            <tbody>
              {SOURCES.map(([group, sources]) => (
                <tr key={group}>
                  <td style={{ fontWeight: 600, fontSize: 13 }}>{group}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{sources}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>How a claim is scored</h2>
          <p>
            A language model reads the claim and the records and gives a score from 0 to 100: how
            far the records go against the claim. It also states which records contradict the
            claim and which support it. Fixed rules in code then decide which band the score may
            reach. Each claim score comes with a range and a confidence. The range runs from the
            lowest to the highest score the model finds plausible for the claim. The confidence is
            the model&apos;s own estimate of how sure its reading is.
          </p>

          <table className="dimension-table text-table" style={{ margin: '1.25rem 0' }}>
            <thead>
              <tr><th>Score</th><th>Finding</th><th>What it takes</th></tr>
            </thead>
            <tbody>
              {BANDS.map(([score, finding, takes]) => (
                <tr key={score}>
                  <td style={{ fontFamily: 'var(--font-mono), ui-monospace, monospace', fontSize: 12, whiteSpace: 'nowrap' }}>{score}</td>
                  <td style={{ fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}>{finding}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{takes}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p>
            A score above 60 requires a record that concerns the claim. A score above 80 requires
            an official record that shows the claim to be false. A company-wide rating, list or
            decision does not meet those requirements on its own, except for the climate pledges
            and the decisions on the same claim described below. If the records the model cites
            against the claim do not meet them, the code lowers the score to 60 or 80.
          </p>

          <h2>Climate pledges</h2>
          <p>
            A claim is a pledge when its central statement is a commitment or an alignment of the
            whole company: net zero by a given year, carbon neutrality, alignment with the Paris
            Agreement or 1.5°C. A net-zero aim that covers only some emission scopes, such as
            Scope 1 and 2, is still a pledge, and the scopes it leaves out are weighed against
            it. Support for a goal, such as the goals of the Paris Agreement, is not a pledge.
            For a pledge, Prasine applies two of the integrity criteria that
            the UN High-Level Expert Group on the Net Zero Emissions Commitments of Non-State
            Entities sets out
            (<a href="https://www.un.org/sites/un2.un.org/files/high-levelexpertgroupupdate7.pdf" target="_blank" rel="noopener">Integrity Matters</a>, 2022, p. 7):
          </p>
          <blockquote style={{ borderLeft: '3px solid var(--border-2)', paddingLeft: 20, margin: '1rem 0', fontStyle: 'italic' }}>
            <p>
              &ldquo;Non-state actors cannot claim to be net zero while continuing to build or
              invest in new fossil fuel supply.&rdquo;
            </p>
            <p>
              &ldquo;Non-state actors cannot lobby to undermine ambitious government climate
              policies either directly or through trade associations or other bodies.&rdquo;
            </p>
          </blockquote>
          <p>
            For a pledge, records of new fossil fuel supply and of lobbying count as evidence
            against the claim, and investors&apos; assessments of the pledge count for it or
            against it. Such records can place the pledge in the 61–80 band, and never above it.
            Lobbying counts against a pledge when the company&apos;s LobbyMap band is D or lower,
            the range LobbyMap defines as obstructive. A statement of fact that mentions a pledge,
            such as a target validation or a fuel purchase, is checked against the records about
            that fact. For such a statement, the records of supply, lobbying and investor
            assessments are context.
          </p>
          <p>
            New fossil fuel supply means new or expanded oil and gas fields and coal mines, along
            with LNG terminals and gas pipelines that are planned or under construction. New coal
            plants also count, because the expert group&apos;s recommendations for businesses
            include ending coal plants by 2030 in OECD countries and by 2040 elsewhere (Integrity
            Matters, p. 24). New gas-fired power plants are context: they do not supply fossil
            fuel, and those recommendations do not name them. A field discovered more than ten
            years ago with no investment decision recorded is context as well. So is an LNG
            terminal that the Europe Gas Tracker still lists as proposed more than ten years
            after its proposal year, together with any LNG capacity on the Global Oil and Gas
            Exit List that matches it.
          </p>

          <h2>Enforcement records</h2>
          <p>
            Each enforcement record was checked twice against the official page of the authority
            or body that made the decision, in two separate passes made with language-model
            agents, and carries a verbatim quotation from it. A decision
            from the last five years that found the same claim misleading is evidence about the
            claim, and it can place the claim in the 61–80 band. A decision on materially
            identical wording counts in the same way. Decisions about other claims, commitments,
            warnings, open cases and decisions annulled on appeal are context. A complaint that
            was not upheld counts in the company&apos;s favour on the claim it concerned.
          </p>

          <h2>The company record</h2>
          <p>
            Each company assessment sets a company record beside the claims: lobbying, new fossil
            fuel supply, verified emissions, targets, investor assessments and enforcement
            records. Each is stated as its source states it, and the record says what they show
            on the two integrity criteria above. The company record is built in code from the
            records and checked before publication. In some reports the review added context to
            it. It carries no score.
          </p>

          <h2>The company score</h2>
          <p>
            The company score is the confidence-weighted mean of the company&apos;s three
            highest-scoring claims. Claims that state the same pledge, such as net zero by the
            same year for the same emissions, count once, through the highest-scoring of them.
            When two claims tie for third place, the one the model is more confident in enters the
            mean. The score never falls below the lower bound of the band its highest-scoring
            claim is in, so milder claims cannot pull it below that band. When the score is
            raised to that bound, the report says so and gives the mean as well. The
            company&apos;s range is the weighted mean of the model&apos;s low and high estimates,
            and it is not raised with the score. A company&apos;s finding is the band its score
            falls in. For a company, the finding &ldquo;Not covered by public records&rdquo;
            means that the public records available do not cover its highest-scoring claim.
          </p>

          <h2>Limits</h2>
          <ul>
            <li>
              A score describes how the records relate to a claim. It is not a legal finding, and
              no finding states that a company has broken any law.
            </li>
            <li>
              A model&apos;s reading can vary between runs. The claims that decide the bands of BP,
              Glencore and H&amp;M were each scored three more times on the same records.
              BP&apos;s two claims, published at 64 and 66, scored 65, 65 and 66, and 67, 67 and
              66; Glencore&apos;s, published at 64, scored 66, 67 and 65. Each stayed in its band.
              H&amp;M&apos;s claim, published at 20, scored 18, 20 and 22; at 22 the company score
              would be raised to 21, in the next band. The claims by Ryanair and Enel that were
              scored again on corrected records were scored four times: Ryanair&apos;s at 58, 62,
              62 and 58, and Enel&apos;s at 24, 42, 42 and 43. Before the runs, the first run was
              set as the claim&apos;s score, and it is the one published; in both cases it lies in
              the lower band. Where the runs of a claim that decides a company&apos;s band fall in
              two bands, the index publishes the lower band, and the report gives the runs. The claims that decide the bands of IKEA, SSAB
              and &Oslash;rsted were not tested. Small differences between companies should not
              be read as a ranking.
            </li>
            <li>
              Records describe the past and cover what their sources cover. A gap in a source is
              not a fact about the company.
            </li>
            <li>
              Directive (EU) 2024/825 applies from 27 September 2026 and only to commercial
              practices aimed at consumers. Whether a page assessed here is such a practice is
              for national authorities and courts to decide.
            </li>
          </ul>

          <h2>Models and code</h2>
          <p>
            Claude Opus 5.5 scores the claims, Claude Sonnet 5.5 writes the reports and Claude
            Haiku 5.5 extracts the claims and reads the source documents. In the reports, the
            model that scores a claim is called the judge. Code generates the evidence list and
            the company record in each report from the records. Before publication each report
            was reviewed against its records and sources, in passes made with language-model
            agents; errors found in the text were corrected, and context was added to some
            company records. The judge scored the claims on the records as first
            written, except two claims, by Ryanair and Enel, that were scored again on corrected
            records because the errors bore on their scores. One claim by Enel is not counted,
            for the reason given in its report. The code is open source
            on{' '}
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>.
          </p>
        </div>
      </main>

      <footer>
        <div className="footer-inner">
          <div>
            <span>Prasine Index · Martin Blomqvist, 2026</span>
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="/about">About</a>
            <a href="/corrections">Corrections</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
