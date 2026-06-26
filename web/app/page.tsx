import ApplyForm from './apply-form'

export default function HomePage() {
  return (
    <>
      {/* ── Nav ── */}
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo"><span>P</span>rasine Index</div>
          <div className="nav-links">
            <a href="#apply" className="nav-btn">Apply for early access</a>
          </div>
        </div>
      </nav>

      {/* ── Intro ── */}
      <section className="intro">
        <div className="doc-container">
          <p className="intro-text">
            Prasine Index verifies EU corporate sustainability claims against enforcement
            records, regulatory filings, and open climate data. The output is a
            fully-cited evidence chain, structured for ESG analysts, compliance teams, and regulators.
          </p>
          <p className="intro-sub">
            Below is a complete assessment. This is what you get.
          </p>
        </div>
      </section>

      {/* ── Report ── */}
      <section className="report-section">
        <div className="doc-container">

          <div className="report-meta">
            <span className="report-label">Assessment</span>
            <span className="report-date">24 June 2026</span>
          </div>

          <h1 className="report-company">Ryanair Holdings plc</h1>
          <p className="report-details">Ireland · Aviation · CSRD obligated · Assessed 2026-06-24</p>

          <div className="report-claim">
            <div className="claim-attr">Claim extracted from corporate.ryanair.com/sustainability/</div>
            <blockquote>
              "Within our Sustainability Report 2025, learn more about the ambitious goals
              we&apos;ve set to reach net-zero carbon emissions by 2050."
            </blockquote>
          </div>

          <div className="report-verdict-line">
            <span className="verdict-word confirmed">Confirmed greenwashing</span>
            <span className="verdict-score">86 / 100</span>
          </div>

          <div className="report-body">

            <div className="key-finding">
              <p className="key-finding-label">Key finding</p>
              <p>
                Ryanair&apos;s net-zero by 2050 pledge is contradicted by its own LobbyMap D+
                (Obstructive) climate-lobbying classification, while a 2020 ASA ruling already
                found an equivalent Ryanair emissions claim misleading and unsubstantiated —
                making this net-zero claim confirmed greenwashing irrespective of its supporting
                benchmarks.
              </p>
            </div>

            <h2>Evidence</h2>

            <p className="ev-group-label">Contradicting evidence</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">1</div>
                <div className="ev-content">
                  <p className="ev-source-name">UK ASA Ruling A20-529462 (2020)</p>
                  <p className="ev-finding">
                    The Advertising Standards Authority ruled Ryanair&apos;s &quot;lowest carbon
                    emissions&quot; claim CONFIRMED MISLEADING — Ryanair could not substantiate
                    lower CO₂ per passenger than comparable airlines on a like-for-like basis.
                    This establishes a documented pattern: Ryanair&apos;s environmental claims
                    have failed regulatory scrutiny before. Under the Prasine framework, a prior
                    ruling against an equivalent claim type independently triggers CONFIRMED status.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.90</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">2</div>
                <div className="ev-content">
                  <p className="ev-source-name">LobbyMap — D+ Climate Policy Engagement Score</p>
                  <p className="ev-finding">
                    Ryanair holds a <strong>D+ (Obstructive)</strong> rating: the company actively
                    opposes or delays climate legislation while making green claims. A net-zero 2050
                    pledge made simultaneously with active lobbying against the regulatory framework
                    required to achieve it is an irreconcilable contradiction. Active obstruction
                    independently triggers CONFIRMED status under the Prasine framework.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.85</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">3</div>
                <div className="ev-content">
                  <p className="ev-source-name">European Commission CPC Investigation (2024)</p>
                  <p className="ev-finding">
                    The European Commission and national consumer protection authorities launched a
                    coordinated investigation into Ryanair&apos;s environmental claims on carbon
                    emissions, offsetting, and sustainability credentials under CPC Regulation
                    2017/2394. Ryanair is a named target alongside Air France, KLM, and Lufthansa.
                    The investigation confirms regulators identified a credible basis for concern.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.70</p>
                </div>
              </div>
            </div>

            <p className="ev-group-label">Supporting evidence</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">4</div>
                <div className="ev-content">
                  <p className="ev-source-name">Science Based Targets initiative — Interim Reduction Targets</p>
                  <p className="ev-finding">
                    SBTi records show Ryanair has interim reduction targets classified as 1.5°C,
                    but explicitly notes <em>net-zero target: none</em>. SBTi validates interim
                    targets only and does not validate a net-zero 2050 claim. These targets are
                    neutral with respect to the assessed commitment and do not mitigate the
                    contradicting evidence.
                  </p>
                  <p className="ev-weight support">Partial support · confidence 0.70</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">5</div>
                <div className="ev-content">
                  <p className="ev-source-name">Transition Pathway Initiative — Below 2°C (2050)</p>
                  <p className="ev-finding">
                    TPI rates Ryanair&apos;s 2050 decarbonisation pathway as &quot;Below 2
                    Degrees,&quot; which is Paris-compatible. TPI distinguishes between &quot;Below
                    2°C&quot; and &quot;Net-Zero Aligned&quot;; Ryanair does not achieve the latter.
                    This is supportive of climate action but does not validate the specific
                    net-zero claim under assessment.
                  </p>
                  <p className="ev-weight support">Partial support · confidence 0.75</p>
                </div>
              </div>
            </div>

            <p className="ev-group-label">Legislative framework</p>
            <div className="evidence-doc">
              <div className="ev-entry">
                <div className="ev-number">6</div>
                <div className="ev-content">
                  <p className="ev-source-name">EmpCo Directive (EU 2024/825) — Substantiation Failure</p>
                  <p className="ev-finding">
                    In force since March 2024, the EmpCo Directive amends UCPD Annex I to require
                    that net-zero claims demonstrate: a baseline emissions year, interim targets at
                    2030/2035/2040, a breakdown of abatement versus certified carbon removal, and
                    a verified transition plan. The assessed claim discloses none of these.
                    Generic net-zero pledges without substantiation are explicitly blacklisted as
                    unfair commercial practices.
                  </p>
                  <p className="ev-weight legislative">Substantiation failure · confidence 0.95</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">7</div>
                <div className="ev-content">
                  <p className="ev-source-name">Corporate Sustainability Reporting Directive (2022/2464)</p>
                  <p className="ev-finding">
                    CSRD requires large companies to disclose scope 1, 2, and 3 GHG emissions under
                    ESRS E1 from FY2024. A net-zero claim that contradicts mandatory CSRD disclosure
                    constitutes a material inconsistency. No CSRD-compliant emissions baseline for
                    Ryanair could be cross-referenced against the claimed 2050 pathway at assessment
                    date — FY2024 disclosures are not yet published.
                  </p>
                  <p className="ev-weight legislative">Data gap — re-assess on CSRD publication · confidence 0.95</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">8</div>
                <div className="ev-content">
                  <p className="ev-source-name">EU Transparency Register — Active Lobbying Registration</p>
                  <p className="ev-finding">
                    Ryanair Holdings plc is registered as an active EU lobbyist (registration
                    no. 002977215945-85, HQ: Ireland), confirming direct corporate lobbying
                    engagement with EU institutions. Direction and substance of lobbying are not
                    disclosed by the register; cross-reference with LobbyMap (source 3) confirms
                    obstructive climate policy engagement.
                  </p>
                  <p className="ev-weight legislative">Corroborates source 3 · confidence 0.75</p>
                </div>
              </div>
            </div>

            <h2>Assessment</h2>
            <div className="report-reasoning">
              <p>
                The claim satisfies three independent confirmation thresholds, each of which
                alone is sufficient to trigger CONFIRMED_GREENWASHING status under the Prasine
                framework on two independent grounds: (1) LobbyMap D+ (Obstructive) — actively
                opposing climate legislation while pledging net-zero is an irreconcilable
                contradiction that alone triggers confirmed status; (2) the 2020 ASA ruling
                (A20-529462) found an equivalent Ryanair emissions claim misleading and
                unsubstantiated, establishing a documented pattern that alone triggers confirmed
                status. The claim additionally fails substantiation under the EmpCo Directive
                (2024/825): no baseline year, no interim checkpoints, no abatement/removal split,
                no verified carbon removal plan.
              </p>
              <p>
                Partial mitigating evidence exists — SBTi interim 1.5°C targets (confidence 0.70)
                and TPI &quot;Below 2 Degrees&quot; benchmark (confidence 0.75) — but neither
                validates a net-zero 2050 commitment and neither can override a confirmed trigger.
                The EC CPC investigation (confidence 0.70) is ongoing; a binding ruling would
                push the score higher.
              </p>
            </div>

            <h2>Dimensional scoring</h2>
            <p className="dimension-note">Higher score = stronger greenwashing evidence</p>
            <table className="dimension-table">
              <thead>
                <tr><th>Dimension</th><th>Score</th></tr>
              </thead>
              <tbody>
                <tr><td>Lobbying contradiction</td><td>88 / 100</td></tr>
                <tr><td>Prior violations</td><td>85 / 100</td></tr>
                <tr><td>Substantiation failure</td><td>80 / 100</td></tr>
                <tr><td>Target credibility gap</td><td>75 / 100</td></tr>
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
                  <td>EU ETS Verified Emissions</td>
                  <td>Not registered</td>
                  <td>No baseline trajectory. Confidence not reduced — ASA ruling and LobbyMap D+ provide independent evidence.</td>
                </tr>
                <tr>
                  <td>CSRD FY2025 Sustainability Report</td>
                  <td>Analysed (Sep 2025)</td>
                  <td>Report discloses net-zero pathway: 32% tech, 34% SAF, 10% Single European Sky, 24% offsetting. No certified removal plan. Baseline year implicit only. Multiple EmpCo gaps confirmed — deepens the finding.</td>
                </tr>
                <tr>
                  <td>LobbyMap itemised activities</td>
                  <td>Score only</td>
                  <td>D+ classification sufficient; itemised list would only deepen the finding.</td>
                </tr>
                <tr>
                  <td>EC CPC Investigation outcome</td>
                  <td>Settled — Nov 2025</td>
                  <td>Ryanair among 21 airlines that committed to EU CPC Network on 6 Nov 2025 to remove or revise misleading environmental claims. No fine issued, but a concluded regulatory commitment. Strengthens the finding — regulators confirmed the claims were misleading.</td>
                </tr>
              </tbody>
            </table>

            <h2>Sources</h2>
            <ol className="sources-list">
              <li>UK ASA Ruling A20-529462 — Ryanair Holdings Ltd, 2020-09-16</li>
              <li>LobbyMap — Corporate Climate Policy Engagement Score, accessed 2026-06-24</li>
              <li>European Commission CPC Network — Coordinated Action on Airline Environmental Claims, 2024</li>
              <li>Science Based Targets initiative — Companies Taking Action, accessed 2026-06-24</li>
              <li>Transition Pathway Initiative — Corporates, 2022</li>
              <li>Directive (EU) 2024/825 (EmpCo) amending UCPD 2005/29/EC and CRD 2011/83/EU, Annex I</li>
              <li>Directive (EU) 2022/2464 (CSRD)</li>
              <li>EU Transparency Register — Ryanair Holdings plc, accessed 2026-06-24</li>
            </ol>
          </div>

        </div>
      </section>

      {/* ── Index ── */}
      <section className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">The Index</h2>
          <p className="index-sub">
            18 EU companies assessed across 6 sectors. Evidence drawn from 22 open data sources per run.
          </p>
          <div className="index-stats">
            <span className="index-stat"><strong>4</strong> confirmed</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>3</strong> likely greenwashing</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>6</strong> misleading claim</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>5</strong> unverifiable claim</span>
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
                { company: 'Glencore plc',             sector: 'Mining',      score: 87, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'Ryanair Holdings plc',     sector: 'Aviation',    score: 86, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'Eni SpA',                  sector: 'Oil & Gas',   score: 85, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'BP plc',                   sector: 'Oil & Gas',   score: 82, label: 'Confirmed',          badge: 'confirmed'    },
                { company: 'KLM Royal Dutch Airlines', sector: 'Aviation',    score: 78, label: 'Likely greenwashing', badge: 'greenwashing' },
                { company: 'TotalEnergies SE',         sector: 'Oil & Gas',   score: 75, label: 'Likely greenwashing', badge: 'greenwashing' },
                { company: 'Enel SpA',                 sector: 'Energy',      score: 68, label: 'Likely greenwashing', badge: 'greenwashing' },
                { company: 'RWE AG',                   sector: 'Energy',      score: 58, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'Wizz Air Holdings plc',    sector: 'Aviation',    score: 56, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'LKAB',                     sector: 'Steel',       score: 52, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'H&M Group',                sector: 'Fashion',     score: 48, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'Öresundskraft',            sector: 'Energy',      score: 48, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'Stegra',                   sector: 'Steel',       score: 48, label: 'Misleading claim',    badge: 'misleading'   },
                { company: 'SSAB AB',                  sector: 'Steel',       score: 42, label: 'Unverifiable claim',  badge: 'insufficient' },
                { company: 'Danone SA',                sector: 'Food',        score: 35, label: 'Unverifiable claim',  badge: 'insufficient' },
                { company: 'Ørsted A/S',               sector: 'Renewables',  score: 32, label: 'Unverifiable claim',  badge: 'insufficient' },
                { company: 'Securitas AB',             sector: 'Services',    score: 28, label: 'Unverifiable claim',  badge: 'insufficient' },
                { company: 'IKEA Group',               sector: 'Retail',      score: 22, label: 'Unverifiable claim',  badge: 'insufficient' },
              ].map(({ company, sector, score, label, badge }) => (
                <tr key={company}>
                  <td style={{ fontWeight: 500 }}>{company}</td>
                  <td style={{ color: 'var(--muted)', fontFamily: "'Space Mono', monospace", fontSize: 12 }}>{sector}</td>
                  <td style={{ fontFamily: "'Space Mono', monospace", fontWeight: 700 }}>{score}</td>
                  <td><span className={`verdict-badge badge-${badge}`}>{label}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="index-note">
            Full evidence chains and scoring breakdowns available on request.
          </p>
        </div>
      </section>

      {/* ── Apply ── */}
      <section id="apply" className="apply-section">
        <div className="doc-container">
          <h2>Apply for early access</h2>
          <p className="apply-sub">
            I&apos;m working with a small number of early clients — ESG analysts, compliance
            teams, and journalists. If this is useful to your work, get in touch.
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
