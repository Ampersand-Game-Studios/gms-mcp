import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";
import worker, {
  buildDailyAggregate,
  handleQueue,
  IngestBudget,
  retentionSettings,
  runRetention,
  sanitizeEvent,
} from "../src/index.js";
import { clientBudgetName, clientNetwork } from "../src/ingest-budget.js";

const host = "https://gms-mcp-telemetry.ampersandgamestudios.com";
const ingestHeaders = {
  "content-type": "application/json",
  "cf-connecting-ip": "192.0.2.1",
};
function protections() {
  return {
    INGEST_IP_LIMITER: {
      async limit() {
        return { success: true };
      },
    },
    INGEST_EDGE_LIMITER: {
      async limit() {
        return { success: true };
      },
    },
    INGEST_BUDGET: {
      idFromName: (name) => name,
      get() {
        return {
          async fetch() {
            return new Response(null, { status: 200 });
          },
        };
      },
    },
  };
}
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
  for (const [event_type, surface] of [
    ["cli.command", "cli"],
    ["telemetry.consent_changed", "cli"],
    ["mcp.tool", "mcp"],
    ["mcp.server_start", "mcp"],
    ["init.run", "init"],
    ["init.codex_check", "init"],
  ])
    assert.ok(
      sanitizeEvent(
        event({
          event_type,
          surface,
          result: "error",
          error_family: "project_access",
        }),
      ),
    );
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
    { event_type: "arbitrary" },
    { event_type: "mcp.tool" },
    { error_family: "secret" },
    { duration_bucket: "secret" },
    { duration_ms: 7 * 86400000 + 1 },
    { python_version: "private-value" },
    { gms_mcp_version: "private-value" },
  ])
    assert.equal(sanitizeEvent(event(override)), null);
});
test("timestamps reject calendar rollover while preserving client UTC formats", () => {
  const originalNow = Date.now;
  Date.now = () => Date.parse("2026-03-02T12:00:00Z");
  try {
    for (const timestamp of [
      "2026-03-02T12:00:00Z",
      "2026-03-02T12:00:00.1Z",
      "2026-03-02T12:00:00.12Z",
      "2026-03-02T12:00:00.123Z",
    ])
      assert.ok(sanitizeEvent(event({ timestamp })));
    assert.equal(
      sanitizeEvent(event({ timestamp: "2026-02-30T12:00:00Z" })),
      null,
    );
  } finally {
    Date.now = originalNow;
  }
});
test("package versions accept normalized release and SCM development versions", () => {
  for (const gms_mcp_version of [
    "0.1.dev64",
    "0.0.13",
    "0.1.0rc1",
    "0.1.0.post1.dev2",
    "0.1.dev64+g1234abcd",
  ]) {
    assert.ok(sanitizeEvent(event({ gms_mcp_version })), gms_mcp_version);
  }
});
test("identity/gzip decompressed bodies are bounded even without content-length", async () => {
  for (const gzip of [false, true]) {
    const payload = JSON.stringify({
      schema_version: 1,
      events: [event({ action: "x".repeat(300000) })],
    });
    const request = new Request(`${host}/v1/events`, {
      method: "POST",
      headers: {
        ...ingestHeaders,
        ...(gzip ? { "content-encoding": "gzip" } : {}),
      },
      body: gzip ? gzipSync(payload) : payload,
    });
    const response = await worker.fetch(request, {
      ...protections(),
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
    ...protections(),
    TELEMETRY_QUEUE: {
      async send(body) {
        sent.push(body);
      },
    },
  };
  const request = (events) =>
    new Request(`${host}/v1/events`, {
      method: "POST",
      headers: ingestHeaders,
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
      headers: { ...ingestHeaders, "content-encoding": "gzip" },
      body,
    }),
    {
      ...protections(),
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

test("limits run before parsing, use the connection IP, and fail closed", async () => {
  for (const failure of ["ip", "edge", "exception", "missing"]) {
    let queued = false;
    const localEnv = {
      ...protections(),
      TELEMETRY_QUEUE: {
        async send() {
          queued = true;
        },
      },
    };
    const keys = [];
    localEnv.INGEST_IP_LIMITER.limit = async ({ key }) => {
      keys.push(key);
      if (failure === "exception") throw new Error("outage");
      return { success: failure !== "ip" };
    };
    localEnv.INGEST_EDGE_LIMITER.limit = async () => ({
      success: failure !== "edge",
    });
    if (failure === "missing") delete localEnv.INGEST_IP_LIMITER;
    const response = await worker.fetch(
      new Request(`${host}/v1/events`, {
        method: "POST",
        headers: { ...ingestHeaders, "x-forwarded-for": "198.51.100.8" },
        body: "invalid json",
      }),
      localEnv,
    );
    assert.equal(response.status, ["ip", "edge"].includes(failure) ? 429 : 503);
    assert.equal(response.headers.get("retry-after"), "60");
    assert.equal(queued, false);
    if (failure !== "missing") assert.deepEqual(keys, ["192.0.2.1"]);
  }
});

test("strict transport, batch envelope, and duplicate IDs never enqueue", async () => {
  const localEnv = {
    ...protections(),
    TELEMETRY_QUEUE: {
      async send() {
        assert.fail("must not enqueue");
      },
    },
  };
  const payload = { schema_version: 1, events: [event()] };
  for (const [body, headers, expected] of [
    [payload, { "content-type": "application/json" }, 403],
    [payload, { ...ingestHeaders, "content-type": "text/plain" }, 415],
    [{ ...payload, extra: "private" }, ingestHeaders, 400],
    [{ ...payload, sent_at: null }, ingestHeaders, 400],
    [{ ...payload, sent_at: "2000-01-01T00:00:00Z" }, ingestHeaders, 400],
    [{ ...payload, events: [event(), event()] }, ingestHeaders, 400],
  ]) {
    const response = await worker.fetch(
      new Request(`${host}/v1/events`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      }),
      localEnv,
    );
    assert.equal(response.status, expected);
  }
});

test("daily budget rejection and outages prevent queue writes; queue failures are retryable", async () => {
  for (const failure of ["budget_limit", "budget_outage", "queue"]) {
    let queued = false;
    const localEnv = {
      ...protections(),
      TELEMETRY_QUEUE: {
        async send() {
          queued = true;
          throw new Error("outage");
        },
      },
    };
    localEnv.INGEST_BUDGET.get = () => ({
      async fetch() {
        if (failure === "budget_outage") throw new Error("outage");
        if (failure === "budget_limit")
          return new Response(null, {
            status: 429,
            headers: { "retry-after": "123" },
          });
        return new Response(null, { status: 200 });
      },
    });
    const response = await worker.fetch(
      new Request(`${host}/v1/events`, {
        method: "POST",
        headers: ingestHeaders,
        body: JSON.stringify({
          schema_version: 1,
          sent_at: new Date().toISOString(),
          events: [event()],
        }),
      }),
      localEnv,
    );
    assert.equal(response.status, failure === "budget_limit" ? 429 : 503);
    assert.equal(queued, failure === "queue");
  }
});

test("durable quota persists across restarts and enforces minute/day boundaries atomically", async () => {
  const originalNow = Date.now;
  let now = Date.parse("2026-11-03T12:00:00Z");
  const data = new Map();
  let pending = Promise.resolve();
  const storage = {
    transaction(callback) {
      const next = pending.then(() =>
        callback({
          get: async (key) => data.get(key),
          put: async (key, value) => data.set(key, value),
        }),
      );
      pending = next.catch(() => {});
      return next;
    },
  };
  const reserve = (count = 1) =>
    new IngestBudget({ storage }).fetch(
      new Request("https://budget/reserve", {
        method: "POST",
        body: JSON.stringify({ events: count }),
      }),
    );
  Date.now = () => now;
  try {
    const parallel = await Promise.all(
      Array.from({ length: 305 }, () => reserve()),
    );
    assert.equal(
      parallel.filter((response) => response.status === 200).length,
      300,
    );
    assert.equal(data.get("counters").events, 300);
    now += 60000;
    assert.equal((await reserve()).status, 200);
    data.set("counters", {
      day: Math.floor(now / 86400000),
      minute: Math.floor(now / 60000),
      events: 49999,
      batches: 0,
    });
    assert.equal((await reserve(2)).status, 429);
    assert.equal((await reserve()).status, 200);
    now += 60000;
    assert.equal((await reserve()).status, 429);
    assert.equal(data.get("counters").events, 50000);
    now += 86400000;
    assert.equal((await reserve(50)).status, 200);
    assert.equal(data.get("counters").events, 50);
    assert.deepEqual([...data.keys()], ["counters"]);
  } finally {
    Date.now = originalNow;
  }
});
test("one network's daily share cannot exhaust the shared budget and leaves no lasting record", async () => {
  const data = new Map();
  let alarm = null;
  const storage = {
    transaction: (run) =>
      run({
        get: async (key) => data.get(key),
        put: async (key, value) => data.set(key, value),
        setAlarm: async (time) => {
          alarm = time;
        },
      }),
    deleteAll: async () => data.clear(),
  };
  const object = new IngestBudget({ storage });
  const reserve = () =>
    object.fetch(
      new Request("https://budget/reserve-client", {
        method: "POST",
        body: JSON.stringify({ events: 50 }),
      }),
    );
  for (let batch = 0; batch < 100; batch += 1) {
    assert.equal((await reserve()).status, 200);
  }
  const rejected = await reserve();
  assert.equal(rejected.status, 429);
  assert.ok(Number(rejected.headers.get("retry-after")) >= 1);
  assert.deepEqual([...data.entries()], [["client_events", 5000]]);
  assert.equal(alarm % 86400000, 0);
  await object.alarm();
  assert.equal(data.size, 0);

  assert.equal(clientNetwork("203.0.113.9"), "203.0.113");
  assert.equal(clientNetwork("2001:db8:1:2::9"), "2001:0db8:0001");
  assert.equal(clientNetwork("2001:db8::9"), "2001:0db8:0000");
  const today = 86400000 * 20000;
  assert.equal(
    await clientBudgetName("203.0.113.9", today),
    await clientBudgetName("203.0.113.200", today),
  );
  assert.notEqual(
    await clientBudgetName("203.0.113.9", today),
    await clientBudgetName("203.0.114.9", today),
  );
  assert.notEqual(
    await clientBudgetName("203.0.113.9", today),
    await clientBudgetName("203.0.113.9", today + 86400000),
  );
  assert.ok(!(await clientBudgetName("203.0.113.9", today)).includes("203"));
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
