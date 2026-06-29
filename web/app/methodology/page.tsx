export const metadata = {
  title: 'Methodology — Prasine Index',
  description:
    'How Prasine Index scores EU corporate sustainability claims: pipeline architecture, 22 data sources, verdict tiers, and scoring logic.',
}

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
          How Prasine Index assesses EU corporate sustainability claims — pipeline
          architecture, data sources, verdict definitions, and scoring logic.
        </p>

        {/* ── Pipeline ── */}
        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Pipeline architecture</h2>
          <p style={{ color: 'var(--muted)', marginBottom: '1.5rem', lineHeight: 1.7 }}>
            Each assessment runs a 7-agent pipeline. Every agent has a typed Pydantic
            contract at input and output — no unvalidated state crosses a boundary.
          </p>
          <table className="dimension-table" style={{ marginBottom: '1rem' }}>
            <thead>
              <tr><th style={{ width: 32 }}>#</th><th>Agent</th><th>What it does</th></tr>
            </thead>
            <tbody>
              {[
                ['1', 'Discovery', 'Fetches the claim source URL and extracts all sustainability assertions from the page. Filters to substantive environmental claims — ignores boilerplate and navigation copy.'],
                ['2', 'Extraction', 'Structures each claim as a typed record: claim text, category (emissions, target, process, certification, offsetting), and source attribution.'],
                ['3', 'Context', 'Retrieves company-level context: sector, CSRD obligation status, SIC code, prior enforcement history, and known lobbying ratings. Sets the baseline for scoring.'],
                ['4', 'Verification', 'Parallel fan-out across all 22 data sources. Each source returns typed Evidence records with a confidence value and a URL. Uses LangGraph for managed parallelism — the only place a framework is used.'],
                ['5', 'Lobbying', 'Dedicated pass for influence data: LobbyMap rating, EU Transparency Register registration, GOGEL/GOGET extraction presence. Lobbying contradiction is an independent scoring trigger.'],
                ['6', 'Judge', 'Scores each claim 0–100. Confidence-weighted aggregate across all evidence items. Assigns verdict tier. Flags data gaps where regulatory ground truth is absent.'],
                ['7', 'Report', 'Writes the full assessment: evidence chain with citations, dimensional scoring table, key finding, data gaps, methodology note, and trace ID for reproducibility.'],
              ].map(([n, name, desc]) => (
                <tr key={n}>
                  <td style={{ fontFamily: "'Space Mono', monospace", fontSize: 12, color: 'var(--muted)' }}>{n}</td>
                  <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{name}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>
            The pipeline is single-threaded at the assessment level — one company at a time.
            Verification runs all 22 sources in parallel within that run. Claims within a
            company are scored sequentially with shared context.
          </p>
        </section>

        {/* ── Data sources ── */}
        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Data sources</h2>
          <p style={{ color: 'var(--muted)', marginBottom: '1.5rem', lineHeight: 1.7 }}>
            Every evidence item in a Prasine report is drawn from one of these 22 EU open
            data sources. No paywalled databases. No hallucinated citations — every source
            is fetched at run time and the URL is included in the evidence record.
          </p>
          <table className="dimension-table">
            <thead>
              <tr><th>Source</th><th>What it provides</th></tr>
            </thead>
            <tbody>
              {[
                ['EU ETS', 'Verified installation-level CO₂ emissions from the EU Emissions Trading System. Ground truth for industrial emitters obligated under ETS.'],
                ['E-PRTR', 'European Pollutant Release and Transfer Register — facility-level pollution data across EU member states.'],
                ['EDGAR (JRC)', 'EU Joint Research Centre gridded GHG emissions — used where ETS coverage is absent.'],
                ['EEA National Inventories', 'European Environment Agency country-level GHG inventories. Sector-level emissions trends.'],
                ['Eurostat', 'EU statistical office — energy mix, production volumes, and sector emissions aggregates.'],
                ['Climate TRACE', 'Independent satellite-derived emissions estimates. Used to cross-check self-reported figures.'],
                ['SBTi', 'Science Based Targets initiative — whether the company has a validated, approved, or committed net-zero or 1.5°C target.'],
                ['TPI (Transition Pathway Initiative)', 'Independent assessment of company management quality on climate transition. Tracks emissions performance vs. sector benchmarks.'],
                ['CA100+', 'Climate Action 100+ benchmark — net-zero alignment score, disclosure quality, and short-term target setting.'],
                ['CDP', 'Carbon Disclosure Project open dataset — company-disclosed emissions, targets, and climate governance data.'],
                ['LobbyMap', 'InfluenceMap corporate climate lobbying scores. The single strongest independent CONFIRMED trigger: a D or D+ rating demonstrates active obstruction of climate policy.'],
                ['EU Transparency Register', 'Confirms whether the company is a registered EU lobbyist and its declared lobbying expenditure.'],
                ['EUR-Lex', 'EU legislative database — cited when a claim conflicts with current or forthcoming EU law (CSRD, Green Claims Directive, EmpCo Directive, EU Taxonomy).'],
                ['Enforcement rulings', 'National advertising authority and regulatory rulings (ASA UK, Reklamnämnden SE, ACM NL, others). Prior violations are scored as independent evidence.'],
                ['GOGEL', 'Global Oil and Gas Exit List — upstream oil and gas expansion plans. Active expansion contradicts credible net-zero claims.'],
                ['GOGET', 'Global Oil and Gas Extraction Tracker — production volumes and new field approvals.'],
                ['Global Coal Exit List (GCEL)', 'Coal power and mining exposure. Active coal expansion is incompatible with Paris-aligned claims.'],
                ['Global Coal Plant Tracker (GCPT)', 'Plant-level coal capacity in operation and under construction.'],
                ['Europe Gas Tracker (EGT)', 'Gas infrastructure under development — pipelines, LNG terminals, gas plants. New gas locks contradict transition claims.'],
                ['Banking on Climate Chaos', 'Fossil fuel financing by major banks — relevant for financial sector claims and credibility of transition pledges.'],
                ['EU Innovation Fund', 'EU-funded decarbonisation grants. Receipt of transition funding is contextual evidence, not a verdict trigger.'],
                ['Source document', "The claim's own source URL is fetched and analysed — the claim text, its context, and any referenced commitments are extracted directly."],
              ].map(([src, desc]) => (
                <tr key={src}>
                  <td style={{ fontWeight: 600, whiteSpace: 'nowrap', fontSize: 13 }}>{src}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* ── Scoring ── */}
        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Scoring</h2>
          <p style={{ color: 'var(--muted)', marginBottom: '1.5rem', lineHeight: 1.7 }}>
            Each claim receives a score from 0 to 100. Higher scores indicate stronger
            evidence of greenwashing. The score is a confidence-weighted aggregate across
            all evidence items retrieved for that claim.
          </p>

          <table className="dimension-table" style={{ marginBottom: '1.5rem' }}>
            <thead>
              <tr><th>Score</th><th>Verdict</th><th>What it means</th></tr>
            </thead>
            <tbody>
              {[
                ['0 – 20', 'Substantiated', 'Available evidence supports the claim. No significant contradicting data found across the 22 sources. The claim is defensible under current EU standards.'],
                ['21 – 40', 'Unverifiable', 'Insufficient public regulatory data to verify or refute the claim. The claim may be accurate, but cannot be independently confirmed through EU open data.'],
                ['41 – 60', 'Misleading', 'Evidence contradicts the claim, but not conclusively. The claim overstates, omits material context, or uses framing inconsistent with the underlying data.'],
                ['61 – 80', 'Likely greenwashing', 'Strong contradicting evidence from multiple sources. The claim conflicts with regulatory data, lobbying conduct, or target credibility in ways that are difficult to reconcile.'],
                ['81 – 100', 'Confirmed greenwashing', 'Definitive contradicting evidence. One or more confirmed triggers apply (see below). The claim cannot be reconciled with independently verified facts.'],
              ].map(([score, verdict, desc]) => (
                <tr key={score}>
                  <td style={{ fontFamily: "'Space Mono', monospace", fontSize: 12, whiteSpace: 'nowrap' }}>{score}</td>
                  <td style={{ fontWeight: 600, whiteSpace: 'nowrap', fontSize: 13 }}>{verdict}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: '0.75rem', marginTop: '2rem' }}>
            Confirmed triggers
          </h3>
          <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: '1rem', lineHeight: 1.7 }}>
            Any of the following, if confirmed, triggers CONFIRMED status regardless of other evidence:
          </p>
          <table className="dimension-table">
            <thead>
              <tr><th>Trigger</th><th>Logic</th></tr>
            </thead>
            <tbody>
              {[
                ['LobbyMap D or D+', 'An "Obstructive" or "Highly Obstructive" climate lobbying rating means the company actively opposes or delays the climate legislation its own green claims depend on. Internal contradiction at the conduct level.'],
                ['Prior enforcement ruling', 'A national advertising authority or regulatory body has ruled a similar or identical claim from this company misleading. Establishes pattern and prior notice.'],
                ['Active fossil fuel expansion', 'Company has upstream oil, gas, or coal expansion planned or underway (per GOGEL/GOGET/GCEL/GCPT) while making Paris-aligned or net-zero claims. Structural contradiction between capital allocation and stated direction.'],
                ['Offsetting basis', 'Net-zero or carbon-neutral claim relies primarily on carbon offsetting, which is expressly excluded from acceptable net-zero bases under the EmpCo Directive (EU 2024/825) and the EU Taxonomy.'],
                ['No SBTi target + net-zero claim', 'Company claims net-zero alignment with no approved, committed, or validated SBTi target. No credible independent verification pathway exists.'],
                ['Verified emissions gap', 'Independent satellite or regulatory emissions estimates significantly exceed company-disclosed figures, and the discrepancy is material to the claim being assessed.'],
              ].map(([trigger, logic]) => (
                <tr key={trigger}>
                  <td style={{ fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}>{trigger}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{logic}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: '1rem', lineHeight: 1.6 }}>
            Multi-claim assessments produce a confidence-weighted aggregate score across
            all claims. The displayed company-level verdict derives from this aggregate,
            not from any individual claim score.
          </p>
        </section>

        {/* ── What this is and isn't ── */}
        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>What this is and isn't</h2>

          <div className="key-finding" style={{ marginBottom: '1.5rem' }}>
            <p className="key-finding-label">Not a legal determination</p>
            <p style={{ fontSize: 14, lineHeight: 1.7 }}>
              A Prasine Index assessment is an evidence-based research output, not a legal
              opinion. It identifies public data that contradicts a company's stated claims.
              It does not constitute legal advice, and a CONFIRMED verdict does not mean the
              company is in breach of law — it means the evidence record is inconsistent
              with the claim at a level that warrants further scrutiny.
            </p>
          </div>

          <table className="dimension-table">
            <thead>
              <tr><th>Aspect</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {[
                ['Model', 'Reports are generated by a multi-agent pipeline using Claude (Anthropic). The model synthesises and scores evidence — it does not generate or fabricate data. Every source cited in a report was fetched and retrieved at run time.'],
                ['Citations', 'Every evidence item includes a source URL, a confidence value (0.0–1.0), and a supports/contradicts/context classification. Evidence items with no retrievable URL are flagged as unverifiable and do not increase the score.'],
                ['Data gaps', 'Every assessment discloses where regulatory ground truth is absent — when a company is not in a mandatory database, when data is paywalled, or when disclosure is incomplete. Data gaps are listed explicitly, not silently omitted.'],
                ['Trace ID', 'Each report includes a trace ID: a hash of the pipeline run. The same company and claim URL run through the same pipeline version will produce an identical trace ID, confirming reproducibility.'],
                ['Scope', 'Current coverage is limited to environmental (E) claims. Social (S) and governance (G) claims are outside scope. CSRD ESRS E1 (climate change) is the primary lens.'],
                ['Paywalled sources', 'Prasine does not access paywalled databases. Where a relevant source requires registration or payment (GOGEL full dataset, some regulatory portals), this is disclosed in the data gaps section.'],
              ].map(([aspect, detail]) => (
                <tr key={aspect}>
                  <td style={{ fontWeight: 600, whiteSpace: 'nowrap', fontSize: 13 }}>{aspect}</td>
                  <td style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* ── Get in touch ── */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: '2rem', marginTop: '1rem' }}>
          <p style={{ color: 'var(--muted)', fontSize: 14, lineHeight: 1.7 }}>
            Questions about the methodology, a specific scoring decision, or how Prasine
            could support your work?{' '}
            <a href="mailto:cm.blomqvist@gmail.com" style={{ color: 'var(--text)', textDecoration: 'underline' }}>
              Get in touch
            </a>.
          </p>
        </div>

      </main>

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
