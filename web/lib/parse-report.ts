import { readFileSync, existsSync } from 'fs'
import { join } from 'path'

export interface EvidenceItem {
  num: number
  source: string
  body: string
  supports: 'Yes' | 'No' | 'N/A' | string
  confidence: number
  url?: string
}

export interface ClaimRow {
  num: number
  score: number
  verdict: string
  text: string
}

export interface ParsedReport {
  company: string
  claimCount: number
  overallScore: number
  scoreRange: string
  verdict: string
  confidence: number
  claims: ClaimRow[]
  detailVerdict: string
  detailScore: number
  detailRange: string
  detailConfidence: number
  publishDate: string
  traceId: string
  claim: string
  claimSource: string
  evidence: EvidenceItem[]
  assessmentParas: string[]
  keyFinding: string
  dataGaps: string[]
}

export interface ReportSummary {
  slug: string
  company: string
  sector: string
  score: number
  verdict: string
  claimCount: number
}

export function verdictFromScore(score: number): { cls: string; label: string } {
  if (score <= 20) return { cls: 'substantiated', label: 'Substantiated claim' }
  if (score <= 40) return { cls: 'insufficient',  label: 'Unverifiable claim'  }
  if (score <= 60) return { cls: 'misleading',    label: 'Misleading claim'    }
  if (score <= 80) return { cls: 'greenwashing',  label: 'Likely greenwashing' }
  return             { cls: 'confirmed',    label: 'Confirmed greenwashing' }
}

const ENUM_LABELS: Record<string, string> = {
  SOURCE_DOCUMENT:          'source document',
  LOBBY_MAP:                'LobbyMap',
  EUR_LEX:                  'EUR-Lex',
  EU_TRANSPARENCY_REGISTER: 'EU Transparency Register',
  ENFORCEMENT_RULING:       'enforcement ruling',
  ENFORCEMENT:              'enforcement record',
  EMISSIONS_DISCREPANCY:    'emissions discrepancy',
  LOBBYING_RECORD:          'lobbying record',
  LEGISLATIVE_RECORD:       'legislative record',
  IR_PAGE:                  'investor relations page',
  EU_ETS:                   'EU ETS',
  SBTI:                     'SBTi',
  EPRTR:                    'E-PRTR',
  CA100:                    'CA100+',
  FOSSIL_FINANCE:           'Fossil Finance Tracker',
  COAL_EXIT:                'Global Coal Exit List',
  EU_INNOVATION_FUND:       'EU Innovation Fund',
  TPI:                      'TPI',
  GCPT:                     'GCPT',
  EGT:                      'EGT',
  GOGEL:                    'GOGEL',
  EDGAR:                    'EDGAR/JRC',
  CONFIRMED_GREENWASHING:   'confirmed greenwashing',
  MISLEADING_CLAIM:         'misleading claim',
  UNVERIFIABLE_CLAIM:       'unverifiable claim',
  SUBSTANTIATED_CLAIM:      'substantiated claim',
  LIKELY_GREENWASHING:      'likely greenwashing',
}

function humanizeText(text: string): string {
  return text.replace(/\b([A-Z][A-Z]*_[A-Z][A-Z_]*)\b/g, (m) =>
    ENUM_LABELS[m] ?? m.toLowerCase().replace(/_/g, ' ')
  )
}

function extractUrl(text: string): string | undefined {
  return text.match(/(https?:\/\/[^\s*),\]]+)/)?.[1]
}

function extractConf(text: string): number {
  const m =
    text.match(/\(confidence ([\d.]+)\)/) ??
    text.match(/confidence ([\d.]+)/i) ??
    text.match(/Confidence: ([\d.]+)/)
  return m ? parseFloat(m[1]) : 0
}

function normaliseSupports(raw: string): 'Yes' | 'No' | 'N/A' {
  const s = raw.toLowerCase().trim()
  if (s === 'yes') return 'Yes'
  if (s === 'no') return 'No'
  return 'N/A'
}

function parseNumberedEvidence(section: string): EvidenceItem[] {
  return section
    .split(/\n\n(?=\*\*\[\d+\])/)
    .filter(c => /^\*\*\[\d+\]/.test(c.trim()))
    .map(chunk => {
      const hm = chunk.match(/^\*\*\[(\d+)\] ([^*]+)\*\* ([\s\S]+)$/)
      if (!hm) return null
      const num = parseInt(hm[1])
      const source = hm[2].trim().replace(/\.$/, '')
      let body = hm[3].trim()
      const url = extractUrl(body)
      const conf = extractConf(body)
      const supRaw = body.match(/Supports claim:\s*(\w+)/i)?.[1] ?? 'N/A'
      const supports = normaliseSupports(supRaw)
      body = body
        .replace(/\*Source:[^*]+\*/g, '')
        .replace(/Supports claim:[^.]+\./gi, '')
        .replace(/\(confidence[\d\s.]+\)/gi, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/\s{2,}/g, ' ')
        .trim()
      return { num, source, body, supports, confidence: conf, url }
    })
    .filter((e): e is NonNullable<typeof e> => e !== null)
}

function parseBulletEvidence(section: string): EvidenceItem[] {
  const items: EvidenceItem[] = []
  let num = 1
  let currentSupports: 'Yes' | 'No' | 'N/A' = 'N/A'
  for (const line of section.split('\n')) {
    const heading = line.match(/^\*\*(Contradicting|Supporting|Regulatory|Context)/i)
    if (heading) {
      const h = heading[1].toLowerCase()
      currentSupports = h === 'contradicting' ? 'No' : h === 'supporting' ? 'Yes' : 'N/A'
      continue
    }
    if (!line.startsWith('- ')) continue
    let body = line.slice(2).trim()
    const url = extractUrl(body)
    const conf = extractConf(body)
    const srcMatch =
      body.match(/\*([^*]+https?:\/\/[^\s*]+)\*$/) ??
      body.match(/\*([^*,]+),\s*[^,*]+,\s*https?:\/\/[^\s*]+\*$/)
    const source = srcMatch
      ? srcMatch[1].replace(/https?:\/\/\S+/, '').replace(/,\s*$/, '').trim()
      : 'Source'
    body = body
      .replace(/\*[^*]+\*$/g, '')
      .replace(/https?:\/\/\S+/g, '')
      .replace(/\(confidence[\d\s.]+\)/gi, '')
      .replace(/\s{2,}/g, ' ')
      .trim()
    items.push({ num: num++, source, body, supports: currentSupports, confidence: conf, url })
  }
  return items
}

function parseParagraphEvidence(section: string): EvidenceItem[] {
  return section
    .split(/\n\n/)
    .filter(p => /^\*\*[^[*]/.test(p.trim()))
    .map((p, i) => {
      const srcMatch = p.match(/^\*\*([^*]+)\*\*/)
      const source = srcMatch?.[1]?.replace(/\.$/, '').trim() ?? 'Source'
      let body = p.replace(/^\*\*[^*]+\*\*/, '').trim()
      const url = extractUrl(body)
      const conf = extractConf(body)
      const supRaw = body.match(/Supports claim:\s*(\w+)/i)?.[1]
      const supports: 'Yes' | 'No' | 'N/A' = supRaw ? normaliseSupports(supRaw) : 'N/A'
      body = body
        .replace(/^[—–-]\s*/, '')
        .replace(/\([^)]*https?:\/\/[^)]*\)/g, '')
        .replace(/\*[^*]+\*/g, '')
        .replace(/Supports claim:[^.]+\./gi, '')
        .replace(/\s*Source:\s*[A-Z][A-Z_]+\b[^]*$/g, '')
        .replace(/\(confidence[\d\s.]+\)/gi, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/\s{2,}/g, ' ')
        .trim()
      return { num: i + 1, source, body, supports, confidence: conf, url }
    })
}

function parseEvidence(section: string): EvidenceItem[] {
  if (/\*\*\[\d+\]/.test(section))                       return parseNumberedEvidence(section)
  if (/\*\*Contradicting|\*\*Supporting/i.test(section)) return parseBulletEvidence(section)
  return parseParagraphEvidence(section)
}

export function parseReport(md: string): ParsedReport {
  const headerMatch = md.match(/^## (.+?) — Company Assessment \((\d+) claim/m)
  const company = headerMatch?.[1] ?? 'Unknown Company'
  const claimCount = parseInt(headerMatch?.[2] ?? '1')

  const overallScore = parseInt(md.match(/\*\*Overall Score: (\d+)\/100\*\*/)?.[1] ?? '0')
  const scoreRange = md.match(/\*\*Score range:\*\* ([^\n]+)/)?.[1]?.trim() ?? ''
  const verdict = md.match(/\*\*Verdict:\*\* ([^\n*]+)/)?.[1]?.trim() ?? ''
  const confidence = parseInt(md.match(/\*\*Confidence:\*\* (\d+)%/)?.[1] ?? '0')

  const claims: ClaimRow[] = md
    .split('\n')
    .filter(l => /^\| \d+/.test(l))
    .map(l => {
      const cells = l.split('|').map(c => c.trim()).filter(Boolean)
      return {
        num: parseInt(cells[0]),
        score: parseInt(cells[1]),
        verdict: cells[2],
        text: cells[3] ?? '',
      }
    })

  const detailHeader = md.match(
    /\*\*Verdict: ([^*]+)\*\* \| Score: ([\d.]+)\/100 \(range: ([^)]+)\) \| Confidence: (\d+)%/,
  )
  const detailVerdict = detailHeader?.[1]?.trim() ?? verdict
  const detailScore = parseFloat(detailHeader?.[2] ?? String(overallScore))
  const detailRange = detailHeader?.[3]?.trim() ?? scoreRange
  const detailConfidence = parseInt(detailHeader?.[4] ?? String(confidence))

  const publishMatch = md.match(
    /\*Published: ([^|]+) \| Prasine Index \| Trace ID: ([^*\n]+)\*/,
  )
  const publishDate = publishMatch?.[1]?.trim() ?? ''
  const traceId = publishMatch?.[2]?.trim() ?? ''

  const claimMatch = md.match(/> "([^"]+)"/)
  const claim = claimMatch?.[1] ?? ''
  const claimSource = humanizeText(md.match(/\*Source: ([^\n*]+)\*/)?.[1]?.trim() ?? '')

  const evStart = md.indexOf('### Evidence')
  const evEnd = md.indexOf('### Assessment')
  const evSection = evStart > -1 && evEnd > -1 ? md.slice(evStart, evEnd) : ''
  const evidence = parseEvidence(evSection)

  const assStart = md.indexOf('### Assessment')
  const kfStart = md.indexOf('### Key Finding')
  const assessmentParas =
    assStart > -1 && kfStart > -1
      ? md
          .slice(assStart + '### Assessment\n'.length, kfStart)
          .split(/\n\n+/)
          .map(p => humanizeText(p.trim()))
          .filter(p => p.length > 0 && !p.startsWith('#') && !/^-{3,}$/.test(p))
      : []

  const dgStart = md.indexOf('### Data Gaps')
  const keyFinding =
    kfStart > -1
      ? humanizeText(
          md
            .slice(kfStart + '### Key Finding\n'.length, dgStart > -1 ? dgStart : undefined)
            .split(/\n\n+/)
            .map(p => p.trim())
            .filter(p => p.length > 0 && !p.startsWith('#') && !/^-{3,}$/.test(p))
            .join(' ')
        )
      : ''

  const methStart = md.indexOf('### Methodology')
  const dataGapsRaw =
    dgStart > -1
      ? md.slice(dgStart + '### Data Gaps\n'.length, methStart > -1 ? methStart : undefined)
      : ''
  const dataGaps = dataGapsRaw
    .split('\n')
    .filter(l => l.startsWith('**') || l.startsWith('- ') || /^\*\*/.test(l))
    .filter(l => l.trim().length > 0)
    .map(l => l.replace(/^- /, '').trim())

  return {
    company, claimCount, overallScore, scoreRange, verdict, confidence, claims,
    detailVerdict, detailScore, detailRange, detailConfidence,
    publishDate, traceId, claim, claimSource,
    evidence, assessmentParas, keyFinding, dataGaps,
  }
}

const SECTOR_MAP: Record<string, string> = {
  'ryanair-holdings-plc': 'Aviation',
  'bp-plc':               'Oil & Gas',
  'glencore-plc':         'Mining',
  'enel-spa':             'Energy',
  'ikea-group':           'Retail',
  'h-m-group':            'Fashion',
}

export function loadReportSummaries(slugs: string[]): ReportSummary[] {
  return slugs.flatMap(slug => {
    const p = join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)
    if (!existsSync(p)) return []
    const md = readFileSync(p, 'utf-8')
    const r = parseReport(md)
    return [{
      slug,
      company: r.company,
      sector: SECTOR_MAP[slug] ?? '',
      score: r.overallScore,
      verdict: r.verdict,
      claimCount: r.claimCount,
    }]
  })
}
