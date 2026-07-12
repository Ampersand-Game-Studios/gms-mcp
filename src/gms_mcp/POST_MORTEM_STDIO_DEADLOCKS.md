# Post-Mortem: MCP Stdio Deadlocks & "Silent Hangs"

> Historical incident record. The current server additionally serializes direct mutations per project, launches subprocesses in their own process groups, bounds retained diagnostics, and terminates complete process trees on timeout. Generic subprocess cancellation also terminates the tree; direct transaction cancellation is deferred until safe completion or the timeout so partial writes are not abandoned.

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

### 3. Original Direct-Mode Stdout Pollution
The original direct mode ran helper code in the MCP server process, which owns `stdout`.
That meant helper code could not treat the server process like a normal terminal:

1. Background helper threads cannot `print(...)` after the tool response has already been sent.
2. Optional services started in-process (such as the TCP bridge server) cannot write lifecycle logs to stdout.
3. Child game processes launched from direct mode must not inherit the MCP server's stdio handles.

Any of those will inject plain text into the JSON-RPC stream and cause the client to drop the transport.

## The Fixes

### 1. Isolated Stdin
All subprocesses are now spawned with `stdin=subprocess.DEVNULL`. This ensures they are completely isolated from the MCP protocol stream. Any attempt to read input will return an EOF immediately rather than hanging.

### 2. Batch Logging (No Streaming)
The server no longer uses `ctx.log()` (or any MCP notifications) while a subprocess is active.
Instead:
- Output capture is bounded in memory.
- Output is written to a local diagnostic log file (for troubleshooting).
- The full result is returned as a single JSON-RPC response at the end.

### 3. Isolated Direct Handlers
`GMS_MCP_ENABLE_DIRECT=1` selects typed direct handlers instead of the generic CLI path. Each handler runs in a disposable worker process with bounded output, a timeout, and process-tree cleanup. The worker can use a project-specific cwd without mutating the long-lived MCP server process.

### 4. Silent Background Helpers
Bridge lifecycle events are now logged internally instead of printing to stdout/stderr.
For macOS background local runs, Igor output is still collected for diagnostics, but it is no longer echoed once the MCP tool has returned.
Spawned local game processes are launched with `stdin/stdout/stderr=DEVNULL` so the game cannot write into the MCP transport.

## Lessons Learned
- **MCP is not a Terminal**: Do not treat stdio transport like a shell. It is a strictly framed protocol stream.
- **Never share stdin**: Always isolate child processes from the protocol pipe.
- **Never leak stdout after return**: background threads and optional services must stay silent on MCP stdio.
- **Prefer typed isolation**: Use typed library handlers inside disposable workers; do not execute mutable helper state inside the long-lived MCP server.
