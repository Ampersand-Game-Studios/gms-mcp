import assert from 'node:assert/strict';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';

import worker from '../src/index.js';

const INGEST_URL = 'https://gms-mcp-telemetry.ampersandgamestudios.com/v1/events';

function validEvent(index = 0) {
  return {
    schema_version: 1,
    event_id: `event-${Date.now()}-${index}`,
    session_id: `session-${Date.now()}`,
    timestamp: new Date().toISOString(),
    surface: 'cli',
    event_type: 'tool',
    action: 'test',
    tool_name: 'gm_test',
    tool_family: 'test',
    result: 'ok',
    gms_mcp_version: '0.0.0-test',
    os_family: 'test',
    python_version: '3.12',
    interactive: false,
    ci: false,
    test_env: true,
  };
}

function testEnv() {
  const sent = [];
  return {
    sent,
    TELEMETRY_QUEUE: {
      send: async (message) => {
        sent.push(message);
      },
    },
  };
}

async function postEvents(env, events, headers = {}) {
  return await worker.fetch(
    new Request(INGEST_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'cf-connecting-ip': '203.0.113.1',
        ...headers,
      },
      body: JSON.stringify({ events }),
    }),
    env
  );
}

test('rejects gzip payloads that exceed the decompressed size limit', async () => {
  const env = testEnv();
  const body = JSON.stringify({
    padding: 'x'.repeat(300 * 1024),
    events: [validEvent()],
  });

  const response = await worker.fetch(
    new Request(INGEST_URL, {
      method: 'POST',
      headers: {
        'content-encoding': 'gzip',
        'content-type': 'application/json',
        'cf-connecting-ip': '203.0.113.2',
      },
      body: gzipSync(body),
    }),
    env
  );

  assert.equal(response.status, 413);
  assert.equal(env.sent.length, 0);
});

test('rate limits repeated ingest requests from the same client', async () => {
  const env = testEnv();
  let response;

  for (let index = 0; index < 61; index += 1) {
    response = await postEvents(env, [validEvent(index)], {
      'cf-connecting-ip': '203.0.113.3',
    });
  }

  assert.equal(response.status, 429);
  assert.equal(env.sent.length, 60);
});
