import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";
import worker, {
  buildDailyAggregate,
  handleQueue,
  retentionSettings,
  runRetention,
  sanitizeEvent,
} from "../src/index.js";

const host = "https://gms-mcp-telemetry.ampersandgamestudios.com";
function event(overrides = {}) {
  return {
    schema_version: 1,
    event_id: "a".repeat(32),
    session_id: "b".repeat(32),
    timestamp: new Date().toISOString(),
    surface: "cli",
    event_type: "cli.command",
    action: "asset.create",
    tool_name: "asset.create",
    tool_family: "asset",
    result: "ok",
    gms_mcp_version: "0.0.13",
    os_family: "macos",
    python_version: "3.12",
    interactive: false,
    ci: false,
    test_env: false,
    ...overrides,
  };
}
class Bucket {
  constructor(keys = []) {
    this.objects = new Map(keys.map((key) => [key, "fixture"]));
    this.deleted = [];
    this.puts = [];
    this.pageSize = 2;
  }
  async list({ prefix, cursor }) {
    const all = [...this.objects.keys()]
      .filter((key) => key.startsWith(prefix))
      .sort();
    const remaining = all.filter((key) => !cursor || key > cursor);
    const keys = remaining.slice(0, this.pageSize);
    return {
      objects: keys.map((key) => ({ key })),
      truncated: remaining.length > keys.length,
      cursor: keys.at(-1),
    };
  }
  async delete(keys) {
    for (const key of Array.isArray(keys) ? keys : [keys]) {
      this.deleted.push(key);
      this.objects.delete(key);
    }
  }
  async put(key, value) {
    this.objects.set(key, value);
    this.puts.push(key);
  }
  async get() {
    throw new Error("Retention must not download production bodies.");
  }
}
const env = (bucket) => ({
  TELEMETRY_BUCKET: bucket,
  RAW_RETENTION_DAYS: "90",
  AGGREGATE_RETENTION_MONTHS: "24",
  TELEMETRY_ARCHIVE_TOKEN: "local-test-token",
});

test("backlogged retention traverses every page, deletes expired only, and is idempotent", async () => {
  const expired = [
    "raw/2026/01/01/a",
    "raw/2026/02/01/b",
    "raw/2026/07/05/c",
    "raw/2026/07/06/boundary",
    "aggregates/2023/01/01/a",
    "aggregates/2024/10/03/b",
    "aggregates/2024/10/04/boundary",
  ];
  const retained = [
    "raw/2026/07/07/retained",
    "raw/2026/10/04/current",
    "raw/2026/99/99/invalid",
    "raw/unexpected/a",
    "aggregates/2024/10/05/retained",
    "aggregates/2026/01/01/current",
    "private/unrelated",
  ];
  const bucket = new Bucket([...expired, ...retained]);
  const options = { now: new Date("2026-10-04T12:00:00Z") };
  const preview = await runRetention(env(bucket), { ...options, dryRun: true });
  assert.deepEqual(preview.objects, { raw: 4, aggregates: 3 });
  assert.equal(bucket.deleted.length, 0);
  const result = await runRetention(env(bucket), options);
  assert.deepEqual(result.objects, preview.objects);
  assert.deepEqual([...bucket.objects.keys()].sort(), retained.sort());
  assert.deepEqual((await runRetention(env(bucket), options)).objects, {
    raw: 0,
    aggregates: 0,
  });
});
test("calendar month cutoff clamps end of month and rejects unsafe configuration", () => {
  assert.equal(
    retentionSettings(
      { RAW_RETENTION_DAYS: "90", AGGREGATE_RETENTION_MONTHS: "1" },
      new Date("2026-03-31T12:00:00Z"),
    ).aggregates,
    "2026-02-28",
  );
  for (const invalid of ["bad", "0", "-1", "90x", "999999", "1.5"])
    assert.throws(() =>
      retentionSettings({ RAW_RETENTION_DAYS: invalid }, new Date()),
    );
});
test("every schema field is validated and diagnostics cannot enter storage", () => {
  assert.ok(sanitizeEvent(event()));
  for (const override of [
    { extra: "/secret/project" },
    { tool_name: "/secret/path" },
    { interactive: "secret" },
    { ci: true },
    { test_env: true },
    { schema_version: 2 },
    { event_id: "invalid" },
    { install_hash: "invalid" },
    { timestamp: "invalid" },
    { timestamp: "1999-01-01T00:00:00Z" },
    { duration_ms: -1 },
    { result: "unexpected" },
    { surface: "invalid" },
  ])
    assert.equal(sanitizeEvent(event(override)), null);
});
test("identity/gzip decompressed bodies are bounded even without content-length", async () => {
  for (const gzip of [false, true]) {
    const payload = JSON.stringify({
      schema_version: 1,
      events: [event({ action: "x".repeat(300000) })],
    });
    const request = new Request(`${host}/v1/events`, {
      method: "POST",
      headers: gzip ? { "content-encoding": "gzip" } : {},
      body: gzip ? gzipSync(payload) : payload,
    });
    const response = await worker.fetch(request, {
      TELEMETRY_QUEUE: {
        send() {
          throw new Error("Oversize must never enqueue");
        },
      },
    });
    assert.equal(response.status, 413);
  }
});
test("batch is all-or-nothing and permitted schema reaches queue without request metadata", async () => {
  const sent = [];
  const localEnv = {
    TELEMETRY_QUEUE: {
      async send(body) {
        sent.push(body);
      },
    },
  };
  const request = (events) =>
    new Request(`${host}/v1/events`, {
      method: "POST",
      body: JSON.stringify({ schema_version: 1, events }),
    });
  assert.equal(
    (
      await worker.fetch(
        request([event(), event({ stdout: "private" })]),
        localEnv,
      )
    ).status,
    400,
  );
  assert.equal(sent.length, 0);
  assert.equal((await worker.fetch(request([event()]), localEnv)).status, 202);
  assert.deepEqual(Object.keys(sent[0]).sort(), [
    "events",
    "received_at",
    "schema_version",
  ]);
});

test("compressed transport itself is bounded without a Content-Length header", async () => {
  const payload = JSON.stringify({ schema_version: 1, events: [event()] });
  const body = Buffer.concat([
    gzipSync(payload),
    ...Array.from({ length: 15000 }, () => gzipSync("")),
  ]);
  assert.ok(body.length > 256 * 1024);
  let sent = false;
  const response = await worker.fetch(
    new Request(`${host}/v1/events`, {
      method: "POST",
      headers: { "content-encoding": "gzip" },
      body,
    }),
    {
      TELEMETRY_QUEUE: {
        async send() {
          sent = true;
        },
      },
    },
  );
  assert.equal(response.status, 413);
  assert.equal(sent, false);
});
test("queue retries are idempotent and invalid queue payload cannot bypass ingest schema", async () => {
  const bucket = new Bucket();
  let acks = 0;
  const message = {
    id: "delivery-id",
    body: {
      schema_version: 1,
      received_at: new Date().toISOString(),
      events: [event()],
    },
    ack() {
      acks++;
    },
  };
  await handleQueue({ messages: [message] }, env(bucket));
  await handleQueue({ messages: [message] }, env(bucket));
  assert.equal(bucket.objects.size, 1);
  assert.equal(acks, 2);
  message.body.events = [event({ secret: "private" })];
  await handleQueue({ messages: [message] }, env(bucket));
  assert.equal(bucket.puts.length, 2);
  assert.equal(acks, 3);
});
test("queue storage failure leaves message unacknowledged for retry", async () => {
  const bucket = new Bucket();
  bucket.put = async () => {
    throw new Error("storage failure");
  };
  let ack = false;
  await assert.rejects(
    handleQueue(
      {
        messages: [
          {
            id: "delivery",
            body: {
              schema_version: 1,
              received_at: new Date().toISOString(),
              events: [event()],
            },
            ack() {
              ack = true;
            },
          },
        ],
      },
      env(bucket),
    ),
  );
  assert.equal(ack, false);
});

test("client retries with different queue IDs and batch membership store each event once", async () => {
  const bucket = new Bucket();
  const first = event();
  const second = event({ event_id: "c".repeat(32) });
  let acks = 0;
  for (const [id, events] of [
    ["delivery-one", [first]],
    ["delivery-two", [first, second]],
  ]) {
    await handleQueue(
      {
        messages: [
          {
            id,
            body: {
              schema_version: 1,
              received_at: new Date().toISOString(),
              events,
            },
            ack() {
              acks++;
            },
          },
        ],
      },
      env(bucket),
    );
  }
  assert.equal(bucket.objects.size, 2);
  assert.equal(acks, 2);
  assert.equal(
    buildDailyAggregate("2026-10-04", [first, first, second]).totals.events,
    2,
  );
});
test("retention and archive endpoints require authentication and allowed host", async () => {
  const bucket = new Bucket(["raw/2020/01/01/old"]);
  for (const path of [
    "/v1/admin/retention",
    "/v1/archive/manifest",
    "/v1/archive/object",
  ])
    assert.equal(
      (await worker.fetch(new Request(`${host}${path}`), env(bucket))).status,
      401,
    );
  assert.equal(
    (
      await worker.fetch(
        new Request("https://untrusted.example/health"),
        env(bucket),
      )
    ).status,
    403,
  );
  const preview = await worker.fetch(
    new Request(`${host}/v1/admin/retention`, {
      headers: { authorization: "Bearer local-test-token" },
    }),
    env(bucket),
  );
  assert.equal(preview.status, 401);
  assert.equal(bucket.deleted.length, 0);
  const deletion = await worker.fetch(
    new Request(`${host}/v1/admin/retention`, {
      method: "POST",
      headers: { authorization: "Bearer local-test-token" },
    }),
    env(bucket),
  );
  assert.equal(deletion.status, 401);
  assert.equal(bucket.objects.size, 1);
});
test("aggregates contain no session/install IDs and resist special object keys", () => {
  const aggregate = buildDailyAggregate("2026-10-04", [
    event({ tool_name: "__proto__", install_hash: "a".repeat(64) }),
  ]);
  assert.equal(aggregate.by_tool[0].tool_name, "__proto__");
  assert.equal(JSON.stringify(aggregate).includes("install_hash"), false);
  assert.equal(JSON.stringify(aggregate).includes("session_id"), false);
});

test("temporary maintenance credential accepts fresh tokens only and never grants archive access", async () => {
  for (const offset of [60000, -60000]) {
    const token = `${String(Date.now() + offset)}.${"a".repeat(64)}`;
    const bucket = new Bucket(["raw/2020/01/01/old"]);
    const localEnv = {
      ...env(bucket),
      TELEMETRY_RETENTION_TOKEN: `${token}\n`,
    };
    const request = (path, method = "GET") =>
      new Request(host + path, {
        method,
        headers: { authorization: `Bearer ${token}` },
      });
    const expected = offset > 0 ? 200 : 401;
    assert.equal(
      (await worker.fetch(request("/v1/admin/retention"), localEnv)).status,
      expected,
    );
    assert.equal(bucket.deleted.length, 0);
    assert.equal(
      (await worker.fetch(request("/v1/archive/manifest"), localEnv)).status,
      401,
    );
    assert.equal(
      (await worker.fetch(request("/v1/admin/retention", "POST"), localEnv))
        .status,
      expected,
    );
    assert.equal(bucket.deleted.length, offset > 0 ? 1 : 0);
  }
});

test("scheduled retention runs even when aggregate generation fails", async () => {
  const bucket = new Bucket([
    "raw/2020/01/01/old",
    "aggregates/2020/01/01/old",
  ]);
  bucket.put = async () => {
    throw new Error("aggregate failure");
  };
  await assert.rejects(worker.scheduled({}, env(bucket)), /aggregate failure/);
  assert.equal(bucket.objects.size, 0);
});

test("scheduled aggregation revisits offline event days without retry double counting", async () => {
  const bucket = new Bucket();
  bucket.get = async (key) => ({
    arrayBuffer: async () => bucket.objects.get(key),
  });
  const late = event({
    timestamp: new Date(Date.now() - 2 * 86400000).toISOString(),
  });
  for (const id of ["late-one", "late-two"]) {
    await handleQueue(
      {
        messages: [
          {
            id,
            body: {
              schema_version: 1,
              received_at: new Date().toISOString(),
              events: [late],
            },
            ack() {},
          },
        ],
      },
      env(bucket),
    );
  }
  await worker.scheduled({}, env(bucket));
  const day = late.timestamp.slice(0, 10).replaceAll("-", "/");
  const aggregate = JSON.parse(
    bucket.objects.get(`aggregates/${day}/summary.json`),
  );
  assert.equal(aggregate.totals.events, 1);
  assert.equal(
    bucket.puts.filter((key) => key.startsWith("aggregates/")).length,
    9,
  );
});
