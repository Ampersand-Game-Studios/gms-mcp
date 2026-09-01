import http from "node:http";

const listenHost = "127.0.0.1";
const listenPort = Number.parseInt(process.env.GMS_MCP_PROXY_PORT ?? "8765", 10);
const upstreamPort = Number.parseInt(process.env.GMS_MCP_UPSTREAM_PORT ?? "8767", 10);
const bearerToken = process.env.GMS_MCP_HTTP_BEARER_TOKEN;

if (!bearerToken) {
  throw new Error("GMS_MCP_HTTP_BEARER_TOKEN is required");
}

const publicAuthority = `${listenHost}:${listenPort}`;
const upstreamAuthority = `${listenHost}:${upstreamPort}`;

const proxy = http.createServer((request, response) => {
  const headers = {
    ...request.headers,
    authorization: `Bearer ${bearerToken}`,
  };
  if (headers.host === publicAuthority) {
    headers.host = upstreamAuthority;
  }
  if (headers.origin === `http://${publicAuthority}`) {
    headers.origin = `http://${upstreamAuthority}`;
  }

  const upstream = http.request(
    {
      host: listenHost,
      port: upstreamPort,
      method: request.method,
      path: request.url,
      headers,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "text/plain" });
    }
    response.end("MCP conformance upstream unavailable");
  });
  request.on("aborted", () => upstream.destroy());
  request.pipe(upstream);
});

proxy.listen(listenPort, listenHost);
