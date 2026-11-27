/* Structural contract for the shipped DOM reconciler. The full browser
 * acceptance verifies real nodes, month layout, focus and TrainingService. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = readFileSync(process.env.HEALTHZIP_COMPONENT_SOURCE || path.join(__dirname,
  '../../src/healthzip/ui/strength_component/workbench.js'), 'utf8');
const code = source.slice(source.indexOf('  function nodeKey('), source.indexOf('  function patchNode('));
const nodeKey = vm.runInNewContext(`${code};nodeKey`);
function element(dataset = {}, attributes = {}) {
  return { nodeType: 1, id: attributes.id || '', dataset,
    getAttribute: key => attributes[key] ?? null,
    hasAttribute: key => Object.hasOwn(attributes, key) };
}

test('each actual date retains one stable identity across selection and month changes', () => {
  const dates = ['2024-02-28', '2024-02-29', '2026-02-28', '2026-11-01', '2026-11-30', '2026-12-31'];
  const keys = dates.map(date => nodeKey(element({action: 'select-date', date})));
  assert.equal(new Set(keys).size, dates.length);
  dates.forEach((date, index) => assert.equal(
    nodeKey(element({action: 'select-date', date}, {'aria-pressed': 'true', 'aria-label': `${date}，3场训练`})),
    keys[index]));
});

test('back and close controls for the same action have separate role identities', () => {
  const back = element({action: 'close-catalog', control: 'back'}, {'aria-label': '返回'});
  const close = element({action: 'close-catalog'}, {'aria-label': '关闭动作选择'});
  assert.notEqual(nodeKey(back), nodeKey(close));
  assert.equal(nodeKey(back), nodeKey(element({action: 'close-catalog', control: 'back'})));
});

test('session, exercise and set controls remain tied to real entity and field identity', () => {
  for (const action of ['open-session', 'catalog-select', 'toggle-card', 'complete-set']) {
    assert.notEqual(nodeKey(element({action, id: 'record-a'})), nodeKey(element({action, id: 'record-b'})));
  }
  assert.notEqual(nodeKey(element({set: 'row-a', field: 'rir'})), nodeKey(element({set: 'row-a', field: 'reps'})));
  assert.notEqual(nodeKey(element({set: 'row-a', field: 'rir'})), nodeKey(element({set: 'row-b', field: 'rir'})));
  assert.equal(nodeKey({nodeType: 3}), null);
});
