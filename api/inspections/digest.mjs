// Weekly digest of Henrico County + Richmond City restaurant inspections.
//
// Invoked by Vercel Cron (see vercel.json). Also callable by hand:
//   /api/inspections/digest?dry=1        render the digest, don't send it
//   /api/inspections/digest?diagnose=1   report what the portal returns from here
//   /api/inspections/digest?days=14      widen the window
//
// Auth: when CRON_SECRET is set, requests must carry
// "Authorization: Bearer <CRON_SECRET>" — Vercel Cron sends this automatically.

import { fetchAll, PortalBlocked, PortalError, HOST, JURISDICTIONS, isoDate } from '../../lib/inspections/portal.mjs';
import { buildDigest } from '../../lib/inspections/format.mjs';
import { sendMessage } from '../../lib/inspections/telegram.mjs';

export const config = { maxDuration: 60 };

// Vercel Hobby cron granularity is a day, so a weekly schedule is enforced here
// too: a run on the wrong weekday exits without sending.
const DIGEST_WEEKDAY = Number(process.env.DIGEST_WEEKDAY ?? 1); // 0=Sun … 1=Mon

function authorized(req) {
  const secret = process.env.CRON_SECRET;
  if (!secret) return true;
  return req.headers.authorization === `Bearer ${secret}`;
}

function windowFor(days) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  return { start: isoDate(start), end: isoDate(end) };
}

export default async function handler(req, res) {
  const query = req.query || {};
  const isManual = query.dry === '1' || query.diagnose === '1' || query.force === '1';

  if (!authorized(req)) return res.status(401).json({ error: 'unauthorized' });

  const days = Math.min(Math.max(parseInt(query.days, 10) || 7, 1), 60);
  const { start, end } = windowFor(days);

  if (query.diagnose === '1') return diagnose(res, start, end);

  const weekday = new Date().getUTCDay();
  if (!isManual && weekday !== DIGEST_WEEKDAY) {
    return res.status(200).json({ skipped: `not digest weekday (${weekday} != ${DIGEST_WEEKDAY})` });
  }

  let inspections;
  try {
    inspections = await fetchAll(start, end);
  } catch (e) {
    const blocked = e instanceof PortalBlocked;
    console.error('inspection fetch failed:', e);
    if (!blocked && !(e instanceof PortalError)) throw e;
    // A silent empty digest would look like a quiet week — say what happened.
    if (!isManual && process.env.TELEGRAM_CHAT_ID) {
      await sendMessage(
        process.env.TELEGRAM_CHAT_ID,
        `⚠️ <b>Inspection digest failed</b>\n<i>${escapeForError(e.message)}</i>`
      ).catch(() => {});
    }
    return res.status(blocked ? 502 : 500).json({ error: e.message, blocked });
  }

  const messages = buildDigest(inspections, start, end);

  if (query.dry === '1') {
    return res.status(200).json({
      window: { start, end },
      count: inspections.length,
      messages,
    });
  }

  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!chatId) return res.status(500).json({ error: 'TELEGRAM_CHAT_ID is not set' });

  const sent = [];
  for (const message of messages) {
    const result = await sendMessage(chatId, message.text, { keyboard: message.keyboard });
    sent.push(result.message_id);
  }

  return res.status(200).json({ window: { start, end }, count: inspections.length, sent });
}

const escapeForError = (s) => String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** One request that shows exactly how the portal responds from this host. */
async function diagnose(res, start, end) {
  const report = { host: HOST, window: { start, end }, egress: null, checks: [] };

  try {
    const r = await fetch('https://api.ipify.org?format=json');
    report.egress = await r.json();
  } catch (e) {
    report.egress = String(e);
  }

  report.jurisdictions = JURISDICTIONS.map((j) => j.path);
  try {
    const rows = await fetchAll(start, end);
    report.checks.push({ ok: true, total: rows.length, sample: rows.slice(0, 3) });
  } catch (e) {
    report.checks.push({ ok: false, error: e.message, blocked: e instanceof PortalBlocked });
  }

  report.proxyConfigured = Boolean((process.env.INSPECTIONS_PROXY_TEMPLATE || '').trim());
  report.telegramConfigured = Boolean(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID);
  return res.status(200).json(report);
}
