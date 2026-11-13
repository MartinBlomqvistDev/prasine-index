import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { UNCOUNTED_CLAIMS } from './site'

export interface EvidenceItem {
  num: number
  source: string
  body: string
  supports: 'Yes' | 'No' | 'N/A' | string
  confidence: number
  // The record's own URL: the last one on its line.
  url?: string
  // Every distinct URL the record holds, in order: the documents its text cites, then its own.
  urls: string[]
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
  floorApplied: boolean
  // The confidence-weighted mean the score was raised from; null when it was not raised
  // or the report does not state it.
  meanScore: number | null
  pledgeOnce: boolean
  // The claims that enter the mean: fewer than claimCount when a pledge counts once.
  competing: number
  verdict: string
  confidence: number
  claims: ClaimRow[]
  // The paragraphs directly under the claims table, such as the reason a claim is not counted.
  claimsNotes: string[]
  // Claims assessed but left out of the table and the score, each stated in a note under
  // the table that starts "A seventh claim, ... is left out of this table and of the score".
  uncounted: number
  // The ordinal of each such claim ("seventh" is 7), checked against the table at build time.
  uncountedOrdinals: number[]
  detailVerdict: string
  detailScore: number
  detailRange: string
  detailConfidence: number
  detailParsed: boolean
  publishDate: string
  traceId: string
  claim: string
  claimSource: string
  evidence: EvidenceItem[]
  assessmentParas: Block[]
  companyContext: Block[]
  companyRecord: { paras: string[]; items: string[] }
  regulatoryContext: Block[]
  keyFinding: string
  dataGaps: string[]
}

/** An item of a list in a report section, with the items nested under it. */
export interface ListItem {
  text: string
  children: ListItem[]
}

/** A paragraph or a list of a report section, in the order the report gives them. */
export type Block = { kind: 'p'; text: string } | { kind: 'ul'; items: ListItem[] }

export interface ReportSummary {
  slug: string
  company: string
  sector: string
  score: number
  verdict: string
  claimCount: number
}

// The five findings, one per score band. Reports written before November 2026
// carry the band's enum name instead of the label, so both are accepted.
const FINDINGS = [
  // The class names describe the band; the enum names are only read from old reports.
  { band: 'SUBSTANTIATED_CLAIM',    cls: 'supported',     label: 'Supported by records'       },
  { band: 'UNVERIFIABLE_CLAIM',     cls: 'unverified',    label: 'Not covered by public records' },
  { band: 'MISLEADING_CLAIM',       cls: 'partial',       label: 'Not fully supported'        },
  { band: 'LIKELY_GREENWASHING',    cls: 'conflicts',     label: 'Conflicts with records'     },
  { band: 'CONFIRMED_GREENWASHING', cls: 'contradicted',  label: 'Contradicted by records'    },
]

export function verdictFromScore(score: number): { cls: string; label: string } {
  if (score <= 20) return FINDINGS[0]
  if (score <= 40) return FINDINGS[1]
  if (score <= 60) return FINDINGS[2]
  if (score <= 80) return FINDINGS[3]
  return FINDINGS[4]
}

// Labels used before November 2026, read from older reports.
const FORMER_LABELS: Record<string, string> = {
  'NOT INDEPENDENTLY VERIFIED': 'UNVERIFIABLE_CLAIM',
  'NOT CHECKED AGAINST PUBLIC RECORDS': 'UNVERIFIABLE_CLAIM',
}

export function findingFromString(value: string): { cls: string; label: string } {
  const v = FORMER_LABELS[value.trim().toUpperCase()] ?? value.trim().toUpperCase()
  return (
    FINDINGS.find(f => v.includes(f.band) || v === f.label.toUpperCase()) ??
    { cls: 'unverified', label: value.trim() }
  )
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
  // The five band names, written as the findings of version 2.
  ...Object.fromEntries(FINDINGS.map(f => [f.band, f.label])),
}

function humanizeText(text: string): string {
  return text.replace(/\b([A-Z][A-Z]*_[A-Z][A-Z_]*)\b/g, (m) =>
    ENUM_LABELS[m] ?? m.toLowerCase().replace(/_/g, ' ')
  )
}

function extractUrl(text: string): string | undefined {
  return text.match(/(https?:\/\/[^\s*),\]]+)/)?.[1]
}

// In a numbered record the record's own URL is the last one on its line; a link the text
// quotes (a Commission Q&A, a methodology page) comes earlier, inside brackets.
function extractRecordUrl(text: string): string | undefined {
  const all = [...text.matchAll(/https?:\/\/[^\s*),\]]+/g)]
  return all.length ? all[all.length - 1][0] : undefined
}

// Every distinct URL in a record, in order of appearance, without a sentence's closing
// punctuation.
function extractAllUrls(text: string): string[] {
  const urls = [...text.matchAll(/https?:\/\/[^\s*),\]]+/g)].map(m => m[0].replace(/[.;:]+$/, ''))
  return [...new Set(urls)]
}

// A summary that ends in a full stop, followed by the ". " the record adds, leaves "..";
// an ellipsis of three stops is kept.
function singleStops(text: string): string {
  return text.replace(/(?<!\.)\.\.(?!\.)/g, '.')
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

// Reports written before November 2026 named sources by their enum, title-cased.
const SOURCE_NAMES: Record<string, string> = {
  Egt: 'Europe Gas Tracker',
  Goget: 'Global Oil and Gas Extraction Tracker',
  Gogel: 'Global Oil and Gas Exit List',
  Gcpt: 'Global Coal Plant Tracker',
  'Coal Exit': 'Global Coal Exit List',
  Tpi: 'Transition Pathway Initiative',
  Edgar: 'EDGAR (JRC)',
  'Climate Trace': 'Climate TRACE',
  'Eea National': 'EEA national inventory',
  Enforcement: 'Enforcement record',
  Ca100: 'Climate Action 100+',
  'Fossil Finance': 'Banking on Climate Chaos',
  Eurostat: 'Eurostat',
}

// A claim as the reader sees it: on one line, without markdown escapes, and with a
// chemical formula that a page's subscript split ("CO 2 e") written as the page shows it.
function cleanClaim(text: string): string {
  return text
    .replace(/\\([*_`\\])/g, '$1')
    .replace(/\s+/g, ' ')
    .replace(/\bCO\s+2\s*e\b/g, 'CO2e')
    .replace(/\bCO\s+2\b/g, 'CO2')
    .trim()
}

function parseNumberedEvidence(section: string): EvidenceItem[] {
  return section
    .split(/\n\n(?=\*\*\[\d+\])/)
    .filter(c => /^\*\*\[\d+\]/.test(c.trim()))
    .map(chunk => {
      const hm = chunk.match(/^\*\*\[(\d+)\] ([^*]+)\*\* ([\s\S]+)$/)
      if (!hm) return null
      const num = parseInt(hm[1])
      const label = hm[2].trim().replace(/\.$/, '')
      const source = SOURCE_NAMES[label] ?? label
      let body = hm[3].trim()
      const url = extractRecordUrl(body)
      const urls = extractAllUrls(body)
      const conf = extractConf(body)
      const supRaw = body.match(/Supports claim:\s*(\w+)/i)?.[1] ?? 'N/A'
      const supports = normaliseSupports(supRaw)
      body = body
        .replace(/\*Source:[^*]+\*/g, '')
        .replace(/Supports claim:[^.]+\./gi, '')
        .replace(/\(confidence[\d\s.]+\)/gi, '')
        .replace(/\s{2,}/g, ' ')
        .trim()
      // Only the record's own URL, at the end of the line, is taken out: the Sources list
      // gives it. A URL inside the text, such as the PDF a page reference points into, stays
      // and is shown as a link.
      if (url && body.endsWith(url)) body = body.slice(0, -url.length).trim()
      body = singleStops(body)
      return { num, source, body, supports, confidence: conf, url, urls }
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
    items.push({ num: num++, source, body, supports: currentSupports, confidence: conf, url, urls: url ? [url] : [] })
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
        .replace(/^[—–-]\s*/, '') // style-ok: strips leading dashes from report markdown
        .replace(/\([^)]*https?:\/\/[^)]*\)/g, '')
        .replace(/\*[^*]+\*/g, '')
        .replace(/Supports claim:[^.]+\./gi, '')
        .replace(/\s*Source:\s*[A-Z][A-Z_]+\b[^]*$/g, '')
        .replace(/\(confidence[\d\s.]+\)/gi, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/\s{2,}/g, ' ')
        .trim()
      return { num: i + 1, source, body, supports, confidence: conf, url, urls: url ? [url] : [] }
    })
}

function parseEvidence(section: string): EvidenceItem[] {
  if (/\*\*\[\d+\]/.test(section))                       return parseNumberedEvidence(section)
  if (/\*\*Contradicting|\*\*Supporting/i.test(section)) return parseBulletEvidence(section)
  return parseParagraphEvidence(section)
}

export function parseReport(source: string): ParsedReport {
  // The pipeline runs on Windows as well as Linux; every rule below expects "\n".
  const md = source.replace(/\r\n?/g, '\n')
  // style-ok: reports written before November 2026 use the dashed header form.
  const headerMatch = md.match(/^## (.+?)(?: — |: )Company Assessment \((\d+) claim/m) // style-ok
  const company = headerMatch?.[1] ?? 'Unknown Company'
  const claimCount = parseInt(headerMatch?.[2] ?? '1')

  const overallScore = parseInt(md.match(/\*\*Overall Score: (\d+)\/100\*\*/)?.[1] ?? '0')
  // Numbers only: the header may explain the range in brackets after them.
  const scoreRange = md.match(/\*\*Score range:\*\* (\d+\s*[–-]\s*\d+)/)?.[1]?.trim() ?? ''
  // Set when the band of the highest-scoring claim, not the mean, gave the company score.
  // A report states the raise in its score line ("(raised to 61, the lower bound ...");
  // reports from before November 2026 state it in a note under the header.
  const floorApplied =
    /\*\*Overall Score: \d+\/100\*\* \(raised to /.test(md) ||
    /^\*Score (?:floored at|raised to) the bottom/m.test(md)
  const meanMatch = md.match(/\*\*Overall Score: \d+\/100\*\* \(raised to \d+,[^\n]*? is (\d+)[;)]/)
  // Set when the score line says a pledge stated in several claims counts once.
  const pledgeOnce = /\*\*Overall Score: \d+\/100\*\*[^\n]*counts once\)/.test(md)
  const competing = parseInt(
    md.match(/\*\*Overall Score: \d+\/100\*\*[^\n]*?highest-scoring of (\d+) claims/)?.[1] ??
      String(claimCount),
  )
  const meanScore = meanMatch ? parseInt(meanMatch[1]) : null
  const verdict = md.match(/\*\*(?:Verdict|Finding):\*\* ([^\n*]+)/)?.[1]?.trim() ?? ''
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
        text: cleanClaim(cells[3] ?? ''),
      }
    })

  // The paragraphs between the last row of the claims table and the next heading or rule.
  const mdLines = md.split('\n')
  const lastRow = mdLines.reduce((acc, l, i) => (/^\| \d+/.test(l) ? i : acc), -1)
  const afterTable = lastRow > -1 ? mdLines.slice(lastRow + 1).join('\n') : ''
  const claimsNotes: string[] = []
  for (const block of afterTable.split(/\n\n+/).map(b => b.trim()).filter(Boolean)) {
    if (!/^[A-Z“"]/.test(block)) break
    claimsNotes.push(block.replace(/\s*\n\s*/g, ' '))
  }
  const uncountedOrdinals = claimsNotes.flatMap(note => {
    const m = note.match(UNCOUNTED_NOTE)
    return m ? [ORDINALS.indexOf(m[1].toLowerCase()) + 1] : []
  })
  const uncounted = uncountedOrdinals.length

  const detailHeader = md.match(
    /\*\*(?:Verdict|Finding): ([^*]+)\*\* \| Score: ([\d.]+)\/100 \(range: ([^)]+)\) \| Confidence: (\d+)%/,
  )
  const detailVerdict = detailHeader?.[1]?.trim() ?? verdict
  const detailScore = parseFloat(detailHeader?.[2] ?? String(overallScore))
  const detailRange = detailHeader?.[3]?.trim() ?? scoreRange
  const detailConfidence = parseInt(detailHeader?.[4] ?? String(confidence))
  const detailParsed = detailHeader !== null

  const publishMatch = md.match(
    /\*(?:Assessed|Published): ([^|]+) \| Prasine Index \| Trace ID: ([^*\n]+)\*/,
  )
  const publishDate = publishMatch?.[1]?.trim() ?? ''
  const traceId = publishMatch?.[2]?.trim() ?? ''

  // The quote may run over several "> " lines (a page's subscript can break it), and it
  // ends at the last quotation mark of its last line, so a claim that quotes something
  // stays whole.
  const claimMatch = md.match(/^> "([\s\S]*?)"[ \t]*$/m)
  const claim = cleanClaim((claimMatch?.[1] ?? '').replace(/\n>[ \t]?/g, ' '))
  const claimSource = humanizeText(md.match(/\*Source: ([^\n*]+)\*/)?.[1]?.trim() ?? '')

  // The evidence runs to the next heading, whichever section follows it.
  const evStart = md.indexOf('### Evidence')
  const evNext = evStart > -1 ? md.indexOf('\n### ', evStart + 1) : -1
  const evSection = evStart > -1 ? md.slice(evStart, evNext > -1 ? evNext : undefined) : ''
  const evidence = parseEvidence(evSection)

  // Each section runs to the next heading, so a section the site does not show
  // (such as the pre-November 2026 "Regulatory Exposure") never leaks into the
  // one before it.
  const assessmentParas = sectionBlocks(md, 'Assessment')
  const companyContext = sectionBlocks(md, 'Company Context')
  // The company record is generated by code: paragraphs, then one list item per record type.
  const recordBlocks = sectionBody(md, 'Company Record').split(/\n\n+/).map(b => b.trim()).filter(Boolean)
  const companyRecord = {
    paras: recordBlocks.filter(b => !b.startsWith('- ')),
    items: recordBlocks
      .filter(b => b.startsWith('- '))
      .flatMap(b => b.split(/\n(?=- )/))
      .map(item => item.replace(/^- /, '').trim()),
  }
  const regulatoryContext = sectionBlocks(md, 'Regulatory Context')
  const keyFinding = sectionParas(md, 'Key Finding').join(' ')

  const dataGaps = sectionBody(md, 'Data Gaps')
    .split('\n')
    .filter(l => l.startsWith('**') || l.startsWith('- '))
    .map(l => l.replace(/^- /, '').trim())

  return {
    company, claimCount, overallScore, scoreRange, floorApplied, meanScore, pledgeOnce, competing, verdict, confidence, claims, claimsNotes, uncounted, uncountedOrdinals,
    detailVerdict, detailScore, detailRange, detailConfidence, detailParsed,
    publishDate, traceId, claim, claimSource,
    evidence, assessmentParas, companyContext, companyRecord, regulatoryContext, keyFinding, dataGaps,
  }
}

function sectionBody(md: string, title: string): string {
  const heading = `### ${title}`
  const start = md.indexOf(`\n${heading}\n`)
  if (start === -1) return ''
  const bodyStart = start + heading.length + 2
  const nextHeading = md.indexOf('\n### ', bodyStart)
  const rule = md.indexOf('\n---\n', bodyStart)
  const ends = [nextHeading, rule].filter(i => i > -1)
  return md.slice(bodyStart, ends.length ? Math.min(...ends) : undefined)
}

function sectionParas(md: string, title: string): string[] {
  return sectionBody(md, title)
    .split(/\n\n+/)
    .map(p => humanizeText(p.trim()))
    .filter(p => p.length > 0 && !p.startsWith('#') && !/^-{3,}$/.test(p))
}

// The marker of a claim that was assessed and is not counted: a note under the claims
// table that opens "A seventh claim, ..." and says the claim "is left out of this table
// and of the score". The header's claim count stays the number of rows in the table.
const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth']
const UNCOUNTED_NOTE = new RegExp(
  `^A (${ORDINALS.join('|')}) claim\\b[^.]*?\\bis left out of this table and of the score\\b`,
  'i',
)

/**
 * A chunk of a section as paragraphs and lists. A line that starts with "- " is a list
 * item, and one indented further than the item above it is nested under that item.
 */
function toBlocks(chunk: string): Block[] {
  const blocks: Block[] = []
  let para: string[] = []
  // The open lists, outermost first, with the indent of their items.
  let stack: { indent: number; items: ListItem[] }[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') })
    para = []
  }
  for (const raw of chunk.split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) continue
    const m = line.match(/^(\s*)- (.*)$/)
    if (m) {
      flush()
      const indent = m[1].length
      const item: ListItem = { text: m[2].trim(), children: [] }
      if (stack.length === 0) {
        const items: ListItem[] = []
        blocks.push({ kind: 'ul', items })
        stack = [{ indent, items }]
      }
      while (stack.length > 1 && indent < stack[stack.length - 1].indent) stack.pop()
      const top = stack[stack.length - 1]
      if (indent > top.indent && top.items.length > 0) {
        stack.push({ indent, items: top.items[top.items.length - 1].children })
      }
      stack[stack.length - 1].items.push(item)
    } else if (stack.length > 0 && /^\s/.test(line)) {
      // An indented line under an item continues it.
      const items = stack[stack.length - 1].items
      items[items.length - 1].text += ` ${line.trim()}`
    } else {
      stack = []
      para.push(line.trim())
    }
  }
  flush()
  return blocks
}

function sectionBlocks(md: string, title: string): Block[] {
  const blocks = sectionParas(md, title).flatMap(toBlocks)
  // Items of one list separated by a blank line stay one list.
  return blocks.reduce<Block[]>((acc, b) => {
    const prev = acc[acc.length - 1]
    if (b.kind === 'ul' && prev?.kind === 'ul') prev.items.push(...b.items)
    else acc.push(b)
    return acc
  }, [])
}

// NOTE: must add an entry here whenever a company is added to SLUGS.
// Reports don't carry a machine-readable sector field, so this is the
// single source of truth for the .com index table's Sector column.
const SECTOR_MAP: Record<string, string> = {
  'ryanair-holdings-plc': 'Aviation',
  'bp-plc':               'Oil & Gas',
  'glencore-plc':         'Mining',
  'enel-spa':             'Energy',
  'ikea-group':           'Retail',
  'h-m-group':            'Fashion',
  'orsted-a-s':           'Renewables',
  'ssab-ab':              'Steel',
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

// ── Home page helpers ────────────────────────────────────────────────────────

/** The row of the claims table that the detailed section covers, or -1. */
export function detailClaimIndex(r: ParsedReport): number {
  // Match on text first, because several claims can share a score.
  const textIndex = r.claims.findIndex(c => {
    const preview = c.text.replace(/(\.{3}|…)$/, '').trim()
    return preview.length > 0 && r.claim.startsWith(preview.slice(0, 60))
  })
  return textIndex > -1 ? textIndex : r.claims.findIndex(c => c.score === r.detailScore)
}

/** The two numbers of a score range such as "50–72", or null. */
export function rangeNumbers(text: string): [number, number] | null {
  const m = text.match(/^(\d+)\s*[–-]\s*(\d+)/)
  return m ? [parseInt(m[1]), parseInt(m[2])] : null
}

/** The band index 0 to 4 of a finding label, from Supported by records to Contradicted by records. */
export function bandIndex(label: string): number {
  return FINDINGS.findIndex(f => f.label === label)
}

export const BAND_RANGES = ['0–20', '21–40', '41–60', '61–80', '81–100']

export interface PublishedReport {
  slug: string
  report: ParsedReport
}

/**
 * Parse every published report, failing the build when one is missing or malformed.
 * A silent gap would drop a company from the page and could move both ends of the
 * comparison, so each check names the slug and what failed.
 */
export function loadPublishedReports(slugs: string[], awaiting: Record<string, string>): PublishedReport[] {
  const labels = new Set(FINDINGS.map(f => f.label))
  return slugs.map(slug => {
    const fail = (why: string): never => {
      throw new Error(`Published report ${slug}: ${why}`)
    }
    if (slug in awaiting) fail('it is also listed as awaiting reassessment')
    const path = join(process.cwd(), '..', 'docs', 'reports', `${slug}.md`)
    if (!existsSync(path)) fail(`file missing at ${path}`)
    const md = readFileSync(path, 'utf-8')
    if (!/\*\*Overall Score: \d+\/100\*\*/.test(md)) {
      fail('no "**Overall Score: N/100**" line, so the company score would read as 0')
    }
    const report = parseReport(md)
    if (report.company === 'Unknown Company') fail('the company header did not parse')
    if (report.claims.length === 0 || report.claims.length !== report.claimCount) {
      fail(`${report.claims.length} claim rows for ${report.claimCount} claims`)
    }
    // A claim left out of the score must be stated in a note under the table, and the
    // note must number it after the claims the table holds.
    const expected = UNCOUNTED_CLAIMS[slug] ?? 0
    if (report.uncounted !== expected) {
      fail(`${report.uncounted} notes on a claim left out of the score, where ${expected} were expected (UNCOUNTED_CLAIMS in lib/site.ts)`)
    }
    report.uncountedOrdinals.forEach((n, i) => {
      if (n !== report.claimCount + i + 1) {
        fail(`the note on a claim left out of the score numbers it ${n}, after ${report.claimCount} claims in the table`)
      }
    })
    for (const c of report.claims) {
      if (!Number.isInteger(c.score) || c.score < 0 || c.score > 100) fail(`claim score ${c.score}`)
    }
    const finding = findingFromString(report.verdict).label
    if (!labels.has(finding) || finding !== verdictFromScore(report.overallScore).label) {
      fail(`finding "${report.verdict}" does not match the score ${report.overallScore}`)
    }
    if (report.companyRecord.items.length === 0) fail('no company record (a version 1 report?)')
    if (!report.detailParsed) fail('the detailed claim header did not parse')
    if (report.evidence.length === 0) fail('no evidence records')
    if (report.assessmentParas.length === 0) fail('no assessment')
    const di = detailClaimIndex(report)
    if (di === -1 || Math.abs(report.claims[di].score - report.detailScore) > 0.5) {
      fail(`the detailed claim (score ${report.detailScore}) matches no row of the claims table`)
    }
    // The detailed claim is the one whose full text the report holds: if its row is a
    // bare prefix of it, the table cut claims without marking the cut.
    const full = report.claim.replace(/\s+/g, ' ').trim()
    const shown = report.claims[di].text.replace(/\s+/g, ' ').trim()
    if (shown && full.length > shown.length && full.startsWith(shown)) {
      fail('the claims table cuts a claim without an ellipsis; re-run the report')
    }
    return { slug, report }
  })
}

/** A report date such as "2026-11-06" as "6 November 2026"; any other text is returned as it is. */
export function formatLongDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso) || Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
}

/** The dates the published reports carry, as one phrase: "5 November 2026" or "5 and 6 November 2026". */
export function assessedDates(reports: PublishedReport[]): string {
  const days = [...new Set(reports.map(p => p.report.publishDate).filter(Boolean))].sort()
  if (days.length === 0) throw new Error('No published report carries a date')
  const long = formatLongDate
  if (days.some(d => long(d) === d)) throw new Error(`A report date does not parse: ${days.join(', ')}`)
  if (days.length === 1) return long(days[0])
  const first = long(days[0])
  const last = long(days[days.length - 1])
  const [d1, m1, y1] = first.split(' ')
  const [d2, m2, y2] = last.split(' ')
  if (days.length === 2 && m1 === m2 && y1 === y2) return `${d1} and ${d2} ${m2} ${y2}`
  return `${first} to ${last}`
}
