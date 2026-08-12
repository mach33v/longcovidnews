#!/usr/bin/env node
// Offline checks for the digest renderer — no network, no Telegram.
//   node scripts/check-digest.mjs           run the assertions
//   node scripts/check-digest.mjs --print   also print a sample digest
//
// Covers the things that break silently in production: HTML escaping, the
// 4096-character message limit, callback_data staying under Telegram's 64 bytes,
// and every entry keeping a button.

import assert from 'node:assert/strict';
import { buildDigest, buildViolationsMessage } from '../lib/inspections/format.mjs';
import { splitMessage, MAX_LEN } from '../lib/inspections/telegram.mjs';

const guid = (n) => `${String(n).padStart(8, '0')}-1111-2222-3333-444455556666`;

function sample(n, overrides = {}) {
  return {
    id: guid(n),
    jurisdiction: n % 2 ? 'Henrico County' : 'Richmond City',
    jurisdictionKey: n % 2 ? 'H' : 'R',
    jurisdictionPath: n % 2 ? 'va-henrico' : 'va-richmond',
    establishment: `Test Diner #${n}`,
    address: `${100 + n} Broad St, Richmond, VA`,
    date: `2026-08-${String((n % 7) + 3).padStart(2, '0')}`,
    type: 'Routine',
    purpose: 'Routine',
    score: null,
    scoreDisplay: '',
    url: `https://inspections.myhealthdepartment.com/va-henrico/inspection/?inspectionID=${guid(n)}`,
    ...overrides,
  };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('empty week produces one message and no keyboard', () => {
  const messages = buildDigest([], '2026-08-05', '2026-08-12');
  assert.equal(messages.length, 1);
  assert.equal(messages[0].keyboard, null);
  assert.match(messages[0].text, /No inspections were published/);
});

test('every inspection gets exactly one numbered button', () => {
  const rows = Array.from({ length: 23 }, (_, i) => sample(i + 1));
  const messages = buildDigest(rows, '2026-08-05', '2026-08-12');
  const buttons = messages.flatMap((m) => (m.keyboard || []).flat());
  assert.equal(buttons.length, rows.length);

  const labels = buttons.map((b) => Number(b.text)).sort((a, b) => a - b);
  assert.deepEqual(labels, rows.map((_, i) => i + 1));

  for (const button of buttons) {
    assert.ok(
      Buffer.byteLength(button.callback_data) <= 64,
      `callback_data too long: ${button.callback_data}`
    );
    assert.match(button.callback_data, /^v\|[HR]\|[0-9a-fA-F-]{36}$/);
  }
});

test('messages stay under the Telegram length limit', () => {
  const rows = Array.from({ length: 120 }, (_, i) =>
    sample(i + 1, { establishment: `Establishment With A Fairly Long Name ${i}` })
  );
  const messages = buildDigest(rows, '2026-08-05', '2026-08-12');
  assert.ok(messages.length > 1, 'expected the digest to paginate');
  for (const m of messages) {
    assert.ok(m.text.length <= MAX_LEN, `message of ${m.text.length} chars exceeds the limit`);
  }
  const buttons = messages.flatMap((m) => (m.keyboard || []).flat());
  assert.equal(buttons.length, rows.length, 'pagination dropped buttons');
});

test('html in establishment names is escaped', () => {
  const rows = [sample(1, { establishment: 'Bob & Sons <script>alert(1)</script>' })];
  const [message] = buildDigest(rows, '2026-08-05', '2026-08-12');
  assert.ok(!message.text.includes('<script>'), 'raw script tag survived escaping');
  assert.ok(message.text.includes('Bob &amp; Sons'));
});

test('violation replies sort priority first and mark repeats', () => {
  const text = buildViolationsMessage({
    establishment: 'Test Diner',
    date: '2026-08-07',
    jurisdictionName: 'Henrico County',
    url: 'https://example.com/report',
    violations: [
      { code: '6-501.11', text: 'Floor tiles cracked', severity: 'Core', repeat: false, corrected: false },
      { code: '3-501.16', text: 'Chicken held at 52F', severity: 'Priority', repeat: true, corrected: true },
    ],
  });
  const priorityAt = text.indexOf('Chicken held at 52F');
  const coreAt = text.indexOf('Floor tiles cracked');
  assert.ok(priorityAt > -1 && coreAt > -1);
  assert.ok(priorityAt < coreAt, 'priority violation should come first');
  assert.match(text, /repeat/);
  assert.match(text, /corrected on site/);
  assert.match(text, /2 violations cited/);
});

test('violation reply handles an inspection with none', () => {
  const text = buildViolationsMessage({
    establishment: 'Clean Cafe',
    date: '2026-08-07',
    jurisdictionName: 'Richmond City',
    url: 'https://example.com/report',
    violations: [],
  });
  assert.match(text, /No violations were listed/);
});

test('splitMessage never breaks a line in half', () => {
  const line = `<b>${'x'.repeat(200)}</b>`;
  const parts = splitMessage(Array.from({ length: 100 }, () => line).join('\n'));
  for (const part of parts) {
    assert.ok(part.length <= MAX_LEN);
    for (const l of part.split('\n')) {
      assert.ok(l === line, 'a line was split mid-way');
    }
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (e) {
    failed += 1;
    console.error(`FAIL  ${name}\n      ${e.message}`);
  }
}

if (process.argv.includes('--print')) {
  const rows = [
    sample(1, { establishment: "Sally Bell's Kitchen", type: 'Routine', purpose: 'Routine' }),
    sample(2, { establishment: 'Mama J&#39;s', type: 'Follow-up', purpose: 'Follow-up' }),
    sample(3, { establishment: 'The Roosevelt', type: 'Routine', purpose: 'Complaint' }),
  ];
  console.log('\n--- sample digest ---');
  for (const m of buildDigest(rows, '2026-08-05', '2026-08-12')) {
    console.log(m.text);
    console.log('[keyboard]', JSON.stringify(m.keyboard));
    console.log('---');
  }
}

console.log(failed ? `\n${failed} check(s) failed` : `\nall ${tests.length} checks passed`);
process.exit(failed ? 1 : 0);
