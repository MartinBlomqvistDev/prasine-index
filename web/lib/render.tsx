import type { ReactNode } from 'react'
import type { Block, ListItem } from './parse-report'

// Markdown bold (**text**) as <strong>, everything else as plain text.
export function renderInline(text: string): ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/g)
  return parts.map((part, i) => (i % 2 === 1 ? <strong key={i}>{part}</strong> : part))
}

// The host of a URL without "www.", used as the visible name of a link.
export function siteName(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

// The visible name of a link: the file name of a PDF, so that a page reference such as
// "PDF page 12" can be matched to its document, and the site's name otherwise.
export function linkName(url: string): string {
  try {
    const u = new URL(url)
    const last = decodeURIComponent(u.pathname.split('/').pop() ?? '')
    if (/\.pdf$/i.test(last)) return last
    const param = u.searchParams.get('filename') ?? ''
    if (/\.pdf$/i.test(param)) return param
  } catch {
    // An unparsable URL falls back to siteName, which returns it as it is.
  }
  return siteName(url)
}

// Bold text as in renderInline, with each URL shown as a link named by linkName.
export function renderLinked(text: string): ReactNode[] {
  return text.split(/(https?:\/\/[^\s)]+)/g).flatMap((part, i) => {
    if (!/^https?:\/\//.test(part)) {
      return renderInline(part).map((node, j) => <span key={`t${i}-${j}`}>{node}</span>)
    }
    // A sentence's comma or full stop after a URL belongs to the sentence, not the link.
    const trail = part.match(/[.,;:]+$/)?.[0] ?? ''
    const url = trail ? part.slice(0, -trail.length) : part
    const link = <a key={`u${i}`} href={url} target="_blank" rel="noopener">{linkName(url)}</a>
    return trail ? [link, <span key={`p${i}`}>{trail}</span>] : [link]
  })
}

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

/** A count from zero to ten as a word, and a larger one in digits. */
export function count(n: number): string {
  return NUMBER_WORDS[n] ?? String(n)
}

/**
 * The claim count under a company's name: "6 claims assessed", or, when claims were
 * assessed and left out of the score, "7 claims assessed, 6 counted".
 */
export function claimCountText(r: { claimCount: number; uncounted?: number }): string {
  const assessed = r.claimCount + (r.uncounted ?? 0)
  const text = `${assessed} ${assessed === 1 ? 'claim' : 'claims'} assessed`
  return r.uncounted ? `${text}, ${r.claimCount} counted` : text
}

function ListItems({ items }: { items: ListItem[] }) {
  return (
    <ul>
      {items.map((item, i) => (
        <li key={i}>
          {renderLinked(item.text)}
          {item.children.length > 0 && <ListItems items={item.children} />}
        </li>
      ))}
    </ul>
  )
}

/** The paragraphs and lists of a report section, lists nested as the report nests them. */
export function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === 'p'
          ? <p key={i}>{renderLinked(b.text)}</p>
          : <ListItems key={i} items={b.items} />,
      )}
    </>
  )
}

/**
 * How a company score was reached, for the line under it. When the score was raised to
 * the lower bound of the band of the highest-scoring claim, the line says so and gives
 * the mean it was raised from; the range belongs to that mean.
 */
export function aggregateNote(r: {
  claimCount: number
  overallScore: number
  floorApplied: boolean
  meanScore: number | null
  pledgeOnce?: boolean
  competing?: number
  // Claims assessed and left out of the score; the other counts cover only the claims counted.
  uncounted?: number
  range: [number, number] | null
}): string {
  const range = r.range ? `${r.range[0]}–${r.range[1]}` : ''
  // The claims that compete for the mean: a pledge stated in several claims counts once.
  const n = r.competing ?? r.claimCount
  const counted = r.uncounted ? ' counted' : ''
  // With three or more claims left, the mean takes the top three of them; with two, both.
  const pool =
    n >= 3
      ? `so the three are drawn from ${count(n)} of the ${count(r.claimCount)}${counted} claims`
      : `so the mean is taken over ${count(n)} of the ${count(r.claimCount)}${counted} claims`
  const once = r.pledgeOnce
    ? n < r.claimCount
      ? ` A pledge stated in more than one claim counts once, ${pool}.`
      : ' A pledge stated in more than one claim counts once.'
    : ''
  if (n <= 1) return `Score of the single claim${range ? ` · the model's range ${range}` : ''}`
  const top = `${n === 2 ? 'higher-scoring' : 'highest-scoring'}${counted}`
  const claims =
    n === 2
      ? 'both claims'
      : n === 3
        ? 'the three claims'
        : `the three highest-scoring of ${count(n)} claims`
  if (r.floorApplied && r.meanScore !== null) {
    return (
      `Raised to ${r.overallScore}, the lower bound of the band of the ${top} claim. ` +
      `The confidence-weighted mean of ${claims} is ${r.meanScore}` +
      `${range ? `, with a range of ${range}` : ''}.${once}`
    )
  }
  return (
    `Confidence-weighted mean of ${claims}, never below the band of the ${top} one` +
    `${range ? ` · range ${range}` : ''}${once ? ` ·${once.slice(0, -1).toLowerCase()}` : ''}`
  )
}
