#!/usr/bin/env node
// Runs the digest from anywhere Node runs — a laptop, a home server, cron, CI.
// Same code path as the Vercel function, so it's the fallback if the portal's
// firewall refuses Vercel's egress.
//
//   node scripts/send-digest.mjs               # last 7 days → Telegram
//   node scripts/send-digest.mjs --dry-run     # print, don't send
//   node scripts/send-digest.mjs --days 14
//   node scripts/send-digest.mjs --sample      # send a clearly-labelled sample
//
// Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, optional INSPECTIONS_PROXY_TEMPLATE.
//
// Exit codes: 0 ok · 1 error · 2 portal refused this network.

import { fetchAll, isoDate, PortalBlocked } from '../lib/inspections/portal.mjs';
import { buildDigest } from '../lib/inspections/format.mjs';
import { sendMessage } from '../lib/inspections/telegram.mjs';

const args = process.argv.slice(2);
const has = (flag) => args.includes(flag);
const value = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i > -1 && args[i + 1] ? args[i + 1] : fallback;
};

const days = Math.min(Math.max(parseInt(value('--days', '7'), 10) || 7, 1), 60);
const dryRun = has('--dry-run');
const sample = has('--sample');

const end = new Date();
const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
const startIso = isoDate(start);
const endIso = isoDate(end);

function sampleRows() {
  const guid = (n) => `${String(n).padStart(8, '0')}-0000-0000-0000-000000000000`;
  return [
    ['Sample Diner', 'va-henrico', 'Henrico County', 'H', 'Routine'],
    ['Sample Taqueria', 'va-richmond', 'Richmond City', 'R', 'Follow-up'],
  ].map(([name, path, jurisdiction, key, type], i) => ({
    id: guid(i + 1),
    jurisdiction,
    jurisdictionKey: key,
    jurisdictionPath: path,
    establishment: name,
    address: '000 Example St, Richmond, VA',
    date: endIso,
    type,
    purpose: type,
    score: null,
    scoreDisplay: '',
    url: `https://inspections.myhealthdepartment.com/${path}/inspection/?inspectionID=${guid(i + 1)}`,
  }));
}

async function main() {
  let messages;

  if (sample) {
    messages = buildDigest(sampleRows(), startIso, endIso);
    messages[0].text =
      '⚠️ <b>SAMPLE — not real inspection data</b>\n' +
      '<i>Sent to check the Telegram wiring. The establishments below are made up.</i>\n\n' +
      messages[0].text;
  } else {
    let rows;
    try {
      rows = await fetchAll(startIso, endIso);
    } catch (e) {
      const blocked = e instanceof PortalBlocked;
      console.error(`${blocked ? 'BLOCKED' : 'FETCH FAILED'}: ${e.message}`);
      process.exit(blocked ? 2 : 1);
    }
    console.error(`Fetched ${rows.length} inspection(s) for ${startIso} … ${endIso}`);
    messages = buildDigest(rows, startIso, endIso);
  }

  if (dryRun) {
    for (const m of messages) {
      console.log(m.text);
      console.log('[keyboard]', JSON.stringify(m.keyboard));
      console.log('—'.repeat(40));
    }
    return;
  }

  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!chatId) throw new Error('TELEGRAM_CHAT_ID is not set');

  for (const m of messages) {
    await sendMessage(chatId, m.text, { keyboard: m.keyboard });
  }
  console.error(`Sent ${messages.length} message(s).`);
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
