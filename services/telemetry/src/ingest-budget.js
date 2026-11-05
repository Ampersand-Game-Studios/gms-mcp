const MAX_EVENTS_PER_DAY = 50000;
const MAX_BATCHES_PER_MINUTE = 300;
const MAX_CLIENT_EVENTS_PER_DAY = 5000;

function budgetResponse(retryAfter) {
  return new Response(JSON.stringify({ ok: retryAfter === 0 }), {
    status: retryAfter ? 429 : 200,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
      ...(retryAfter ? { "retry-after": String(retryAfter) } : {}),
    },
  });
}

// IPv4 /24 or IPv6 /48: one network cannot exhaust the shared daily budget by
// rotating addresses it controls. Malformed input maps to its own full value.
export function clientNetwork(ip) {
  if (!ip.includes(":")) return ip.split(".").slice(0, 3).join(".");
  const [head, tail = ""] = ip.toLowerCase().split("::");
  const left = head ? head.split(":") : [];
  const right = tail ? tail.split(":") : [];
  const groups = [
    ...left,
    ...Array(Math.max(0, 8 - left.length - right.length)).fill("0"),
    ...right,
  ];
  return groups
    .slice(0, 3)
    .map((group) => group.padStart(4, "0"))
    .join(":");
}

// The object name is a digest that changes every UTC day, and each object erases
// itself at the end of that day, so client objects cannot link a network over time.
export async function clientBudgetName(ip, now = Date.now()) {
  const day = Math.floor(now / 86400000);
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${day}:${clientNetwork(ip)}`),
  );
  const hex = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `client:${hex}`;
}

// The "global" object serves the whole service, across IPs and Cloudflare locations.
// Client objects hold one network's daily share of that budget.
// Only counters are stored; no IP addresses, identities, or event content.
export class IngestBudget {
  constructor(state) {
    this.storage = state.storage;
  }

  async alarm() {
    await this.storage.deleteAll();
  }

  async reserveClient(events) {
    return this.storage.transaction(async (transaction) => {
      const now = Date.now();
      const nextDay = (Math.floor(now / 86400000) + 1) * 86400000;
      const used = (await transaction.get("client_events")) ?? 0;
      if (used + events > MAX_CLIENT_EVENTS_PER_DAY) {
        return Math.max(1, Math.ceil((nextDay - now) / 1000));
      }
      await transaction.put("client_events", used + events);
      if (used === 0) await transaction.setAlarm(nextDay);
      return 0;
    });
  }

  async fetch(request) {
    if (request.method !== "POST") return new Response(null, { status: 405 });
    const { events } = await request.json();
    if (!Number.isSafeInteger(events) || events < 1 || events > 50) {
      return new Response(null, { status: 400 });
    }
    if (new URL(request.url).pathname === "/reserve-client") {
      return budgetResponse(await this.reserveClient(events));
    }
    const retryAfter = await this.storage.transaction(async (transaction) => {
      const now = Date.now();
      const day = Math.floor(now / 86400000);
      const minute = Math.floor(now / 60000);
      const stored = await transaction.get("counters");
      const dailyEvents = stored?.day === day ? stored.events : 0;
      const minuteBatches = stored?.minute === minute ? stored.batches : 0;
      if (dailyEvents + events > MAX_EVENTS_PER_DAY) {
        return Math.max(1, Math.ceil(((day + 1) * 86400000 - now) / 1000));
      }
      if (minuteBatches >= MAX_BATCHES_PER_MINUTE) {
        return Math.max(1, Math.ceil(((minute + 1) * 60000 - now) / 1000));
      }
      // Reserve before queueing. A failed queue send still consumes this quota.
      await transaction.put("counters", {
        day,
        minute,
        events: dailyEvents + events,
        batches: minuteBatches + 1,
      });
      return 0;
    });
    return budgetResponse(retryAfter);
  }
}
