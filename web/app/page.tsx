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
            fully-cited evidence chain — the kind you can put in front of a regulator or a court.
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
            <span className="report-date">11 May 2026</span>
          </div>

          <h1 className="report-company">Ryanair Holdings plc</h1>
          <p className="report-details">Ireland · Aviation · CSRD obligated · Assessed 2026-05-11</p>

          <div className="report-claim">
            <div className="claim-attr">Claim extracted from corporate.ryanair.com/sustainability/</div>
            <blockquote>
              "Within our Sustainability Report 2025, learn more about the ambitious goals
              we&apos;ve set to reach net-zero carbon emissions by 2050."
            </blockquote>
          </div>

          <div className="report-verdict-line">
            <span className="verdict-word greenwashing">Greenwashing</span>
            <span className="verdict-score">79 / 100</span>
          </div>

          <div className="report-body">
            <h2>Evidence</h2>

            <div className="evidence-doc">

              <div className="ev-entry">
                <div className="ev-number">1</div>
                <div className="ev-content">
                  <p className="ev-source-name">LobbyMap — Corporate Climate Lobbying Score</p>
                  <p className="ev-finding">
                    Ryanair holds a <strong>D+ (Obstructive)</strong> rating on LobbyMap, indicating
                    active opposition to climate legislation. A company publicly committing to
                    net-zero by 2050 while simultaneously lobbying against the regulatory
                    framework required to achieve it represents the clearest form of greenwashing
                    in the Prasine scoring model.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.85</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">2</div>
                <div className="ev-content">
                  <p className="ev-source-name">UK ASA Ruling A20-529462 (2020)</p>
                  <p className="ev-finding">
                    The Advertising Standards Authority found Ryanair&apos;s prior
                    &quot;lowest carbon emissions&quot; claim unsubstantiated. The ruling
                    establishes a documented pattern: Ryanair has made emissions claims
                    that failed regulatory scrutiny before. This history is material to
                    assessing the credibility of the current net-zero commitment.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.90</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">3</div>
                <div className="ev-content">
                  <p className="ev-source-name">European Commission CPC Investigation (2024)</p>
                  <p className="ev-finding">
                    The EC launched a coordinated investigation into Ryanair&apos;s
                    environmental claims as part of a broader sweep of airline industry
                    sustainability marketing. The investigation targets carbon emissions
                    framing, offsetting claims, and sustainability credentials — the
                    exact category of claim under assessment here.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.80</p>
                </div>
              </div>

              <div className="ev-entry">
                <div className="ev-number">4</div>
                <div className="ev-content">
                  <p className="ev-source-name">EmpCo Directive (EU 2024/825) — Substantiation Failure</p>
                  <p className="ev-finding">
                    Under the amended UCPD Annex I, a net-zero claim must disclose: a
                    baseline emissions year, interim targets at recognised checkpoints
                    (2030, 2035, 2040), a breakdown of abatement versus removal, and a
                    verified transition plan. The assessed claim discloses none of these.
                    Generic net-zero commitments without substantiation are explicitly
                    blacklisted under this directive.
                  </p>
                  <p className="ev-weight contra">Contradicts claim · confidence 0.95</p>
                </div>
              </div>

            </div>

            <h2>Reasoning</h2>
            <div className="report-reasoning">
              <p>
                Four independent signals contradict the claim, with no supporting evidence
                retrieved from any of the 21 data sources queried. The D+ LobbyMap rating
                is the primary driver: the gap between a public net-zero pledge and active
                obstruction of climate legislation is not ambiguous. The prior ASA ruling
                establishes pattern. The EC investigation establishes current regulatory
                exposure. The EmpCo substantiation failure means the claim is not merely
                unverified — it is, as written, illegal under EU law effective 2026.
              </p>
              <p>
                Score: 79/100. The assessment lands in the GREENWASHING band (61–80)
                rather than CONFIRMED (81–100) because no binding EU court ruling has yet
                found this specific claim unlawful. That may change as the CPC investigation
                concludes.
              </p>
            </div>

            <h2>Sources</h2>
            <ol className="sources-list">
              <li>LobbyMap, InfluenceMap — Corporate Climate Lobbying Score, accessed 2026-05-11</li>
              <li>UK ASA Ruling A20-529462 — Ryanair Holdings Ltd, 2020-09-16</li>
              <li>European Commission CPC Network — Coordinated Action on Airline Environmental Claims, 2024</li>
              <li>Directive (EU) 2024/825 (EmpCo) amending UCPD 2005/29/EC and CRD 2011/83/EU, Annex I</li>
              <li>EU Transparency Register — Ryanair Holdings plc, accessed 2026-05-11</li>
            </ol>
          </div>

        </div>
      </section>

      {/* ── Index ── */}
      <section className="index-section">
        <div className="doc-container">
          <h2 className="index-heading">The Index</h2>
          <p className="index-sub">
            18 EU companies assessed across 6 sectors. Evidence drawn from 21 open data sources per run.
          </p>
          <div className="index-stats">
            <span className="index-stat"><strong>4</strong> confirmed</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>3</strong> greenwashing</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>6</strong> misleading</span>
            <span className="index-stat-sep">·</span>
            <span className="index-stat"><strong>5</strong> insufficient evidence</span>
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
                { company: 'Glencore plc',             sector: 'Mining',      score: 87, label: 'Confirmed',             badge: 'confirmed'    },
                { company: 'Eni SpA',                  sector: 'Oil & Gas',   score: 85, label: 'Confirmed',             badge: 'confirmed'    },
                { company: 'BP plc',                   sector: 'Oil & Gas',   score: 82, label: 'Confirmed',             badge: 'confirmed'    },
                { company: 'Ryanair Holdings plc',     sector: 'Aviation',    score: 82, label: 'Confirmed',             badge: 'confirmed'    },
                { company: 'KLM Royal Dutch Airlines', sector: 'Aviation',    score: 78, label: 'Greenwashing',          badge: 'greenwashing' },
                { company: 'TotalEnergies SE',         sector: 'Oil & Gas',   score: 75, label: 'Greenwashing',          badge: 'greenwashing' },
                { company: 'Enel SpA',                 sector: 'Energy',      score: 68, label: 'Greenwashing',          badge: 'greenwashing' },
                { company: 'RWE AG',                   sector: 'Energy',      score: 58, label: 'Misleading',            badge: 'misleading'   },
                { company: 'Wizz Air Holdings plc',    sector: 'Aviation',    score: 56, label: 'Misleading',            badge: 'misleading'   },
                { company: 'LKAB',                     sector: 'Steel',       score: 52, label: 'Misleading',            badge: 'misleading'   },
                { company: 'H&M Group',                sector: 'Fashion',     score: 48, label: 'Misleading',            badge: 'misleading'   },
                { company: 'Öresundskraft',            sector: 'Energy',      score: 48, label: 'Misleading',            badge: 'misleading'   },
                { company: 'Stegra',                   sector: 'Steel',       score: 48, label: 'Misleading',            badge: 'misleading'   },
                { company: 'SSAB AB',                  sector: 'Steel',       score: 42, label: 'Insufficient evidence', badge: 'insufficient' },
                { company: 'Danone SA',                sector: 'Food',        score: 35, label: 'Insufficient evidence', badge: 'insufficient' },
                { company: 'Ørsted A/S',               sector: 'Renewables',  score: 32, label: 'Insufficient evidence', badge: 'insufficient' },
                { company: 'Securitas AB',             sector: 'Services',    score: 28, label: 'Insufficient evidence', badge: 'insufficient' },
                { company: 'IKEA Group',               sector: 'Retail',      score: 22, label: 'Insufficient evidence', badge: 'insufficient' },
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
          <span>Prasine Index — Martin Blomqvist, 2026</span>
          <div style={{ display: 'flex', gap: 24 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
