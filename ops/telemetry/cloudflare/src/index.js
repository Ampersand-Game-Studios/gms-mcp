const SCHEMA_VERSION = 1;
const MAX_EVENTS = 50;
const MAX_REQUEST_BYTES = 256 * 1024;
const MAX_ARCHIVE_DAYS = 31;
const MAX_ARCHIVE_OBJECTS = 10000;
const PRIMARY_HOSTNAME = "gms-mcp-telemetry.ampersandgamestudios.com";
const DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);

const EVENT_RULES = {
  schema_version: { type: "integer", required: true },
  event_id: { type: "string", required: true, maxLength: 64 },
  session_id: { type: "string", required: true, maxLength: 64 },
  timestamp: { type: "string", required: true, maxLength: 32 },
  surface: { type: "string", required: true, maxLength: 16 },
  event_type: { type: "string", required: true, maxLength: 32 },
  action: { type: "string", required: true, maxLength: 64 },
  tool_name: { type: "string", required: true, maxLength: 64 },
  tool_family: { type: "string", required: true, maxLength: 32 },
  result: { type: "string", required: true, maxLength: 16 },
  error_family: { type: "string", required: false, maxLength: 32 },
  duration_ms: { type: "integer", required: false },
  duration_bucket: { type: "string", required: false, maxLength: 16 },
  execution_mode: { type: "string", required: false, maxLength: 32 },
  gms_mcp_version: { type: "string", required: true, maxLength: 32 },
  os_family: { type: "string", required: true, maxLength: 16 },
  python_version: { type: "string", required: true, maxLength: 16 },
  interactive: { type: "boolean", required: true },
  ci: { type: "boolean", required: true },
  test_env: { type: "boolean", required: true },
  install_hash: { type: "string", required: false, maxLength: 128 }
};

function jsonResponse(status, payload) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
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
    return jsonResponse(503, { ok: false, error: "Archive export is not configured." });
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

  const encoding = (request.headers.get("content-encoding") || "").toLowerCase();
  if (!encoding || encoding === "identity") {
    return await request.json();
  }
  if (encoding !== "gzip") {
    throw new Error("unsupported_encoding");
  }

  const stream = request.body.pipeThrough(new DecompressionStream("gzip"));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

function sanitizeEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    return null;
  }

  const sanitized = {};
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
      if (!trimmed || trimmed.length > rule.maxLength) {
        return null;
      }
      sanitized[key] = trimmed;
      continue;
    }

    if (rule.type === "integer") {
      if (!Number.isInteger(value)) {
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

  if (sanitized.schema_version !== SCHEMA_VERSION) {
    return null;
  }
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
    day: String(date.getUTCDate()).padStart(2, "0")
  };
}

function prefixForDate(kind, value) {
  const parts = utcParts(value);
  return `${kind}/${parts.year}/${parts.month}/${parts.day}/`;
}

async function gzipText(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return await new Response(stream).arrayBuffer();
}

async function gunzipToText(buffer) {
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

function buildDailyAggregate(dayIso, events) {
  const totals = {
    events: 0,
    ok: 0,
    error: 0,
    cancelled: 0
  };
  const byEventType = {};
  const byTool = {};
  const bySurface = {};

  for (const event of events) {
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
      max_duration_ms: 0
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
    by_tool: Object.values(byTool).sort((left, right) => right.total - left.total)
  };
}

async function listKeys(bucket, prefix) {
  let cursor = undefined;
  const keys = [];
  do {
    const page = await bucket.list({ prefix, cursor });
    for (const object of page.objects) {
      keys.push(object.key);
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return keys;
}

async function listObjects(bucket, prefix) {
  let cursor = undefined;
  const objects = [];
  do {
    const page = await bucket.list({ prefix, cursor });
    for (const object of page.objects) {
      objects.push({
        key: object.key,
        size: object.size || 0,
        uploaded: object.uploaded ? new Date(object.uploaded).toISOString() : null
      });
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return objects;
}

async function loadEventsForPrefix(bucket, prefix) {
  const keys = await listKeys(bucket, prefix);
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
      } catch (_error) {
        continue;
      }
    }
  }
  return events;
}

async function deletePrefixForDate(bucket, kind, value) {
  const prefix = prefixForDate(kind, value);
  const keys = await listKeys(bucket, prefix);
  for (const key of keys) {
    await bucket.delete(key);
  }
}

function monthsToDays(months) {
  return Number.parseInt(months || "24", 10) * 31;
}

function daysToMilliseconds(days) {
  return days * 24 * 60 * 60 * 1000;
}

function parseDateOnly(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error("invalid_date");
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
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
  const totalDays = Math.floor((endDate.getTime() - startDate.getTime()) / daysToMilliseconds(1)) + 1;
  if (totalDays > MAX_ARCHIVE_DAYS) {
    throw new Error("range_too_large");
  }
  return { startDate, endDate, totalDays };
}

function nextUtcDay(value) {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate() + 1));
}

function isAllowedArchiveKey(key) {
  return typeof key === "string" && key.length > 0 && key.length <= 1024 && !key.includes("..") && (key.startsWith("raw/") || key.startsWith("aggregates/"));
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
      return jsonResponse(400, { ok: false, error: "Expected start_date and end_date." });
    }
    if (reason === "range_too_large") {
      return jsonResponse(400, { ok: false, error: "Requested range is too large." });
    }
    return jsonResponse(400, { ok: false, error: "Invalid archive date range." });
  }

  const objects = [];
  for (let current = range.startDate; current.getTime() <= range.endDate.getTime(); current = nextUtcDay(current)) {
    const dayIso = current.toISOString();
    for (const kind of ["raw", "aggregates"]) {
      const entries = await listObjects(env.TELEMETRY_BUCKET, prefixForDate(kind, dayIso));
      for (const entry of entries) {
        objects.push({
          key: entry.key,
          size: entry.size,
          uploaded_at: entry.uploaded
        });
        if (objects.length > MAX_ARCHIVE_OBJECTS) {
          return jsonResponse(413, { ok: false, error: "Requested archive contains too many objects." });
        }
      }
    }
  }

  return jsonResponse(200, {
    ok: true,
    schema_version: SCHEMA_VERSION,
    generated_at: new Date().toISOString(),
    range: {
      start_date: range.startDate.toISOString().slice(0, 10),
      end_date: range.endDate.toISOString().slice(0, 10)
    },
    object_count: objects.length,
    objects
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
    return jsonResponse(404, { ok: false, error: "Telemetry object not found." });
  }

  const headers = new Headers({
    "cache-control": "private, no-store",
    "x-telemetry-object-key": key
  });
  if (object.httpMetadata?.contentType) {
    headers.set("content-type", object.httpMetadata.contentType);
  }
  if (object.httpMetadata?.contentEncoding) {
    headers.set("content-encoding", object.httpMetadata.contentEncoding);
  }

  return new Response(object.body, {
    status: 200,
    headers
  });
}

async function handleIngest(request, env) {
  let payload;
  try {
    payload = await readJsonBody(request);
  } catch (error) {
    if (String(error.message) === "payload_too_large") {
      return jsonResponse(413, { ok: false, error: "Payload too large." });
    }
    if (String(error.message) === "unsupported_encoding") {
      return jsonResponse(415, { ok: false, error: "Unsupported content encoding." });
    }
    return jsonResponse(400, { ok: false, error: "Malformed JSON payload." });
  }

  const events = Array.isArray(payload?.events) ? payload.events : null;
  if (!events || events.length === 0 || events.length > MAX_EVENTS) {
    return jsonResponse(400, { ok: false, error: "Expected 1-50 events." });
  }

  const sanitized = events.map(sanitizeEvent).filter(Boolean);
  if (sanitized.length === 0) {
    return jsonResponse(400, { ok: false, error: "No valid events were supplied." });
  }

  await env.TELEMETRY_QUEUE.send({
    schema_version: SCHEMA_VERSION,
    received_at: new Date().toISOString(),
    events: sanitized
  });

  return jsonResponse(202, { ok: true, accepted: sanitized.length, dropped: events.length - sanitized.length });
}

async function handleQueue(batch, env) {
  for (const message of batch.messages) {
    const body = message.body;
    if (!body || !Array.isArray(body.events) || body.events.length === 0) {
      message.ack();
      continue;
    }
    const receivedAt = body.received_at || new Date().toISOString();
    const prefix = prefixForDate("raw", receivedAt);
    const key = `${prefix}${Date.now()}-${crypto.randomUUID()}.ndjson.gz`;
    const ndjson = `${body.events.map((event) => JSON.stringify(event)).join("\n")}\n`;
    const compressed = await gzipText(ndjson);
    await env.TELEMETRY_BUCKET.put(key, compressed, {
      httpMetadata: {
        contentType: "application/x-ndjson",
        contentEncoding: "gzip"
      },
      customMetadata: {
        schema_version: String(SCHEMA_VERSION),
        event_count: String(body.events.length)
      }
    });
    message.ack();
  }
}

async function handleScheduled(env) {
  const now = new Date();
  const yesterday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 1));
  const dayIso = yesterday.toISOString();
  const rawPrefix = prefixForDate("raw", dayIso);
  const events = await loadEventsForPrefix(env.TELEMETRY_BUCKET, rawPrefix);
  const summary = buildDailyAggregate(dayIso.slice(0, 10), events);
  const aggregateKey = `${prefixForDate("aggregates", dayIso)}summary.json`;
  await env.TELEMETRY_BUCKET.put(aggregateKey, JSON.stringify(summary, null, 2), {
    httpMetadata: { contentType: "application/json" }
  });

  const rawRetentionDays = Number.parseInt(env.RAW_RETENTION_DAYS || "90", 10);
  const aggregateRetentionDays = monthsToDays(env.AGGREGATE_RETENTION_MONTHS || "24");
  const rawCutoff = new Date(yesterday.getTime() - daysToMilliseconds(rawRetentionDays));
  const aggregateCutoff = new Date(yesterday.getTime() - daysToMilliseconds(aggregateRetentionDays));
  await deletePrefixForDate(env.TELEMETRY_BUCKET, "raw", rawCutoff.toISOString());
  await deletePrefixForDate(env.TELEMETRY_BUCKET, "aggregates", aggregateCutoff.toISOString());
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
      return jsonResponse(200, { ok: true, service: "gms-mcp-telemetry-ingest" });
    }
    return jsonResponse(404, { ok: false, error: "Not found." });
  },

  async queue(batch, env) {
    await handleQueue(batch, env);
  },

  async scheduled(_controller, env) {
    await handleScheduled(env);
  }
};
