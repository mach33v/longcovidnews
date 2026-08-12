// Renders the weekly digest and the on-demand violation replies.

import { escapeHtml, splitMessage, MAX_LEN } from './telegram.mjs';

const TZ = 'America/New_York';
const BUTTONS_PER_ROW = 5;

const fmtDate = (iso, opts) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', { timeZone: TZ, ...opts });

export function formatRange(startIso, endIso) {
  const sameYear = startIso.slice(0, 4) === endIso.slice(0, 4);
  const start = fmtDate(startIso, { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) });
  const end = fmtDate(endIso, { month: 'short', day: 'numeric', year: 'numeric' });
  return `${start} – ${end}`;
}

// The portal reports a type ("Routine", "Follow-up", "Complaint") and a purpose;
// showing both is redundant when they agree.
function describeType(inspection) {
  const parts = [inspection.type, inspection.purpose].filter(Boolean);
  const unique = [...new Set(parts.map((p) => p.trim()))];
  return unique.join(' · ');
}

function renderEntry(inspection, number) {
  const name = escapeHtml(inspection.establishment);
  const title = inspection.url
    ? `<b>${number}.</b> <a href="${escapeHtml(inspection.url)}">${name}</a>`
    : `<b>${number}.</b> ${name}`;

  const meta = [fmtDate(inspection.date, { weekday: 'short', month: 'short', day: 'numeric' })];
  const type = describeType(inspection);
  if (type) meta.push(escapeHtml(type));
  if (inspection.scoreDisplay) meta.push(escapeHtml(inspection.scoreDisplay));
  else if (inspection.score !== null && inspection.score !== undefined && inspection.score !== '') {
    meta.push(`score ${escapeHtml(inspection.score)}`);
  }

  const lines = [title, `<i>${meta.join(' · ')}</i>`];
  if (inspection.address) lines.push(escapeHtml(inspection.address));
  return lines.join('\n');
}

/**
 * Build the digest as a list of messages, each with its own inline keyboard of
 * numbered "show violations" buttons for the entries it contains.
 *
 * Returns [{ text, keyboard }].
 */
export function buildDigest(inspections, startIso, endIso) {
  const header = `<b>🍽 Restaurant inspections</b>\n<i>${formatRange(startIso, endIso)}</i>`;

  if (!inspections.length) {
    return [
      {
        text: `${header}\n\nNo inspections were published for Henrico County or Richmond City this week.`,
        keyboard: null,
      },
    ];
  }

  const byJurisdiction = new Map();
  for (const i of inspections) {
    if (!byJurisdiction.has(i.jurisdiction)) byJurisdiction.set(i.jurisdiction, []);
    byJurisdiction.get(i.jurisdiction).push(i);
  }

  const counts = [...byJurisdiction.entries()]
    .map(([name, rows]) => `${rows.length} in ${escapeHtml(name)}`)
    .join(', ');
  const overview =
    `${inspections.length} inspection${inspections.length === 1 ? '' : 's'} (${counts})\n` +
    `<i>Tap a number below for the violations cited.</i>`;

  // Blocks are the atoms of pagination: each carries the text plus the entries
  // whose buttons must travel with it.
  const blocks = [];
  blocks.push({ text: `${header}\n\n${overview}`, entries: [] });

  let number = 0;
  for (const [name, rows] of [...byJurisdiction.entries()].sort()) {
    rows.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.establishment.localeCompare(b.establishment)));
    blocks.push({ text: `<b>━━ ${escapeHtml(name)} ━━</b>`, entries: [] });
    for (const inspection of rows) {
      number += 1;
      blocks.push({ text: renderEntry(inspection, number), entries: [{ number, inspection }] });
    }
  }

  blocks.push({
    text: '<i>Source: Virginia Dept. of Health inspection portal</i>',
    entries: [],
  });

  return paginate(blocks);
}

function paginate(blocks) {
  const messages = [];
  let text = '';
  let entries = [];

  const flush = () => {
    if (!text) return;
    messages.push({ text, keyboard: buildKeyboard(entries) });
    text = '';
    entries = [];
  };

  for (const block of blocks) {
    const candidate = text ? `${text}\n\n${block.text}` : block.text;
    if (candidate.length > MAX_LEN - 200) {
      flush();
      text = block.text;
      entries = [...block.entries];
    } else {
      text = candidate;
      entries.push(...block.entries);
    }
  }
  flush();

  // A block bigger than the limit on its own would still overflow; make sure.
  return messages.flatMap((m) => {
    const parts = splitMessage(m.text);
    return parts.map((part, idx) => ({
      text: part,
      keyboard: idx === parts.length - 1 ? m.keyboard : null,
    }));
  });
}

function buildKeyboard(entries) {
  if (!entries.length) return null;
  const buttons = entries.map(({ number, inspection }) => ({
    text: String(number),
    callback_data: `v|${inspection.jurisdictionKey}|${inspection.id}`,
  }));
  const rows = [];
  for (let i = 0; i < buttons.length; i += BUTTONS_PER_ROW) {
    rows.push(buttons.slice(i, i + BUTTONS_PER_ROW));
  }
  return rows;
}

const SEVERITY_RANK = { priority: 0, 'priority foundation': 1, core: 2 };
const rank = (v) => SEVERITY_RANK[(v.severity || '').toLowerCase()] ?? 3;

export function buildViolationsMessage({ establishment, date, url, violations, jurisdictionName }) {
  const title = establishment
    ? `<b>${escapeHtml(establishment)}</b>`
    : '<b>Inspection</b>';
  const meta = [jurisdictionName, date ? fmtDate(date, { month: 'short', day: 'numeric', year: 'numeric' }) : null]
    .filter(Boolean)
    .map(escapeHtml)
    .join(' · ');

  const head = [title, meta ? `<i>${meta}</i>` : null].filter(Boolean).join('\n');

  if (!violations || !violations.length) {
    const link = url ? `\n\n<a href="${escapeHtml(url)}">Open the full report</a>` : '';
    return `${head}\n\nNo violations were listed for this inspection.${link}`;
  }

  const sorted = [...violations].sort((a, b) => rank(a) - rank(b));
  const lines = sorted.map((v) => {
    const marks = [];
    if (v.severity) marks.push(v.severity);
    if (v.repeat) marks.push('repeat');
    if (v.corrected) marks.push('corrected on site');
    const suffix = marks.length ? ` <i>(${escapeHtml(marks.join(', '))})</i>` : '';
    const code = v.code ? `<code>${escapeHtml(v.code)}</code> ` : '';
    const bullet = rank(v) <= 1 ? '‼️' : '•';
    return `${bullet} ${code}${escapeHtml(v.text)}${suffix}`;
  });

  const link = url ? `\n<a href="${escapeHtml(url)}">Full report</a>` : '';
  const count = `${violations.length} violation${violations.length === 1 ? '' : 's'} cited`;
  return `${head}\n<i>${count}</i>\n\n${lines.join('\n\n')}\n${link}`;
}
