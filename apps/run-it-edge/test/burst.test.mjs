import { test } from 'node:test';
import assert from 'node:assert/strict';
import { measure } from '../burst.mjs';

test('the actual Worker wrapper holds all three limits through scripted bursts and restarts', async () => {
  const result = await measure();
  assert.equal(result.primaryBurstRequests, 2800);
  assert.equal(result.totalPostRequests, 2804);
  assert.equal(result.realExternalRequests, 0);
  assert.equal(result.perVisitor.accepted, 3);
  assert.equal(result.perVisitor.visitorQuota, 200);
  assert.equal(result.daily.accepted, 40);
  assert.equal(result.daily.dailyCap, 200);
  assert.equal(result.breaker.circuitOpen, 200);
  assert.equal(result.breaker.midnightDoesNotReset, true);
});
