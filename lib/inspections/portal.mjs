// Client for the VDH inspections portal (inspections.myhealthdepartment.com).
//
// The portal is a static Webflow front-end driven by a JSON endpoint: the page
// POSTs {task, data} to "/?page=ajax". searchInspections returns the rows the
// jurisdiction landing page lists; the per-inspection page carries the violations
// as server-rendered HTML.
//
// Verified against the live portal on 2026-08-13 from a residential connection.
// What the live site actually does, versus what was guessed before:
//   - searchInspections ignores `count` and always returns at most 25 rows.
//     `start` is honoured, so paging works by stepping start in 25s. Asking for
//     a start past the end returns {"err":true,"msg":"bad request"}.
//   - inspectionDate comes back as MM/DD/YYYY, not ISO.
//   - score is always 0 and scoreDisplay always "" for these jurisdictions; the
//     portal's own config reports showScore:false, so the number is meaningless.
//   - There is no "getInspection" task ("the task you requested is invalid"),
//     and /print/?task=getPrintable returns a scanned-image PDF, not HTML
//     (the portal config also reports allowPDFPrint:false). Violations are read
//     from the inspection page's <p class="observations-text"> block instead.
//   - No reCAPTCHA gates the JSON API. The portal config for these jurisdictions
//     reports enableCaptchaInspectionsLandingPage:false, and every request here
//     succeeds with no token of any kind.
//
// The portal sits behind an AWS WAF that answers 403 to a lot of datacenter
// traffic. If the host running this is refused, set INSPECTIONS_PROXY_TEMPLATE
// to a fetch-a-page-for-me service URL containing "{url}", e.g.
//   https://api.scraperapi.com/?api_key=KEY&url={url}
// and every request is routed through it.

export const HOST = 'https://inspections.myhealthdepartment.com';

export const JURISDICTIONS = [
  { key: 'H', path: 'va-henrico', name: 'Henrico County' },
  { key: 'R', path: 'va-richmond', name: 'Richmond City' },
];

export const byKey = (key) => JURISDICTIONS.find((j) => j.key === key);
export const byPath = (path) => JURISDICTIONS.find((j) => j.path === path);

const BROWSER_HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  'Accept-Language': 'en-US,en;q=0.9',
};

export class PortalBlocked extends Error {}
export class PortalError extends Error {}

function viaProxy(url) {
  const template = (process.env.INSPECTIONS_PROXY_TEMPLATE || '').trim();
  if (!template) return url;
  if (!template.includes('{url}')) {
    throw new PortalError('INSPECTIONS_PROXY_TEMPLATE must contain "{url}"');
  }
  return template.replace('{url}', encodeURIComponent(url));
}

async function request(url, init = {}, { retries = 2, timeoutMs = 15000 } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(viaProxy(url), {
        ...init,
        signal: controller.signal,
        headers: { ...BROWSER_HEADERS, ...(init.headers || {}) },
      });
      if (res.status === 403) {
        throw new PortalBlocked(
          `403 from the inspections portal — this network is refused by its firewall. ` +
            `Set INSPECTIONS_PROXY_TEMPLATE to route requests through a fetch proxy.`
        );
      }
      if (!res.ok) throw new PortalError(`HTTP ${res.status} for ${url}`);
      return await res.text();
    } catch (e) {
      if (e instanceof PortalBlocked) throw e;
      lastError = e;
      if (attempt < retries) await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
    } finally {
      clearTimeout(timer);
    }
  }
  throw new PortalError(`${url} failed after ${retries + 1} attempts: ${lastError}`);
}

async function ajax(task, data, { referer } = {}) {
  const body = JSON.stringify({ task, data });
  const text = await request(`${HOST}/?page=ajax`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/plain, */*',
      'X-Requested-With': 'XMLHttpRequest',
      ...(referer ? { Referer: referer } : {}),
    },
    body,
  });
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new PortalError(`${task} did not return JSON (got ${text.slice(0, 120)}…)`);
  }
  // The portal spells its error flag two ways: "err" from searchInspections,
  // "error" from the task dispatcher itself.
  if (parsed && !Array.isArray(parsed) && (parsed.err || parsed.error)) {
    throw new PortalError(`${task} returned error: ${parsed.msg || parsed.err || parsed.error}`);
  }
  return parsed;
}

const pad = (n) => String(n).padStart(2, '0');
export const isoDate = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;

// The portal serves dates as MM/DD/YYYY (its config declares
// hscSettings.dateFormat "mm/dd/yyyy"). Everything downstream wants ISO.
function toIsoDate(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const us = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (us) return `${us[3]}-${pad(us[1])}-${pad(us[2])}`;
  const iso = raw.match(/^(\d{4}-\d{2}-\d{2})/);
  if (iso) return iso[1];
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? '' : isoDate(parsed);
}

// searchInspections ignores the requested `count` and caps every response at 25.
const PAGE_SIZE = 25;

/**
 * Inspections published for one jurisdiction between two dates (inclusive).
 * Pages through the portal until it stops returning full pages.
 */
export async function fetchInspections(jurisdiction, startDate, endDate, { maxPages = 40 } = {}) {
  const rows = [];
  const seen = new Set();
  for (let page = 0; page < maxPages; page++) {
    let batch;
    try {
      batch = await ajax(
        'searchInspections',
        {
          path: jurisdiction.path,
          programName: '',
          filters: { date: `${startDate} to ${endDate}` },
          start: page * PAGE_SIZE,
          count: PAGE_SIZE,
          searchQueryOverride: null,
          searchStr: '',
          lat: 0,
          lng: 0,
          sort: {},
        },
        { referer: `${HOST}/${jurisdiction.path}` }
      );
    } catch (e) {
      // Stepping past the last page answers {"err":true,"msg":"bad request"}.
      // That's the end of the list, not a failure — but only ever after we've
      // already read something, so a genuine first-page error still surfaces.
      if (e instanceof PortalError && page > 0) break;
      throw e;
    }
    const list = Array.isArray(batch) ? batch : batch?.inspections || [];
    // The portal will happily repeat rows rather than return an empty page.
    const fresh = list.filter((row) => row && !seen.has(row.inspectionID));
    for (const row of list) if (row) seen.add(row.inspectionID);
    rows.push(...fresh);
    if (list.length < PAGE_SIZE || !fresh.length) break;
  }
  return rows.map((row) => normalize(row, jurisdiction));
}

function normalize(row, jurisdiction) {
  const address = [row.addressLine1, row.addressLine2].filter(Boolean).join(' ').trim();
  const cityLine = [row.city, row.state].filter(Boolean).join(', ');
  const scoreDisplay = (row.scoreDisplay || '').trim();
  // These jurisdictions don't score inspections: every row comes back score 0
  // with an empty scoreDisplay, and the portal hides the field (showScore:false).
  // Passing the 0 through renders a meaningless "score 0" on every entry.
  const scored = scoreDisplay !== '' || (row.score !== null && row.score !== undefined && row.score !== 0);
  return {
    id: row.inspectionID,
    permitId: row.permitID,
    jurisdiction: jurisdiction.name,
    jurisdictionKey: jurisdiction.key,
    jurisdictionPath: jurisdiction.path,
    establishment: (row.establishmentName || 'Unknown establishment').trim(),
    address: [address, cityLine].filter(Boolean).join(', '),
    date: toIsoDate(row.inspectionDate),
    // inspectionType is the establishment category ("Fast Food", "Mobile Food
    // Unit"); purpose is the kind of visit ("Routine", "Follow-Up").
    type: (row.inspectionType || '').replace('(OLD)', '').trim(),
    purpose: (row.purpose || '').trim(),
    score: scored ? row.score : null,
    scoreDisplay: scored ? scoreDisplay : '',
    url: `${HOST}/${jurisdiction.path}/inspection/?inspectionID=${row.inspectionID}`,
  };
}

/** Every inspection across both jurisdictions, newest first. */
export async function fetchAll(startDate, endDate, options) {
  const all = [];
  for (const jurisdiction of JURISDICTIONS) {
    all.push(...(await fetchInspections(jurisdiction, startDate, endDate, options)));
  }
  return all.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

// ---------------------------------------------------------------------------
// Violations, fetched on demand when someone taps a button in Telegram.
// ---------------------------------------------------------------------------

const stripTags = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|tr|li|h\d)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n+/g, '\n')
    .trim();

/**
 * Violation lines for one inspection, read from the inspection page.
 *
 * The page server-renders the inspector's write-up into a single
 * <p class="observations-text"> block, so one GET is enough. The JSON API has
 * no task that returns it and the printable endpoint is a scanned PDF.
 */
export async function fetchViolations(jurisdiction, inspectionId) {
  const url = `${HOST}/${jurisdiction.path}/inspection/?inspectionID=${encodeURIComponent(inspectionId)}`;
  const html = await request(url, {
    headers: { Accept: 'text/html,*/*', Referer: `${HOST}/${jurisdiction.path}` },
  });
  return {
    violations: extractViolationsFromHtml(html),
    source: 'inspection-page',
    ...extractHeaderFromHtml(html),
  };
}

/** Establishment name and inspection date from the inspection page. */
function extractHeaderFromHtml(html) {
  const out = {};

  // <h2 class="establishment-page-left-name"><a …>Jimmy John's</a></h2>
  const nameMatch = html.match(
    /<h2[^>]*class="[^"]*establishment-page-left-name[^"]*"[^>]*>([\s\S]*?)<\/h2>/i
  );
  if (nameMatch) {
    const name = stripTags(nameMatch[1]);
    if (name) out.establishment = name;
  }

  // The <h1> holds "Fast Food | Routine"; the date is the div right after it.
  const dateMatch = html.match(
    /<h1[^>]*class="[^"]*establishment-page-left-name[^"]*"[^>]*>[\s\S]*?<\/h1>\s*<div[^>]*>\s*([^<]+)/i
  );
  if (dateMatch) {
    const date = toIsoDate(dateMatch[1]);
    if (date) out.date = date;
  }
  return out;
}

/**
 * Violations out of the inspection page's observations block.
 *
 * The block is one <p> holding every citation, entries separated by a double
 * <br> and each entry shaped like:
 *
 *   16: 12VAC5-421-1780.E.4 Observed mold build-up on the ice machine.
 *   <br>Corrective Actions: Clean
 *
 * The leading number is the FDA risk-factor item; the code is the Virginia
 * Administrative Code cite. Note that this portal does not publish the
 * Priority / Priority Foundation / Core classification anywhere in the page —
 * severity is left empty rather than guessed at.
 */
function extractViolationsFromHtml(html) {
  const block = html.match(
    /<p[^>]*class="[^"]*observations-text[^"]*"[^>]*>([\s\S]*?)<\/p>/i
  );
  if (!block) return [];

  return block[1]
    .split(/(?:<br\s*\/?>\s*){2,}/i)
    .map((chunk) => {
      const parts = chunk
        .split(/<br\s*\/?>/i)
        .map((p) => stripTags(p))
        .filter(Boolean);
      if (!parts.length) return null;

      const corrective = parts
        .slice(1)
        .join(' ')
        .replace(/^Corrective Actions?:\s*/i, '')
        .trim();

      // "16: 12VAC5-421-1780.E.4 Observed mold build-up…"
      const head = parts[0].match(/^(\d+)\s*:\s*(\S+)\s+([\s\S]+)$/);
      const item = head ? head[1] : '';
      const code = head ? head[2] : '';
      const description = (head ? head[3] : parts[0]).trim();
      if (!description) return null;

      const whole = `${parts[0]} ${corrective}`;
      return {
        code: [item ? `#${item}` : '', code].filter(Boolean).join(' '),
        text: corrective ? `${description}\n↳ ${corrective}` : description,
        severity: '',
        repeat: /\brepeat\b/i.test(whole),
        corrected: /corrected on[- ]site|\bCOS\b|voluntarily discarded|during (?:the )?inspection/i.test(corrective),
      };
    })
    .filter(Boolean);
}
