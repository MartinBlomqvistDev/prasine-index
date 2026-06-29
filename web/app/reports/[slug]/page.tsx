import { marked } from 'marked'
import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { notFound } from 'next/navigation'

// All canonical report slugs — for static prerendering
export function generateStaticParams() {
  return [
    { slug: 'ryanair-holdings-plc' },
    { slug: 'glencore-plc' },
    { slug: 'eni-spa' },
    { slug: 'bp-plc' },
    { slug: 'klm-royal-dutch-airlines' },
    { slug: 'totalenergies-se' },
    { slug: 'enel-spa' },
    { slug: 'rwe-ag' },
    { slug: 'wizz-air-holdings-plc' },
    { slug: 'lkab' },
    { slug: 'h-m-group' },
    { slug: 'oresundskraft' },
    { slug: 'stegra' },
    { slug: 'ssab-ab' },
    { slug: 'danone-sa' },
    { slug: 'orsted-a-s' },
    { slug: 'securitas-ab' },
    { slug: 'ikea-group' },
  ]
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  return {
    title: `${slug.replace(/-/g, ' ')} — Prasine Index`,
    description: 'EU greenwashing assessment report by Prasine Index',
  }
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params

  // Reports live two levels above web/
  const reportPath = join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)

  if (!existsSync(reportPath)) {
    notFound()
  }

  const markdown = readFileSync(reportPath, 'utf-8')
  const html = await marked(markdown, { async: false })

  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <a href="/"><span>P</span>rasine Index</a>
          </div>
          <div className="nav-links">
            <a href="/#index" className="nav-link">All companies</a>
            <a href="/#apply" className="nav-btn">Request an assessment</a>
          </div>
        </div>
      </nav>

      <main className="doc-container" style={{ padding: '48px 24px 80px' }}>
        <div
          className="report-markdown"
          dangerouslySetInnerHTML={{ __html: html as string }}
        />
      </main>

      <footer>
        <div className="footer-inner">
          <span>© 2026 Prasine Index</span>
          <div style={{ display: 'flex', gap: 20 }}>
            <a href="https://github.com/MartinBlomqvistDev/prasine-index" target="_blank" rel="noopener">GitHub</a>
            <a href="mailto:cm.blomqvist@gmail.com">Contact</a>
          </div>
        </div>
      </footer>
    </>
  )
}
