import ApplyForm from './apply-form'

export default function HomePage() {
  return (
    <>
      {/* ── Nav ── */}
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo"><span>P</span>rasine Index</div>
          <div className="nav-links">
            <a href="#apply" className="nav-btn">Request an assessment</a>
          </div>
        </div>
      </nav>

      {/* ── Intro ── */}
      <section className="intro">
        <div className="doc-container">
          <p className="intro-text">
            Prasine Index verifies EU corporate sustainability claims against enforcement
            records, regulatory filings, lobbying data, and open climate datasets. Submit
            a company and claim URL. Receive a cited greenwashing assessment report built
            for journalists, NGOs, law firms, and activist investors.
          </p>
          <p className="intro-sub">
            Example output: what a Prasine Index assessment looks like.
          </p>
        </div>
      </section>

      {/* ── Report ── */}
      <section className="report-section">
        <div className="doc-container">

          <div className="report-meta">
            <span className="report-label">Assessment</span>
            <span className="report-date">26 June 2026</span>
          </div>

          <h1 className="report-company">Ryanair Holdings plc</h1>
          <p className="report-details">Ireland · Aviation · CSRD obligated · Assessed 2026-06-26</p>

          {/* ── Aggregate summary ── */}
          <div className="report-verdict-line" style={{ marginTop: '1.5rem' }}>
            <span className="verdict-word confirmed">Confirmed greenwashing</span>
            <span className="verdict-score">83 / 100</span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, marginBottom: '1.25rem' }}>
            Confidence-weighted aggregate across 5 claims · range 80–89
          </p>

          {/* ── Claim overview table ── */}
          <table className="dimension-table" style={{ marginBottom: '1.5rem' }}>
            <thead>
              <tr><th>Score</th><th>Verdict</th><th>Claim assessed</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>84 / 100</td>
                <td><span className="verdict-badge badge-confirmed">Confirmed</span></td>
                <td style={{ fontSize: 12 }}>&ldquo;the ambitious goals we&apos;ve set to reach net-zero carbon emissions by 2050&rdquo;</td>
              </tr>
              <tr style={{ background: 'var(--surface-alt, #f7f7f7)' }}>
                <td><strong>86 / 100</strong></td>
                <td><span className="verdict-badge badge-confirmed">Confirmed</span></td>
                <td style={{ fontSize: 12 }}><strong>&ldquo;We&apos;ve developed a pathway to achieve our net-zero carbon emissions goal by 2050, which aligns with the Paris Agreement&hellip;&rdquo; &mdash; detailed below</strong></td>
              </tr>
              <tr>
                <td>82 / 100</td>
                <td><span className="verdict-badge badge-confirmed">Confirmed</span></td>
                <td style={{ fontSize: 12 }}>&ldquo;Work with suppliers to increase sustainable aviation fuel (SAF) with industry-leading SAF goals &gt;10% by 2030.&rdquo;</td>
              </tr>
              <tr>
                <td>82 / 100</td>
                <td><span className="verdict-badge badge-confirmed">Confirmed</span></td>
                <td style={{ fontSize: 12 }}>&ldquo;By appointing best-in class researchers, we&apos;ll achieve our goal of powering 12.5% of our flights with SAF by 2030.&rdquo;</td>
              </tr>
              <tr>
                <td>82 / 100</td>
                <td><span className="verdict-badge badge-confirmed">Confirmed</span></td>
                <td style={{ fontSize: 12 }}>&ldquo;Our goal is 12.5% SAF usage by 2030.&rdquo;</td>
              </tr>
            </tbody>
          </table>

          {/* ── Claim detail divider ── */}
          <p style={{ fontSize: 12, color: 'var(--muted)', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
            Detailed assessment of claim 2 (highest-scoring) follows.
          </p>

          <div className="report-claim">
            <div className="claim-attr">Claim extracted from corporate.ryanair.com/sustainability/pathway-to-net-zero</div>
            <blockquote>
              &quot;We&apos;ve developed a pathway to achieve our net-zero carbon emissions goal
              by 2050, which aligns with the Paris Agreement and the aviation industry&apos;s
              Destination 2050 initiative.&quot;
            </blockquote>
          </div>

          <div className="report-verdict-line">
            <span className="verdict-word confirmed">Confirmed greenwashing</span>
            <span className="verdict-score">86 / 100</span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>Range 82–90 · Confidence 86% · Trace af429cf9</p>

          <div className="report-body">

            <div className="key-finding">
              <p className="key-finding-label">Key finding</p>
              <p>
                Ryanair holds a D+ obstructive climate-lobbying rating from LobbyMap, meaning it
                actively opposes or delays the climate legislation its own net-zero pledge depends
                on — and its self-published pathway relies on 24% carbon offsetting, a basis
                expressly blacklisted for net-zero claims under the EmpCo Directive (EU 2024/825).
              </p>
            </div>

            <h2>Evidence</h2>

            <p className="ev-group-label">Contradicting evidence</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">1</div>
                <div className="ev-content">
                  <p className="ev-source-name">LobbyMap D+ (Obstructive) + EU Transparency Register</p>
                  <p className="ev-finding">
                    LobbyMap rates Ryanair <strong>D+ (Obstructive)</strong> — actively opposing
                    or delaying climate legislation while making green claims (confidence 0.85).
                    This is corroborated by the EU Transparency Register, which confirms Ryanair
                    is an actively registered direct corporate lobbyist (reg. no. 002977215945-85,
                    HQ Ireland, confidence 0.75). A company obstructing the policy framework its
                    own 2050 pledge depends on cannot reconcile that pledge with its conduct.
                    Under Prasine scoring, a D/D+ LobbyMap rating alone triggers CONFIRMED status.
                  </p>
                  <p className="ev-weight contra">Independent trigger · confidence 0.85</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">2</div>
                <div className="ev-content">
                  <p className="ev-source-name">UK ASA Ruling G20-1089921 (2020)</p>
                  <p className="ev-finding">
                    The Advertising Standards Authority found Ryanair&apos;s &quot;lowest carbon
                    emissions&quot; claim <strong>CONFIRMED MISLEADING</strong> — Ryanair could
                    not substantiate lower CO₂ per passenger than comparable airlines on a
                    like-for-like basis. This establishes a documented prior violation within the
                    same claim category. Under the Prasine framework, a prior ruling against an
                    equivalent claim type independently triggers CONFIRMED status.
                  </p>
                  <p className="ev-weight contra">Independent trigger · confidence 0.90</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">3</div>
                <div className="ev-content">
                  <p className="ev-source-name">Ryanair Self-Disclosure — Pathway to Net Zero (2024)</p>
                  <p className="ev-finding">
                    Ryanair&apos;s own pathway document reveals that 24% of its net-zero plan
                    relies on &ldquo;offsetting and other economic measures&rdquo; — a basis
                    expressly blacklisted under the EmpCo Directive. The document states no
                    explicit baseline year, no 2035/2040 interim targets, no
                    abatement-versus-certified-removal split, and no verified transition plan.
                    It also contradicts itself: prioritises carbon reduction over offsetting
                    while assigning nearly a quarter of the pathway to offsets. The 34% SAF
                    component currently sits at the EU-mandated 2% against a &gt;10% 2030 target.
                  </p>
                  <p className="ev-weight contra">Substantiation failure · confidence 0.95</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">4</div>
                <div className="ev-content">
                  <p className="ev-source-name">European Commission CPC Investigation (2024)</p>
                  <p className="ev-finding">
                    The EC and national consumer protection authorities launched a coordinated
                    investigation under CPC Regulation 2017/2394 into Ryanair&apos;s environmental
                    claims on carbon emissions, offsetting, and sustainability credentials.
                    On 6 November 2025, Ryanair was among 21 airlines that reached a formal
                    settlement with the CPC Network, committing to remove or revise misleading
                    environmental claims. No fine was issued, but the settlement constitutes a
                    concluded regulatory determination.
                  </p>
                  <p className="ev-weight contra">Regulatory settlement · confidence 0.70</p>
                </div>
              </div>
            </div>

            <p className="ev-group-label">Legislative framework</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">5</div>
                <div className="ev-content">
                  <p className="ev-source-name">EmpCo Directive (EU 2024/825) — Blacklisted Claim Type</p>
                  <p className="ev-finding">
                    In force since March 2024, the EmpCo Directive amends UCPD Annex I to require
                    that net-zero claims demonstrate: a baseline emissions year, interim targets,
                    a split between abatement and certified permanent removal, and a verified
                    transition plan. Claims based on carbon offsetting are expressly blacklisted.
                    Ryanair&apos;s pathway fails every requirement. EUR-Lex CELEX:32024L0825.
                  </p>
                  <p className="ev-weight legislative">Substantiation failure · confidence 0.95</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">6</div>
                <div className="ev-content">
                  <p className="ev-source-name">CSRD (EU 2022/2464) — Mandatory Emissions Disclosure</p>
                  <p className="ev-finding">
                    CSRD requires mandatory disclosure of scope 1, 2, and 3 GHG emissions under
                    ESRS E1 from FY2024. A net-zero claim that cannot be cross-referenced against
                    a CSRD-compliant baseline constitutes a material substantiation gap. EUR-Lex
                    CELEX:32022L2464.
                  </p>
                  <p className="ev-weight legislative">Data gap · confidence 0.95</p>
                </div>
              </div>
            </div>

            <p className="ev-group-label">Mitigating evidence</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">7</div>
                <div className="ev-content">
                  <p className="ev-source-name">SBTi — Interim Targets Set (net-zero: none) · TPI — Below 2°C</p>
                  <p className="ev-finding">
                    SBTi records interim reduction targets classified as 1.5°C but{' '}
                    <em>net-zero target: none</em> — neutral for the assessed net-zero commitment
                    (confidence 0.70). TPI rates the 2050 pathway &ldquo;Below 2 Degrees&rdquo;
                    at Management Quality Level 2 (Acknowledging) — Paris-compatible but not
                    1.5°C-aligned and weak on governance (confidence 0.75). Neither displaces the
                    three independent confirmed triggers.
                  </p>
                  <p className="ev-weight support">Partial mitigation — insufficient to rebut · confidence 0.70–0.75</p>
                </div>
              </div>
            </div>

            <h2>Assessment</h2>
            <div className="report-reasoning">
              <p>
                The decisive finding is the contradiction between Ryanair&apos;s net-zero pledge
                and its own lobbying conduct. LobbyMap classifies Ryanair D+ (Obstructive) —
                actively opposing the climate legislation required to deliver any net-zero pathway.
                A company obstructing the policy framework its 2050 pledge depends on cannot
                reconcile that pledge with its conduct. Under Prasine scoring, this alone confirms
                greenwashing. The EU Transparency Register confirms this engagement is
                operationalised at the institutional level.
              </p>
              <p>
                Two further independent triggers reinforce the verdict. The ASA found an equivalent
                prior emissions claim CONFIRMED MISLEADING (G20-1089921, 2020), establishing a
                documented pattern. Ryanair&apos;s own pathway document then fails the EmpCo
                Directive on every substantiation requirement: no baseline year, no 2035/2040
                interim targets, no abatement-versus-certified-removal split, and 24% reliance on
                offsetting — expressly blacklisted. The self-published pathway is internally
                inconsistent and materially behind its own 2030 SAF trajectory.
              </p>
              <p>
                Mitigating evidence (SBTi interim targets, TPI Below 2°C rating) is genuine but
                cannot override three independent confirmed triggers. These signals place the score
                in the lower-to-mid confirmed band (82–90) rather than higher. The November 2025
                CPC settlement — Ryanair among 21 airlines that committed to revise misleading
                environmental claims — adds a concluded regulatory determination on top of the
                existing finding.
              </p>
            </div>

            <h2>Dimensional scoring</h2>
            <p className="dimension-note">Higher score = stronger greenwashing evidence. Claim 2 of 5.</p>
            <table className="dimension-table">
              <thead>
                <tr><th>Dimension</th><th>Score</th></tr>
              </thead>
              <tbody>
                <tr><td>Substantiation failure</td><td>90 / 100</td></tr>
                <tr><td>Lobbying contradiction</td><td>88 / 100</td></tr>
                <tr><td>Prior violations</td><td>85 / 100</td></tr>
                <tr><td>Target credibility gap</td><td>82 / 100</td></tr>
                <tr><td>Emissions discrepancy</td><td>55 / 100</td></tr>
              </tbody>
            </table>

            <h2>Data gaps</h2>
            <table className="data-gaps-table">
              <thead>
                <tr><th>Source</th><th>Status</th><th>Impact</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>EU ETS Verified Emissions (EUTL)</td>
                  <td>Not registered</td>
                  <td>Aviation emissions reported through a separate scheme. Scope 1 absolute emissions could not be independently verified. Does not affect the lobbying, prior-violation, or substantiation triggers — each independently sufficient.</td>
                </tr>
                <tr>
                  <td>Scope 1, 2 and 3 absolute emissions</td>
                  <td>Not in source document</td>
                  <td>No verified baseline provided in the pathway document, preventing cross-check against CSRD-mandated disclosure.</td>
                </tr>
                <tr>
                  <td>SBTi net-zero validation</td>
                  <td>Status: none</td>
                  <td>No validated net-zero target exists to corroborate the assessed claim. Neutral — absence of validation does not itself trigger a score increase, but removes a potential mitigant.</td>
                </tr>
              </tbody>
            </table>

            <h2>Sources</h2>
            <ol className="sources-list">
              <li>LobbyMap — Corporate Climate Policy Engagement Score, accessed 2026-06-26. https://lobbymap.org/</li>
              <li>EU Transparency Register — Ryanair Holdings plc (reg. 002977215945-85), accessed 2026-06-26</li>
              <li>UK ASA Ruling G20-1089921 — Ryanair DAC, 2020-02-05. https://www.asa.org.uk/rulings/ryanair-dac-g20-1089921-ryanair-dac.html</li>
              <li>Ryanair — Pathway to Net Zero, corporate.ryanair.com/sustainability/pathway-to-net-zero, retrieved 2026-06-26</li>
              <li>European Commission / CPC Network — Coordinated Action on Airline Environmental Claims, 2024–2025</li>
              <li>Directive (EU) 2024/825 (EmpCo) — EUR-Lex CELEX:32024L0825</li>
              <li>Directive (EU) 2022/2464 (CSRD) — EUR-Lex CELEX:32022L2464</li>
              <li>Science Based Targets initiative — Companies Taking Action, accessed 2026-06-26</li>
              <li>Transition Pathway Initiative — Corporates, accessed 2026-06-26</li>
            </ol>
          </div>

        </div>
      </section>

      {/* ── Index ── */}
      <section id="index" className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">The Index</h2>
          <p className="index-sub">
            6 EU companies assessed across 5 sectors. Evidence drawn from 22 open data sources per run.
          </p>
          <div className="index-stats">
            <span className="index-stat"><strong>3</strong> confirmed</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>1</strong> likely greenwashing</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>1</strong> misleading claim</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>1</strong> substantiated claim</span>
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
              {[
                { company: 'BP plc',               slug: 'bp-plc',               sector: 'Oil & Gas', score: 87, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'Glencore plc',         slug: 'glencore-plc',         sector: 'Mining',    score: 83, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'Ryanair Holdings plc', slug: 'ryanair-holdings-plc', sector: 'Aviation',  score: 83, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'Enel SpA',             slug: 'enel-spa',             sector: 'Energy',    score: 58, label: 'Likely greenwashing', badge: 'greenwashing' },
                { company: 'IKEA Group',           slug: 'ikea-group',           sector: 'Retail',    score: 43, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'H&M Group',            slug: 'h-m-group',            sector: 'Fashion',   score: 20, label: 'Substantiated claim', badge: 'substantiated'},
              ].map(({ company, slug, sector, score, label, badge }) => (
                <tr key={company}>
                  <td colSpan={4} style={{ padding: 0, border: 'none' }}>
                    <a
                      href={`/reports/${slug}`}
                      style={{ display: 'table', width: '100%', tableLayout: 'fixed', textDecoration: 'none', color: 'inherit', cursor: 'pointer' }}
                    >
                      <span style={{ display: 'table-cell', padding: '10px 12px', fontWeight: 500 }}>{company}</span>
                      <span style={{ display: 'table-cell', padding: '10px 12px', color: 'var(--muted)', fontFamily: "'Space Mono', monospace", fontSize: 12 }}>{sector}</span>
                      <span style={{ display: 'table-cell', padding: '10px 12px', fontFamily: "'Space Mono', monospace", fontWeight: 700 }}>{score}</span>
                      <span style={{ display: 'table-cell', padding: '10px 12px' }}><span className={`verdict-badge badge-${badge}`}>{label}</span></span>
                    </a>
                  </td>
                </tr>
              ))}
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
              Data Scientist / AI Engineer · Sweden
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
