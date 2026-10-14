#!/usr/bin/env node
// Offline MPPScan parser smoke check. Fetch is replaced with the supplied file;
// this never probes endpoints or submits payments.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const [file, moduleName = '@agentcash/discovery'] = process.argv.slice(2);
if (!file) throw new Error('usage: node validate_payment_catalog.mjs <openapi.json> [discovery-module-path]');
const {getOpenAPI, getL3ForOpenAPI} = await import(moduleName);
const raw = fs.readFileSync(file, 'utf8');
const document = JSON.parse(raw);
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => new Response(raw, {status: 200, headers: {'content-type': 'application/json'}});
try {
  const parsed = await getOpenAPI(document.servers[0].url);
  assert(!parsed.isErr() && parsed.value && !parsed.value.parseFailure, 'OpenAPI parsing failed');
  const expected = Object.values(document.paths).reduce((n, item) => n + Object.values(item).filter(op => op?.['x-payment-info']).length, 0);
  assert.equal(parsed.value.routes.length, expected, 'Parser dropped operations');
  for (const route of parsed.value.routes) {
    const advisory = getL3ForOpenAPI(parsed.value, route.path, route.method);
    const op = document.paths[route.path][route.method.toLowerCase()];
    assert.equal(advisory?.authMode, 'paid');
    assert(advisory.protocols.includes('mpp'));
    assert.equal(advisory.estimatedPrice, op['x-payment-info'].price.amount + ' USD');
    assert(advisory.outputSchema, 'Missing output schema: ' + route.path);
    if (op.requestBody || op.parameters?.length) assert(advisory.inputSchema, 'Missing input schema: ' + route.path);
  }
  console.log(`MPPScan parser recognized ${expected} paid MPP operations, USD prices and documented input/output schemas.`);
} finally {
  globalThis.fetch = originalFetch;
}
