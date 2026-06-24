import Link from 'next/link'

export default function RequestPage() {
  return (
    <div className="dash-layout">
      <aside className="dash-sidebar">
        <div className="dash-logo"><span>P</span>rasine Index</div>
        <Link href="/dashboard" className="dash-nav-item">Assessments</Link>
        <Link href="/dashboard/request" className="dash-nav-item active">Request new</Link>
      </aside>

      <main className="dash-main">
        <div className="dash-header">
          <h1>Request an assessment</h1>
          <p>Turnaround: 48 hours. You&apos;ll receive the full report via email and in your dashboard.</p>
        </div>

        <form
          style={{ maxWidth: 520 }}
          action="https://formspree.io/f/placeholder"
          method="POST"
        >
          <div className="form-row">
            <label className="form-label" htmlFor="company-url">Company URL or name</label>
            <input className="form-input" type="text" id="company-url" name="company_url" required placeholder="https://www.company.com/sustainability/" />
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="claim">Specific claim to assess (optional)</label>
            <textarea className="form-textarea" id="claim" name="claim" placeholder='e.g. "Net zero by 2040"' />
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="use-case">Use case</label>
            <select className="form-select" id="use-case" name="use_case">
              <option value="">Select</option>
              <option value="portfolio-screening">Portfolio screening</option>
              <option value="compliance-review">Compliance review</option>
              <option value="litigation-support">Litigation support</option>
              <option value="journalism">Journalism / investigation</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="notes">Additional context</label>
            <textarea className="form-textarea" id="notes" name="notes" rows={3} />
          </div>
          <button type="submit" className="form-submit">Submit</button>
        </form>
      </main>
    </div>
  )
}
