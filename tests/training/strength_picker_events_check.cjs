/* Execute the shipped component's event handlers without browser dependencies.
 * This checks transport/navigation/draft state; it is not layout or browser QA.
 */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = readFileSync(path.join(__dirname,
  '../../src/healthzip/ui/strength_component/workbench.js'), 'utf8');

function exercise(id, catalogId, setId) {
  return { id, catalog_id: catalogId, catalog_active: true,
    exercise: { name: catalogId, recording_mode: 'repetitions' }, condition: {},
    sets: [{ set_uuid: setId, revision: 1, completion_state: 'draft' }] };
}
function harness() {
  const appEvents = {}, windowEvents = {}, storage = new Map(), messages = [], timers = new Map();
  let sequence = 0;
  const scroll = { scrollTop: 0 };
  const app = { dataset: {}, innerHTML: '', addEventListener: (type, fn) => { appEvents[type] = fn; },
    querySelector: selector => selector === '.scroll' ? scroll : null,
    querySelectorAll: () => [] };
  const parent = { postMessage: message => { messages.push(message); } };
  const window = { parent, screen: { availHeight: 844 },
    addEventListener: (type, fn) => { windowEvents[type] = fn; } };
  const microtasks = [];
  vm.runInNewContext(source, {
    window, document: { getElementById: id => id === 'app' ? app : null, activeElement: null },
    localStorage: { getItem: key => storage.get(key) || null,
      setItem: (key, value) => { storage.set(key, value); } },
    crypto: { randomUUID: () => `request-${++sequence}` },
    requestAnimationFrame: () => {}, setInterval: () => {},
    setTimeout: fn => { const id = ++sequence; timers.set(id, fn); return id; },
    clearTimeout: id => timers.delete(id), queueMicrotask: fn => microtasks.push(fn),
    Intl, Date, CSS: { escape: value => value },
  });
  let snapshot = {
    db_scope: 'synthetic-picker', timezone_name: 'Asia/Shanghai',
    now: '2026-11-20T09:00:00+08:00', today: '2026-11-20', month: '2026-11',
    calendar: [], regions: [], equipment_types: [],
    session: { id: 'session-1', session_uuid: 'session-1', revision: 1,
      name: 'Synthetic training', session_status: 'in_progress',
      started_at: '2026-11-20T08:00:00+08:00',
      exercises: [exercise('original-instance', 'original-action', 'original-set')] },
    catalog: { items: [{ exercise_id: 'new-action', name: 'New action' },
      { exercise_id: 'original-action', name: 'Original action' }], total: 2 },
  };
  function render(receipt) {
    windowEvents.message({ source: parent, data: { type: 'streamlit:render',
      args: { snapshot, receipt } } });
    while (microtasks.length) microtasks.shift()();
  }
  function click(action, id) {
    const target = { dataset: { action, id }, disabled: false };
    appEvents.click({ target: { closest: () => target } });
  }
  function input(field, value) {
    appEvents.input({ target: { dataset: { set: 'original-set', field }, value } });
  }
  const state = () => JSON.parse(storage.get('healthzip.strength.v1:synthetic-picker'));
  const commands = () => messages.filter(m => m.type === 'streamlit:setComponentValue').map(m => m.value);
  function acknowledge(action, data = {}, status = 'saved') {
    const command = commands().at(-1);
    assert.equal(command.action, action);
    render({ id: command.id, action, status, data, message: status === 'error' ? 'Synthetic failure' : '' });
  }
  function openPicker() { click('open-catalog'); acknowledge('catalog', snapshot.catalog); }
  render(); click('workbench');
  return { click, input, state, commands, acknowledge, openPicker, snapshot,
    flushTimers: () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()); },
    search: value => appEvents.input({ target: { dataset: { search: 'catalog' }, value } }),
  };
}

function assertDraft(h) {
  const draft = h.state().drafts['session-1:original-set'];
  assert.deepEqual(draft.values, { load_value: '32.5', reps: '8', rir: '0' });
  assert.equal(draft.dirty, true);
  assert.equal(draft.base_revision, 1);
}
function fillDraft(h) { h.input('load_value', '32.5'); h.input('reps', '8'); h.input('rir', '0'); }

test('one selection returns to training, expands the acknowledged action and preserves inputs', () => {
  const h = harness(); fillDraft(h); h.openPicker();
  h.click('catalog-select', 'new-action');
  const command = h.commands().at(-1);
  assert.equal(command.action, 'add_exercises');
  assert.deepEqual(JSON.parse(JSON.stringify(command.payload.exercises)),
    [{ exercise_id: 'new-action', allow_repeat: false }]);
  assert.equal(h.state().view, 'catalog'); // No saved state before acknowledgment.
  const count = h.commands().length;
  h.click('catalog-select', 'new-action');
  assert.equal(h.commands().length, count); // No second write while pending.
  h.snapshot.session.exercises.push(exercise('added-instance', 'new-action', 'new-set'));
  // A later, unrelated instance must not steal expansion from this receipt.
  h.snapshot.session.exercises.push(exercise('other-instance', 'other-action', 'other-set'));
  h.snapshot.session.revision = 2;
  h.acknowledge('add_exercises', { added_instance_ids: ['added-instance'] });
  assert.equal(h.state().view, 'workbench');
  assert.equal(h.state().expanded, 'added-instance');
  assert.equal(h.state().pending, null);
  assertDraft(h);
  const fresh = h.state().drafts['session-1:new-set'];
  assert.deepEqual(fresh.values, {});
  assert.equal(fresh.dirty, false);
  h.openPicker(); assert.equal(h.state().view, 'catalog'); assertDraft(h);
});

test('closing without selecting cancels queued search and preserves all existing fields', () => {
  const h = harness(); fillDraft(h); h.openPicker();
  const count = h.commands().length;
  h.search('a debounced query'); h.click('close-catalog'); h.flushTimers();
  assert.equal(h.commands().length, count);
  assert.equal(h.state().view, 'workbench');
  assertDraft(h);
  h.openPicker();
  assert.equal(h.commands().at(-1).payload.query, '');
});

test('failed addition stays in picker, accepts retry and makes repeated action explicit', () => {
  const h = harness(); fillDraft(h); h.openPicker();
  h.click('catalog-select', 'original-action');
  assert.equal(h.commands().at(-1).payload.exercises[0].allow_repeat, true);
  h.acknowledge('add_exercises', {}, 'error');
  assert.equal(h.state().view, 'catalog');
  assert.equal(h.state().pending, null); assertDraft(h);
  h.click('catalog-select', 'original-action');
  const firstDelivery = h.commands().at(-1);
  h.click('retry');
  const retry = h.commands().at(-1);
  assert.equal(retry.id, firstDelivery.id);
  assert.deepEqual(JSON.parse(JSON.stringify(retry.payload)), JSON.parse(JSON.stringify(firstDelivery.payload)));
  h.snapshot.session.exercises.push(exercise('repeated-instance', 'original-action', 'repeated-set'));
  h.acknowledge('add_exercises', { added_instance_ids: ['repeated-instance'] });
  assert.equal(h.state().view, 'workbench');
  assert.equal(h.state().expanded, 'repeated-instance'); assertDraft(h);
});
