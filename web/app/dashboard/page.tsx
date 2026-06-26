import Link from 'next/link'

const SAMPLE_ASSESSMENTS = [
  { id: 'ryanair-holdings-plc', company: 'Ryanair Holdings plc', sector: 'Aviation', score: 79, verdict: 'Greenwashing', date: '2026-05-11', status: 'complete' },
  { id: 'klm-royal-dutch-airlines', company: 'KLM Royal Dutch Airlines', sector: 'Aviation', score: 78, verdict: 'Greenwashing', date: '2026-05-11', status: 'complete' },
  { id: 'bp-plc', company: 'BP plc', sector: 'Oil & Gas', score: 78, verdict: 'Greenwashing', date: '2026-05-11', status: 'complete' },
  { id: 'rwe-ag', company: 'RWE AG', sector: 'Energy', score: 42, verdict: 'Insufficient evidence', date: '2026-05-11', status: 'complete' },
]

const verdictClass: Record<string, string> = {
  'Greenwashing': 'badge-greenwashing',
  'Confirmed greenwashing': 'badge-confirmed',
  'Misleading': 'badge-misleading',
  'Substantiated': 'badge-substantiated',
  'Insufficient evidence': 'badge-insufficient',
}

export default function DashboardPage() {
  return (
    <div className="dash-layout">
      <aside className="dash-sidebar">
        <div className="dash-logo"><span>P</span>rasine Index</div>
        <Link href="/dashboard" className="dash-nav-item active">Assessments</Link>
        <Link href="/dashboard/request" className="dash-nav-item">Request new</Link>
        <Link href="/" className="dash-nav-item" style={{ marginTop: 'auto', position: 'absolute', bottom: 24 }}>← Public site</Link>
      </aside>

      <main className="dash-main">
        <div className="dash-header">
          <h1>Assessments</h1>
          <p><Link href="/dashboard/request">Request a new assessment →</Link></p>
        </div>

        <table className="assessments-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Sector</th>
              <th>Score</th>
              <th>Verdict</th>
              <th>Date</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ASSESSMENTS.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link href={`/dashboard/reports/${a.id}`} style={{ fontWeight: 600 }}>
                    {a.company}
                  </Link>
                </td>
                <td style={{ color: 'var(--muted)', fontSize: 12 }}>{a.sector}</td>
                <td style={{ fontWeight: 700, fontFamily: 'monospace' }}>{a.score}/100</td>
                <td>
                  <span className={`verdict-badge ${verdictClass[a.verdict] ?? ''}`}>
                    {a.verdict}
                  </span>
                </td>
                <td style={{ color: 'var(--muted)', fontSize: 12, fontFamily: 'monospace' }}>{a.date}</td>
                <td>
                  <span className={`status-badge status-${a.status}`}>{a.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </main>
    </div>
  )
}
