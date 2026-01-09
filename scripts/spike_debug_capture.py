#!/usr/bin/env python3
"""
Spike: Test if GameMaker's show_debug_message() emits to Windows OutputDebugString.

This script attempts to capture debug output from a running process using
the Windows debugging API. If successful, we can capture GameMaker game logs
without modifying the game code at all.

Run this script, then launch a GameMaker game that calls show_debug_message().
"""

import ctypes
import ctypes.wintypes
import threading
import time
import sys
from datetime import datetime

# Windows API constants
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
ERROR_ALREADY_EXISTS = 183

# Structures for OutputDebugString capture
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.wintypes.LPVOID),
        ("bInheritHandle", ctypes.wintypes.BOOL),
    ]


def capture_debug_strings(duration_seconds: int = 30, verbose: bool = True):
    """
    Capture OutputDebugString messages from any process for a specified duration.
    
    This uses the DBWIN_BUFFER shared memory mechanism that tools like
    DebugView use to capture debug output.
    
    Args:
        duration_seconds: How long to capture (default 30s)
        verbose: Print messages as they arrive
        
    Returns:
        List of captured debug messages
    """
    kernel32 = ctypes.windll.kernel32
    
    # Create/open the shared objects that OutputDebugString uses
    # These are system-wide objects that debuggers listen to
    
    BUFFER_SIZE = 4096
    
    # Security attributes for shared objects
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = False
    
    # Create the buffer ready event (signaled when buffer is ready to receive)
    buffer_ready_event = kernel32.CreateEventW(
        ctypes.byref(sa),
        False,  # Auto-reset
        False,  # Initial state: not signaled
        "DBWIN_BUFFER_READY"
    )
    
    if not buffer_ready_event:
        print("[ERROR] Failed to create DBWIN_BUFFER_READY event")
        return []
    
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        print("[WARN] Another debugger may be capturing OutputDebugString")
        print("       (e.g., DebugView, Visual Studio)")
        print("       Close other debuggers and try again.")
        kernel32.CloseHandle(buffer_ready_event)
        return []
    
    # Create the data ready event (signaled when data is available)
    data_ready_event = kernel32.CreateEventW(
        ctypes.byref(sa),
        False,  # Auto-reset
        False,  # Initial state: not signaled
        "DBWIN_DATA_READY"
    )
    
    if not data_ready_event:
        print("[ERROR] Failed to create DBWIN_DATA_READY event")
        kernel32.CloseHandle(buffer_ready_event)
        return []
    
    # Create the shared memory buffer
    file_mapping = kernel32.CreateFileMappingW(
        ctypes.wintypes.HANDLE(-1),  # INVALID_HANDLE_VALUE = page file
        ctypes.byref(sa),
        0x04,  # PAGE_READWRITE
        0,
        BUFFER_SIZE,
        "DBWIN_BUFFER"
    )
    
    if not file_mapping:
        print("[ERROR] Failed to create DBWIN_BUFFER file mapping")
        kernel32.CloseHandle(buffer_ready_event)
        kernel32.CloseHandle(data_ready_event)
        return []
    
    # Map the buffer into our address space
    buffer_ptr = kernel32.MapViewOfFile(
        file_mapping,
        0x0006,  # FILE_MAP_READ | FILE_MAP_WRITE
        0,
        0,
        0
    )
    
    if not buffer_ptr:
        print("[ERROR] Failed to map DBWIN_BUFFER")
        kernel32.CloseHandle(file_mapping)
        kernel32.CloseHandle(buffer_ready_event)
        kernel32.CloseHandle(data_ready_event)
        return []
    
    print(f"[OK] OutputDebugString capture initialized")
    print(f"[OK] Listening for {duration_seconds} seconds...")
    print(f"[OK] Launch your GameMaker game now!")
    print("-" * 60)
    
    captured_messages = []
    start_time = time.time()
    
    try:
        while (time.time() - start_time) < duration_seconds:
            # Signal that buffer is ready
            kernel32.SetEvent(buffer_ready_event)
            
            # Wait for data (100ms timeout to allow checking elapsed time)
            result = kernel32.WaitForSingleObject(data_ready_event, 100)
            
            if result == WAIT_OBJECT_0:
                # Data is available - read it
                # Buffer format: 4 bytes PID + string data
                pid = ctypes.cast(buffer_ptr, ctypes.POINTER(ctypes.wintypes.DWORD))[0]
                message_ptr = buffer_ptr + 4
                message = ctypes.string_at(message_ptr).decode('utf-8', errors='replace').strip()
                
                if message:
                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    entry = f"[{timestamp}] PID:{pid} | {message}"
                    captured_messages.append(entry)
                    
                    if verbose:
                        print(entry)
                        
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopping capture...")
        
    finally:
        # Cleanup
        kernel32.UnmapViewOfFile(buffer_ptr)
        kernel32.CloseHandle(file_mapping)
        kernel32.CloseHandle(buffer_ready_event)
        kernel32.CloseHandle(data_ready_event)
    
    print("-" * 60)
    print(f"[DONE] Captured {len(captured_messages)} messages")
    
    return captured_messages


def test_output_debug_string():
    """Test that our capture mechanism works by emitting a test message."""
    print("[TEST] Emitting test OutputDebugString message...")
    
    kernel32 = ctypes.windll.kernel32
    test_message = b"[SPIKE TEST] This is a test message from Python\x00"
    kernel32.OutputDebugStringA(test_message)
    
    print("[TEST] Test message emitted. If capture is working, you should see it.")


if __name__ == "__main__":
    print("=" * 60)
    print("OutputDebugString Capture Spike Test")
    print("=" * 60)
    print()
    print("This test checks if GameMaker's show_debug_message()")
    print("emits to Windows OutputDebugString, which would allow us")
    print("to capture game logs without modifying the game code.")
    print()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        # Run a quick self-test
        print("[MODE] Self-test mode - will emit test messages")
        print()
        
        # Start capture in background
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(capture_debug_strings, duration_seconds=5)
            
            # Give capture time to start
            time.sleep(1)
            
            # Emit test messages
            test_output_debug_string()
            test_output_debug_string()
            test_output_debug_string()
            
            # Wait for capture to complete
            messages = future.result()
            
        if any("SPIKE TEST" in msg for msg in messages):
            print()
            print("[SUCCESS] Self-test passed! OutputDebugString capture works.")
        else:
            print()
            print("[FAILED] Self-test failed. No test messages captured.")
            
    else:
        # Normal mode - wait for external debug messages
        duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30
        messages = capture_debug_strings(duration_seconds=duration)
        
        if messages:
            print()
            print("Captured messages summary:")
            for msg in messages[-10:]:  # Last 10 messages
                print(f"  {msg}")
        else:
            print()
            print("[INFO] No messages captured.")
            print("       This could mean:")
            print("       1. No processes emitted OutputDebugString")
            print("       2. GameMaker doesn't use OutputDebugString")
            print("       3. Another debugger is already capturing")
