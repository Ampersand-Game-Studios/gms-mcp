# Post-Mortem: MCP Stdio Deadlocks & "Silent Hangs"

## Issue Description
Users reported that calling MCP tools (especially on Windows via Cursor) would frequently "hang forever," eventually hitting a timeout without producing any output.

## Root Causes

### 1. Stdio Multiplexing Deadlock (The "Fragile Straw")
Cursor (and other MCP clients) communicate with the server over `stdin`/`stdout`.
The original implementation used `ctx.log()` to stream subprocess output *while* the subprocess was still running.

Because `ctx.log()` emits JSON-RPC notifications over the same `stdout` pipe the client is reading from, if the client (Cursor) applied backpressure or reached a buffer limit, the server would block on a `write()` call. Meanwhile, the subprocess would block on its own `write()` to the pipe that the server was no longer draining.

**Result**: A circular wait (deadlock) where nothing moved until the client-side timeout killed the session.

### 2. Subprocess Stdin Inheritance
By default, Python's `subprocess.Popen` without `stdin=...` allows child processes to inherit the parent's `stdin`.
In an MCP context, the server's `stdin` is the **active protocol stream** from Cursor.

If any tool (or its dependencies) attempted to read from `stdin` (e.g., an `input()` prompt, a `y/n` confirmation, or even a library's TTY detection), it would either:
1. Block forever waiting for user input that would never arrive.
2. Consume raw MCP protocol bytes, corrupting the JSON-RPC stream and causing the client to desynchronize or hang.

## The Fixes

### 1. Isolated Stdin
All subprocesses are now spawned with `stdin=subprocess.DEVNULL`. This ensures they are completely isolated from the MCP protocol stream. Any attempt to read input will return an EOF immediately rather than hanging.

### 2. Batch Logging (No Streaming)
The server no longer uses `ctx.log()` (or any MCP notifications) while a subprocess is active.
Instead:
- Output is captured in memory.
- Output is written to a local diagnostic log file (for troubleshooting).
- The full result is returned as a single JSON-RPC response at the end.

### 3. Preferred Direct Execution
To bypass the overhead and fragility of subprocesses on Windows entirely, the server now defaults to **in-process execution** (`GMS_MCP_ENABLE_DIRECT=1`). This avoids the "cold start" cost of spawning new Python processes and ensures near-instant response times for most operations.

## Lessons Learned
- **MCP is not a Terminal**: Do not treat stdio transport like a shell. It is a strictly framed protocol stream.
- **Never share stdin**: Always isolate child processes from the protocol pipe.
- **Prefer In-Process**: When the tool logic is available as a library, in-process execution is significantly more robust than wrapping a CLI in a subprocess.
