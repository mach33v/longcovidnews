// Client for the VDH inspections portal (inspections.myhealthdepartment.com).
//
// The portal is a static Webflow front-end driven by a JSON endpoint: the page
// POSTs {task, data} to "/?page=ajax". searchInspections returns the rows the
// jurisdiction landing page lists; the printable view carries the violations.
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
  if (parsed && parsed.err) throw new PortalError(`${task} returned error: ${parsed.err}`);
  return parsed;
}

const pad = (n) => String(n).padStart(2, '0');
export const isoDate = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;

/**
 * Inspections published for one jurisdiction between two dates (inclusive).
 * Pages through the portal until it stops returning full pages.
 */
export async function fetchInspections(jurisdiction, startDate, endDate, { pageSize = 50, maxPages = 10 } = {}) {
  const rows = [];
  for (let page = 0; page < maxPages; page++) {
    const batch = await ajax(
      'searchInspections',
      {
        path: jurisdiction.path,
        programName: '',
        filters: { date: `${startDate} to ${endDate}` },
        start: page * pageSize,
        count: pageSize,
        searchQueryOverride: null,
        searchStr: '',
        lat: 0,
        lng: 0,
        sort: {},
      },
      { referer: `${HOST}/${jurisdiction.path}` }
    );
    const list = Array.isArray(batch) ? batch : batch?.inspections || [];
    rows.push(...list);
    if (list.length < pageSize) break;
  }
  return rows.map((row) => normalize(row, jurisdiction));
}

function normalize(row, jurisdiction) {
  const address = [row.addressLine1, row.addressLine2].filter(Boolean).join(' ').trim();
  const cityLine = [row.city, row.state].filter(Boolean).join(', ');
  return {
    id: row.inspectionID,
    permitId: row.permitID,
    jurisdiction: jurisdiction.name,
    jurisdictionKey: jurisdiction.key,
    jurisdictionPath: jurisdiction.path,
    establishment: (row.establishmentName || 'Unknown establishment').trim(),
    address: [address, cityLine].filter(Boolean).join(', '),
    date: (row.inspectionDate || '').slice(0, 10),
    type: (row.inspectionType || '').replace('(OLD)', '').trim(),
    purpose: (row.purpose || '').trim(),
    score: row.score ?? null,
    scoreDisplay: (row.scoreDisplay || '').trim(),
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
 * Violation lines for one inspection.
 *
 * Tries the JSON task first; falls back to the portal's printable view, which
 * renders the same report as server-side HTML.
 */
export async function fetchViolations(jurisdiction, inspectionId) {
  let detail = null;
  try {
    detail = await ajax(
      'getInspection',
      { path: jurisdiction.path, inspectionID: inspectionId, pKey: inspectionId },
      { referer: `${HOST}/${jurisdiction.path}/inspection/?inspectionID=${inspectionId}` }
    );
  } catch {
    detail = null;
  }

  const fromJson = detail && extractViolationsFromJson(detail);
  if (fromJson && fromJson.length) return { violations: fromJson, source: 'json' };

  const printUrl =
    `${HOST}/${jurisdiction.path}/print/?task=getPrintable` +
    `&path=${encodeURIComponent(jurisdiction.path)}&pKey=${encodeURIComponent(inspectionId)}`;
  const html = await request(printUrl, {
    headers: { Accept: 'text/html,*/*', Referer: `${HOST}/${jurisdiction.path}` },
  });
  return {
    violations: extractViolationsFromHtml(html),
    source: 'print',
    ...extractHeaderFromHtml(html),
  };
}

/** Best-effort establishment name and date from the printable report. */
function extractHeaderFromHtml(html) {
  const text = stripTags(html);
  const out = {};

  const nameMatch =
    text.match(/(?:Establishment|Facility|Name)\s*:?\s*\n?\s*([^\n]{3,80})/i) || null;
  if (nameMatch) out.establishment = nameMatch[1].trim();

  const dateMatch = text.match(/(?:Inspection\s*Date|Date\s*of\s*Inspection)\s*:?\s*\n?\s*([^\n]{6,30})/i);
  if (dateMatch) {
    const parsed = new Date(dateMatch[1].trim());
    if (!Number.isNaN(parsed.getTime())) out.date = isoDate(parsed);
  }
  return out;
}

function extractViolationsFromJson(detail) {
  // The payload shape varies by portal version; look for the first array of
  // objects that carries violation-ish keys.
  const candidates = [];
  const walk = (node, depth = 0) => {
    if (!node || depth > 4) return;
    if (Array.isArray(node)) {
      if (node.length && typeof node[0] === 'object' && node[0]) {
        const keys = Object.keys(node[0]).map((k) => k.toLowerCase());
        if (keys.some((k) => k.includes('violation') || k.includes('observation') || k.includes('comment'))) {
          candidates.push(node);
        }
      }
      node.forEach((n) => walk(n, depth + 1));
      return;
    }
    if (typeof node === 'object') Object.values(node).forEach((v) => walk(v, depth + 1));
  };
  walk(detail);
  if (!candidates.length) return null;

  return candidates[0]
    .map((v) => {
      const get = (...names) => {
        for (const n of names) {
          const hit = Object.entries(v).find(([k]) => k.toLowerCase() === n);
          if (hit && hit[1]) return String(hit[1]).trim();
        }
        return '';
      };
      const text = get('violationtext', 'description', 'observation', 'comments', 'comment', 'text');
      const code = get('code', 'violationcode', 'itemnumber', 'item');
      const severity = get('severity', 'violationtype', 'category', 'priority');
      const repeat = /true|yes|1/i.test(get('repeat', 'isrepeat', 'repeatviolation'));
      const corrected = /true|yes|1/i.test(get('correctedonsite', 'cos', 'corrected'));
      return text ? { code, text, severity, repeat, corrected } : null;
    })
    .filter(Boolean);
}

function extractViolationsFromHtml(html) {
  const text = stripTags(html);
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const out = [];
  // Violation lines in the printable report lead with an item/code reference,
  // e.g. "3-501.16 (A)(2)(a) Potentially hazardous food ... held at 52°F".
  const codeLead = /^(\d+[-–]\d+[.\d]*(?:\s*\([A-Za-z0-9]+\))*|\d{1,3}[.)])\s+(.{15,})$/;
  for (const line of lines) {
    const m = line.match(codeLead);
    if (!m) continue;
    const body = m[2].trim();
    if (/^(page|inspection|establishment|address|permit|date|time)\b/i.test(body)) continue;
    out.push({
      code: m[1].trim(),
      text: body,
      severity: /priority foundation/i.test(line)
        ? 'Priority Foundation'
        : /priority/i.test(line)
          ? 'Priority'
          : /core/i.test(line)
            ? 'Core'
            : '',
      repeat: /repeat/i.test(line),
      corrected: /corrected on[- ]site|COS\b/i.test(line),
    });
  }
  return out;
}
