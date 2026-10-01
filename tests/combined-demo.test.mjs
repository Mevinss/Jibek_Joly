import test from 'node:test';
import assert from 'node:assert/strict';
import { approachAdvice } from '../services/ai/web/combined/approach.mjs';

test('a six minute slot at four km requires 40 km/h', () => {
  const r = approachAdvice({ distanceKm: 4, nowMin: 0, slotMin: 6, capKmh: 40 });
  assert.equal(r.status, 'AVAILABLE');
  assert.equal(r.speedKmh, 40);
});
test('unreachable and expired slots do not produce a speed recommendation', () => {
  assert.equal(approachAdvice({ distanceKm: 4, nowMin: 0, slotMin: 3, capKmh: 40 }).status, 'UNREACHABLE');
  assert.equal(approachAdvice({ distanceKm: 4, nowMin: 6, slotMin: 6, capKmh: 40 }).status, 'EXPIRED');
});
test('missing, negative and nonfinite inputs are rejected', () => {
  for (const distanceKm of [undefined, -1, NaN, Infinity, 0]) {
    assert.equal(approachAdvice({ distanceKm, nowMin: 0, slotMin: 6, capKmh: 40 }).status, 'INVALID');
  }
});
test('a very early approach window requests holding instead of a crawl speed', () => {
  const r = approachAdvice({ distanceKm: 1, nowMin: 0, slotMin: 30, capKmh: 40 });
  assert.equal(r.status, 'HOLD');
  assert.equal(r.speedKmh, null);
});
