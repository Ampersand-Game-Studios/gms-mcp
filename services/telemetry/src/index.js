import EVENT_SCHEMA from "./event-schema.json" with { type: "json" };
import { clientBudgetName } from "./ingest-budget.js";

const SCHEMA_VERSION = 1;
const MAX_EVENTS = 50;
const MAX_REQUEST_BYTES = 256 * 1024;
const MAX_ARCHIVE_DAYS = 31;
const MAX_ARCHIVE_OBJECTS = 10000;
const PRIMARY_HOSTNAME = "gms-mcp-telemetry.ampersandgamestudios.com";
const DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
const SERVICE_REVISION = "ingest-security-v9";
const EVENT_SURFACES = EVENT_SCHEMA.event_surfaces;
const SURFACES = new Set(Object.values(EVENT_SURFACES));
const RESULTS = new Set(EVENT_SCHEMA.results);
const ERROR_FAMILIES = new Set(EVENT_SCHEMA.error_families);
const DURATION_BUCKETS = new Set(EVENT_SCHEMA.duration_buckets);
const TOKEN_PATTERN = new RegExp(EVENT_SCHEMA.token_pattern);
const VERSION_PATTERN = new RegExp(EVENT_SCHEMA.version_pattern, "i");
const PYTHON_VERSION_PATTERN = new RegExp(EVENT_SCHEMA.python_version_pattern);
const TIMESTAMP_PATTERN = new RegExp(EVENT_SCHEMA.timestamp_pattern);
const MAX_EVENT_AGE_MS = EVENT_SCHEMA.max_event_age_ms;
const MAX_CLOCK_SKEW_MS = EVENT_SCHEMA.max_clock_skew_ms;

export { IngestBudget } from "./ingest-budget.js";

const EVENT_RULES = EVENT_SCHEMA.fields;

function jsonResponse(status, payload, headers = {}) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      ...headers,
    },
  });
}

function hostAllowed(request) {
  let hostname = "";
  try {
    hostname = new URL(request.url).hostname.toLowerCase();
  } catch (_error) {
    return false;
  }
  return hostname === PRIMARY_HOSTNAME || DEV_HOSTS.has(hostname);
}

function parseBearerToken(request) {
  const header = request.headers.get("authorization") || "";
  if (!header.toLowerCase().startsWith("bearer ")) {
    return "";
  }
  return header.slice(7).trim();
}

function requireArchiveAuth(request, env) {
  const expected = String(env.TELEMETRY_ARCHIVE_TOKEN || "").trim();
  if (!expected) {
    return jsonResponse(503, {
      ok: false,
      error: "Archive export is not configured.",
    });
  }
  const provided = parseBearerToken(request);
  if (!provided || provided !== expected) {
    return jsonResponse(401, { ok: false, error: "Unauthorized." });
  }
  return null;
}

async function readJsonBody(request) {
  const contentLength = Number(request.headers.get("content-length") || "0");
  if (contentLength > MAX_REQUEST_BYTES) {
    throw new Error("payload_too_large");
  }

  const encoding = (
    request.headers.get("content-encoding") || ""
  ).toLowerCase();
  if (encoding && encoding !== "identity" && encoding !== "gzip") {
    throw new Error("unsupported_encoding");
  }
  if (!request.body) throw new Error("missing_body");
  let compressedSize = 0;
  const boundedBody = request.body.pipeThrough(
    new TransformStream({
      transform(chunk, controller) {
        compressedSize += chunk.byteLength;
        if (compressedSize > MAX_REQUEST_BYTES)
          throw new Error("payload_too_large");
        controller.enqueue(chunk);
      },
    }),
  );
  const stream =
    encoding === "gzip"
      ? boundedBody.pipeThrough(new DecompressionStream("gzip"))
      : boundedBody;
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_REQUEST_BYTES) {
        await reader.cancel();
        throw new Error("payload_too_large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

function sanitizeEvent(event, now = Date.now()) {
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    return null;
  }

  const sanitized = {};
  if (Object.keys(event).some((key) => !Object.hasOwn(EVENT_RULES, key)))
    return null;
  for (const [key, rule] of Object.entries(EVENT_RULES)) {
    const value = event[key];
    if (value === undefined || value === null) {
      if (rule.required) {
        return null;
      }
      continue;
    }

    if (rule.type === "string") {
      if (typeof value !== "string") {
        return null;
      }
      const trimmed = value.trim();
      if (
        !trimmed ||
        trimmed.length > rule.maxLength ||
        (key !== "timestamp" && !TOKEN_PATTERN.test(trimmed))
      ) {
        return null;
      }
      sanitized[key] = trimmed;
      continue;
    }

    if (rule.type === "integer") {
      if (!Number.isSafeInteger(value) || value < 0) {
        return null;
      }
      sanitized[key] = value;
      continue;
    }

    if (rule.type === "boolean") {
      if (typeof value !== "boolean") {
        return null;
      }
      sanitized[key] = value;
    }
  }

  if (sanitized.schema_version !== EVENT_SCHEMA.schema_version) {
    return null;
  }
  if (
    !/^[a-f0-9]{32}$/.test(sanitized.event_id) ||
    !/^[a-f0-9]{32}$/.test(sanitized.session_id)
  )
    return null;
  if (sanitized.install_hash && !/^[a-f0-9]{64}$/.test(sanitized.install_hash))
    return null;
  if (!SURFACES.has(sanitized.surface) || !RESULTS.has(sanitized.result))
    return null;
  if (sanitized.ci || sanitized.test_env) return null;
  if (
    !Object.hasOwn(EVENT_SURFACES, sanitized.event_type) ||
    EVENT_SURFACES[sanitized.event_type] !== sanitized.surface ||
    (sanitized.error_family && !ERROR_FAMILIES.has(sanitized.error_family)) ||
    (sanitized.duration_bucket &&
      !DURATION_BUCKETS.has(sanitized.duration_bucket)) ||
    (sanitized.duration_ms !== undefined &&
      sanitized.duration_ms > EVENT_SCHEMA.max_duration_ms) ||
    !VERSION_PATTERN.test(sanitized.gms_mcp_version) ||
    !PYTHON_VERSION_PATTERN.test(sanitized.python_version)
  )
    return null;
  if (!validClientTimestamp(sanitized.timestamp, now)) return null;
  return sanitized;
}

function utcParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error("invalid_timestamp");
  }
  return {
    year: String(date.getUTCFullYear()),
    month: String(date.getUTCMonth() + 1).padStart(2, "0"),
    day: String(date.getUTCDate()).padStart(2, "0"),
  };
}

function prefixForDate(kind, value) {
  const parts = utcParts(value);
  return `${kind}/${parts.year}/${parts.month}/${parts.day}/`;
}

async function gzipText(text) {
  const stream = new Blob([text])
    .stream()
    .pipeThrough(new CompressionStream("gzip"));
  return await new Response(stream).arrayBuffer();
}

async function gunzipToText(buffer) {
  const stream = new Blob([buffer])
    .stream()
    .pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

function buildDailyAggregate(dayIso, events) {
  const totals = {
    events: 0,
    ok: 0,
    error: 0,
    cancelled: 0,
  };
  const byEventType = Object.create(null);
  const byTool = Object.create(null);
  const bySurface = Object.create(null);
  const seen = new Set();

  for (const event of events) {
    if (
      !event ||
      typeof event.event_id !== "string" ||
      seen.has(event.event_id)
    )
      continue;
    seen.add(event.event_id);
    totals.events += 1;
    if (event.result === "ok") {
      totals.ok += 1;
    } else if (event.result === "cancelled") {
      totals.cancelled += 1;
    } else {
      totals.error += 1;
    }

    byEventType[event.event_type] = (byEventType[event.event_type] || 0) + 1;
    bySurface[event.surface] = (bySurface[event.surface] || 0) + 1;

    const tool = byTool[event.tool_name] || {
      tool_name: event.tool_name,
      tool_family: event.tool_family,
      total: 0,
      ok: 0,
      error: 0,
      cancelled: 0,
      total_duration_ms: 0,
      max_duration_ms: 0,
    };
    tool.total += 1;
    if (event.result === "ok") {
      tool.ok += 1;
    } else if (event.result === "cancelled") {
      tool.cancelled += 1;
    } else {
      tool.error += 1;
    }
    if (Number.isInteger(event.duration_ms)) {
      tool.total_duration_ms += event.duration_ms;
      tool.max_duration_ms = Math.max(tool.max_duration_ms, event.duration_ms);
    }
    byTool[event.tool_name] = tool;
  }

  return {
    schema_version: SCHEMA_VERSION,
    generated_at: new Date().toISOString(),
    day: dayIso,
    totals,
    by_event_type: byEventType,
    by_surface: bySurface,
    by_tool: Object.values(byTool).sort(
      (left, right) => right.total - left.total,
    ),
  };
}

async function listObjects(bucket, prefix) {
  let cursor;
  const objects = [];
  do {
    const page = await bucket.list({ prefix, cursor });
    for (const object of page.objects) {
      objects.push({
        key: object.key,
        size: object.size || 0,
        uploaded: object.uploaded
          ? new Date(object.uploaded).toISOString()
          : null,
      });
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return objects;
}

async function loadEvents(bucket, keys) {
  const events = [];
  for (const key of keys) {
    const object = await bucket.get(key);
    if (!object) {
      continue;
    }
    const compressed = await object.arrayBuffer();
    const text = await gunzipToText(compressed);
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      try {
        events.push(JSON.parse(trimmed));
      } catch (_error) {}
    }
  }
  return events;
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function daysToMilliseconds(days) {
  return days * 24 * 60 * 60 * 1000;
}

function parseDateOnly(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error("invalid_date");
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.toISOString().slice(0, 10) !== value
  ) {
    throw new Error("invalid_date");
  }
  return parsed;
}

function normalizeArchiveRange(searchParams) {
  const startRaw = searchParams.get("start_date");
  const endRaw = searchParams.get("end_date");
  if (!startRaw || !endRaw) {
    throw new Error("missing_dates");
  }
  const startDate = parseDateOnly(startRaw);
  const endDate = parseDateOnly(endRaw);
  if (endDate.getTime() < startDate.getTime()) {
    throw new Error("invalid_range");
  }
  const totalDays =
    Math.floor(
      (endDate.getTime() - startDate.getTime()) / daysToMilliseconds(1),
    ) + 1;
  if (totalDays > MAX_ARCHIVE_DAYS) {
    throw new Error("range_too_large");
  }
  return { startDate, endDate, totalDays };
}

function nextUtcDay(value) {
  return new Date(
    Date.UTC(
      value.getUTCFullYear(),
      value.getUTCMonth(),
      value.getUTCDate() + 1,
    ),
  );
}

function isAllowedArchiveKey(key) {
  return (
    typeof key === "string" &&
    key.length > 0 &&
    key.length <= 1024 &&
    !key.includes("..") &&
    (key.startsWith("raw/") || key.startsWith("aggregates/"))
  );
}

async function handleArchiveManifest(request, env) {
  const authFailure = requireArchiveAuth(request, env);
  if (authFailure) {
    return authFailure;
  }

  const url = new URL(request.url);
  let range;
  try {
    range = normalizeArchiveRange(url.searchParams);
  } catch (error) {
    const reason = String(error.message);
    if (reason === "missing_dates") {
      return jsonResponse(400, {
        ok: false,
        error: "Expected start_date and end_date.",
      });
    }
    if (reason === "range_too_large") {
      return jsonResponse(400, {
        ok: false,
        error: "Requested range is too large.",
      });
    }
    return jsonResponse(400, {
      ok: false,
      error: "Invalid archive date range.",
    });
  }

  const cursor = url.searchParams.get("cursor") || "";
  if (cursor && !isAllowedArchiveKey(cursor)) {
    return jsonResponse(400, { ok: false, error: "Invalid archive cursor." });
  }
  const limitRaw = url.searchParams.get("limit");
  const pageLimit = limitRaw === null ? MAX_ARCHIVE_OBJECTS : Number(limitRaw);
  if (
    !Number.isSafeInteger(pageLimit) ||
    pageLimit < 1 ||
    pageLimit > MAX_ARCHIVE_OBJECTS
  ) {
    return jsonResponse(400, { ok: false, error: "Invalid archive limit." });
  }

  // Keys are listed in ascending lexicographic order (kind, then day), so the
  // last returned key is a stable cursor for the next page.
  const objects = [];
  let nextCursor = null;
  pages: for (const kind of ["aggregates", "raw"]) {
    for (
      let current = range.startDate;
      current.getTime() <= range.endDate.getTime();
      current = nextUtcDay(current)
    ) {
      const prefix = prefixForDate(kind, current.toISOString());
      const resumesHere = cursor.startsWith(prefix);
      if (cursor && cursor > prefix && !resumesHere) continue;
      let listCursor;
      do {
        const page = await env.TELEMETRY_BUCKET.list({
          prefix,
          limit: 1000,
          ...(listCursor
            ? { cursor: listCursor }
            : resumesHere
              ? { startAfter: cursor }
              : {}),
        });
        for (const object of page.objects) {
          if (objects.length === pageLimit) {
            nextCursor = objects.at(-1).key;
            break pages;
          }
          objects.push({
            key: object.key,
            size: object.size || 0,
            uploaded_at: object.uploaded
              ? new Date(object.uploaded).toISOString()
              : null,
          });
        }
        if (page.truncated && (!page.cursor || page.cursor === listCursor))
          throw new Error("invalid_archive_cursor");
        listCursor = page.truncated ? page.cursor : undefined;
      } while (listCursor);
    }
  }

  return jsonResponse(200, {
    ok: true,
    schema_version: SCHEMA_VERSION,
    generated_at: new Date().toISOString(),
    range: {
      start_date: range.startDate.toISOString().slice(0, 10),
      end_date: range.endDate.toISOString().slice(0, 10),
    },
    object_count: objects.length,
    objects,
    next_cursor: nextCursor,
  });
}

async function handleArchiveObject(request, env) {
  const authFailure = requireArchiveAuth(request, env);
  if (authFailure) {
    return authFailure;
  }

  const url = new URL(request.url);
  const key = url.searchParams.get("key") || "";
  if (!isAllowedArchiveKey(key)) {
    return jsonResponse(400, { ok: false, error: "Invalid object key." });
  }

  const object = await env.TELEMETRY_BUCKET.get(key);
  if (!object) {
    return jsonResponse(404, {
      ok: false,
      error: "Telemetry object not found.",
    });
  }

  const headers = new Headers({
    "cache-control": "private, no-store",
    "x-telemetry-object-key": key,
  });
  if (object.httpMetadata?.contentType) {
    headers.set("content-type", object.httpMetadata.contentType);
  }
  if (object.httpMetadata?.contentEncoding) {
    headers.set("content-encoding", object.httpMetadata.contentEncoding);
  }

  return new Response(object.body, {
    status: 200,
    headers,
  });
}

async function handleIngest(request, env) {
  // Only Cloudflare's connection address controls the limit. Forwarded headers
  // and client-provided session/install identities cannot select a fresh quota.
  const ip = request.headers.get("cf-connecting-ip");
  if (!ip)
    return jsonResponse(403, { ok: false, error: "Missing client address." });
  try {
    const local = await env.INGEST_IP_LIMITER.limit({ key: ip });
    if (!local.success)
      return jsonResponse(
        429,
        { ok: false, error: "Rate limited." },
        { "retry-after": "60" },
      );
    const overall = await env.INGEST_EDGE_LIMITER.limit({ key: "ingest" });
    if (!overall.success)
      return jsonResponse(
        429,
        { ok: false, error: "Rate limited." },
        { "retry-after": "60" },
      );
  } catch {
    return jsonResponse(
      503,
      { ok: false, error: "Ingestion protection unavailable." },
      { "retry-after": "60" },
    );
  }
  if (
    (request.headers.get("content-type") || "")
      .split(";")[0]
      .trim()
      .toLowerCase() !== "application/json"
  ) {
    return jsonResponse(415, {
      ok: false,
      error: "Expected application/json.",
    });
  }
  let payload;
  try {
    payload = await readJsonBody(request);
  } catch (error) {
    if (String(error.message) === "payload_too_large") {
      return jsonResponse(413, { ok: false, error: "Payload too large." });
    }
    if (String(error.message) === "unsupported_encoding") {
      return jsonResponse(415, {
        ok: false,
        error: "Unsupported content encoding.",
      });
    }
    return jsonResponse(400, { ok: false, error: "Malformed JSON payload." });
  }

  const events = Array.isArray(payload?.events) ? payload.events : null;
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    Object.keys(payload).some(
      (key) => !["schema_version", "sent_at", "events"].includes(key),
    ) ||
    (payload.sent_at !== undefined && !validClientTimestamp(payload.sent_at)) ||
    payload?.schema_version !== SCHEMA_VERSION ||
    !events ||
    events.length === 0 ||
    events.length > MAX_EVENTS
  ) {
    return jsonResponse(400, { ok: false, error: "Expected 1-50 events." });
  }

  const now = Date.now();
  const sanitized = events
    .map((event) => sanitizeEvent(event, now))
    .filter(Boolean);
  if (sanitized.length !== events.length) {
    return jsonResponse(400, {
      ok: false,
      error: "Every event must satisfy the closed telemetry schema.",
    });
  }
  if (
    new Set(sanitized.map((event) => event.event_id)).size !== sanitized.length
  ) {
    return jsonResponse(400, {
      ok: false,
      error: "Duplicate event IDs in batch.",
    });
  }

  try {
    // The client share goes first, so a rejected network spends no global budget.
    for (const [name, path] of [
      [await clientBudgetName(ip), "/reserve-client"],
      ["global", "/reserve"],
    ]) {
      const budget = env.INGEST_BUDGET.get(env.INGEST_BUDGET.idFromName(name));
      const decision = await budget.fetch(`https://budget.internal${path}`, {
        method: "POST",
        body: JSON.stringify({ events: sanitized.length }),
      });
      if (decision.status === 429) return decision;
      if (!decision.ok) throw new Error("budget_unavailable");
    }
  } catch {
    return jsonResponse(
      503,
      { ok: false, error: "Ingestion protection unavailable." },
      { "retry-after": "60" },
    );
  }

  try {
    await env.TELEMETRY_QUEUE.send({
      schema_version: SCHEMA_VERSION,
      received_at: new Date().toISOString(),
      events: sanitized,
    });
  } catch {
    return jsonResponse(
      503,
      { ok: false, error: "Ingestion queue unavailable." },
      { "retry-after": "60" },
    );
  }

  return jsonResponse(202, {
    ok: true,
    accepted: sanitized.length,
    dropped: events.length - sanitized.length,
  });
}

function validClientTimestamp(value, now = Date.now()) {
  if (typeof value !== "string" || !TIMESTAMP_PATTERN.test(value)) return false;
  const timestamp = Date.parse(value);
  const canonical = value.replace(
    /(\.\d{1,3})?Z$/,
    (_, fraction) => `${(fraction || ".").padEnd(4, "0")}Z`,
  );
  return (
    Number.isFinite(timestamp) &&
    new Date(timestamp).toISOString() === canonical &&
    timestamp <= now + MAX_CLOCK_SKEW_MS &&
    timestamp >= now - MAX_EVENT_AGE_MS
  );
}

async function handleQueue(batch, env) {
  const accepted = [];
  const eventsByPrefix = new Map();
  for (const message of batch.messages) {
    const body = message.body;
    if (
      !body ||
      body.schema_version !== SCHEMA_VERSION ||
      !Array.isArray(body.events) ||
      body.events.length === 0 ||
      body.events.length > MAX_EVENTS
    ) {
      message.ack();
      continue;
    }
    const receivedTime = Date.parse(body.received_at);
    if (
      !Number.isFinite(receivedTime) ||
      receivedTime > Date.now() + MAX_CLOCK_SKEW_MS ||
      receivedTime < Date.now() - MAX_EVENT_AGE_MS ||
      !message.id
    ) {
      message.ack();
      continue;
    }
    // Events were accepted (and charged to the budget) at receive time, so a
    // delayed or retried delivery is judged against that time, not now.
    const events = body.events.map((event) =>
      sanitizeEvent(event, receivedTime),
    );
    if (events.some((event) => !event)) {
      message.ack();
      continue;
    }
    accepted.push(message);
    for (const event of events) {
      const prefix = prefixForDate("raw", event.timestamp);
      if (!eventsByPrefix.has(prefix)) eventsByPrefix.set(prefix, new Map());
      eventsByPrefix.get(prefix).set(event.event_id, event);
    }
  }
  if (!accepted.length) return;

  // One object per event day per delivery batch. A redelivery of the same
  // messages rewrites the same keys; events resent in a different batch are
  // removed by the event_id de-duplication in buildDailyAggregate.
  const batchId = (
    await sha256Hex(
      accepted
        .map((message) => message.id)
        .sort()
        .join("\n"),
    )
  ).slice(0, 32);
  for (const [prefix, events] of eventsByPrefix) {
    const lines = [...events.values()]
      .map((event) => `${JSON.stringify(event)}\n`)
      .join("");
    await env.TELEMETRY_BUCKET.put(
      `${prefix}batch-${batchId}.ndjson.gz`,
      await gzipText(lines),
      {
        httpMetadata: {
          contentType: "application/x-ndjson",
          contentEncoding: "gzip",
        },
        customMetadata: {
          schema_version: String(SCHEMA_VERSION),
          event_count: String(events.size),
        },
      },
    );
  }
  for (const message of accepted) message.ack();
}

function retentionSettings(env, now) {
  const days = Number(env.RAW_RETENTION_DAYS || "90");
  const months = Number(env.AGGREGATE_RETENTION_MONTHS || "24");
  if (
    !Number.isInteger(days) ||
    days < 1 ||
    days > 365 ||
    !Number.isInteger(months) ||
    months < 1 ||
    months > 120
  )
    throw new Error("invalid_retention_configuration");
  const raw = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - days),
  );
  const aggregate = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - months, 1),
  );
  const lastDay = new Date(
    Date.UTC(aggregate.getUTCFullYear(), aggregate.getUTCMonth() + 1, 0),
  ).getUTCDate();
  aggregate.setUTCDate(Math.min(now.getUTCDate(), lastDay));
  return {
    raw: raw.toISOString().slice(0, 10),
    aggregates: aggregate.toISOString().slice(0, 10),
  };
}

async function purgeExpired(bucket, kind, cutoff, dryRun) {
  let cursor;
  let matched = 0;
  do {
    const page = await bucket.list({ prefix: `${kind}/`, cursor, limit: 1000 });
    const keys = page.objects
      .map((object) => object.key)
      .filter((key) => {
        const match = key.match(
          /^(raw|aggregates)\/(\d{4})\/(\d{2})\/(\d{2})\//,
        );
        if (!match) return false;
        const date = `${match[2]}-${match[3]}-${match[4]}`;
        try {
          parseDateOnly(date);
        } catch {
          return false;
        }
        // Expire the cutoff day itself as well as any older backlog.
        return date <= cutoff;
      });
    matched += keys.length;
    if (!dryRun && keys.length) await bucket.delete(keys);
    if (page.truncated && (!page.cursor || page.cursor === cursor))
      throw new Error("invalid_retention_cursor");
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return matched;
}

async function runRetention(env, { now = new Date(), dryRun = false } = {}) {
  const cutoffs = retentionSettings(env, now);
  const raw = await purgeExpired(
    env.TELEMETRY_BUCKET,
    "raw",
    cutoffs.raw,
    dryRun,
  );
  const aggregates = await purgeExpired(
    env.TELEMETRY_BUCKET,
    "aggregates",
    cutoffs.aggregates,
    dryRun,
  );
  return { ok: true, dry_run: dryRun, cutoffs, objects: { raw, aggregates } };
}

// Raw objects uploaded within this margin of the last aggregation are re-read,
// covering clock skew between the Worker and R2 upload timestamps.
const AGGREGATE_FRESHNESS_MARGIN_MS = 5 * 60 * 1000;

async function rebuildAggregates(env, now) {
  const bucket = env.TELEMETRY_BUCKET;
  // Offline clients can submit events up to seven days old. Consider the
  // accepted window plus the following UTC boundary so late arrivals count,
  // but only re-read days that received raw objects since their last rollup.
  for (let offset = 0; offset <= 8; offset++) {
    const day = new Date(
      Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate() - offset,
      ),
    );
    const dayIso = day.toISOString();
    const aggregateKey = `${prefixForDate("aggregates", dayIso)}summary.json`;
    const listedAt = Date.now();
    const [objects, existing] = await Promise.all([
      listObjects(bucket, prefixForDate("raw", dayIso)),
      bucket.head(aggregateKey),
    ]);
    const previousListedAt = Number(existing?.customMetadata?.listed_at);
    if (
      Number.isFinite(previousListedAt) &&
      objects.every(
        (object) =>
          object.uploaded &&
          Date.parse(object.uploaded) <
            previousListedAt - AGGREGATE_FRESHNESS_MARGIN_MS,
      )
    )
      continue;
    const events = await loadEvents(
      bucket,
      objects.map((object) => object.key),
    );
    const summary = buildDailyAggregate(dayIso.slice(0, 10), events);
    await bucket.put(aggregateKey, JSON.stringify(summary, null, 2), {
      httpMetadata: { contentType: "application/json" },
      customMetadata: { listed_at: String(listedAt) },
    });
  }
}

async function handleScheduled(env) {
  const now = new Date();
  // Aggregation and retention are independent: either failing must not stop
  // the other, and both failures are reported.
  const results = await Promise.allSettled([
    rebuildAggregates(env, now),
    runRetention(env, { now }),
  ]);
  const failures = results.filter((result) => result.status === "rejected");
  for (const [index, result] of results.entries()) {
    if (result.status === "rejected")
      console.error(
        JSON.stringify({
          event: "scheduled_task_failed",
          task: index === 0 ? "aggregate" : "retention",
          error: String(result.reason?.message || result.reason),
        }),
      );
  }
  if (failures.length) throw failures[0].reason;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!hostAllowed(request)) {
      return jsonResponse(403, { ok: false, error: "Forbidden host." });
    }
    if (request.method === "POST" && url.pathname === "/v1/events") {
      return handleIngest(request, env);
    }
    if (request.method === "GET" && url.pathname === "/v1/archive/manifest") {
      return handleArchiveManifest(request, env);
    }
    if (request.method === "GET" && url.pathname === "/v1/archive/object") {
      return handleArchiveObject(request, env);
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse(200, {
        ok: true,
        service: "gms-mcp-telemetry-ingest",
        revision: SERVICE_REVISION,
      });
    }
    if (
      url.pathname === "/v1/admin/retention" &&
      (request.method === "GET" || request.method === "POST")
    ) {
      const temporaryToken = String(env.TELEMETRY_RETENTION_TOKEN || "").trim();
      const expiry = temporaryToken.match(/^(\d{13})\.[a-f0-9]{64}$/);
      const temporaryAuth =
        expiry &&
        Number(expiry[1]) > Date.now() &&
        temporaryToken === parseBearerToken(request);
      if (!temporaryAuth)
        return jsonResponse(401, { ok: false, error: "Unauthorized." });
      return jsonResponse(
        200,
        await runRetention(env, { dryRun: request.method === "GET" }),
      );
    }
    return jsonResponse(404, { ok: false, error: "Not found." });
  },

  async queue(batch, env) {
    await handleQueue(batch, env);
  },

  async scheduled(_controller, env) {
    await handleScheduled(env);
  },
};

export {
  buildDailyAggregate,
  handleQueue,
  retentionSettings,
  runRetention,
  sanitizeEvent,
};
