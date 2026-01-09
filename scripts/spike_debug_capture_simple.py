#!/usr/bin/env python3
"""
Simple OutputDebugString capture test.
Run this, then launch a GameMaker game with show_debug_message() calls.
"""

import ctypes
import ctypes.wintypes
import sys
import time

BUFFER_SIZE = 4096
ERROR_ALREADY_EXISTS = 183

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.wintypes.LPVOID),
        ("bInheritHandle", ctypes.wintypes.BOOL),
    ]

def main():
    kernel32 = ctypes.windll.kernel32
    
    print("=" * 60)
    print("OutputDebugString Capture Test")
    print("=" * 60)
    print()
    
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = False
    
    # Create buffer ready event
    buffer_ready = kernel32.CreateEventW(ctypes.byref(sa), False, False, "DBWIN_BUFFER_READY")
    if not buffer_ready:
        print("[ERROR] Failed to create DBWIN_BUFFER_READY")
        return
    
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        print("[ERROR] Another debugger is already capturing!")
        print("        Close DebugView, Visual Studio, etc.")
        kernel32.CloseHandle(buffer_ready)
        return
    
    # Create data ready event  
    data_ready = kernel32.CreateEventW(ctypes.byref(sa), False, False, "DBWIN_DATA_READY")
    if not data_ready:
        print("[ERROR] Failed to create DBWIN_DATA_READY")
        kernel32.CloseHandle(buffer_ready)
        return
    
    # Create shared memory
    file_mapping = kernel32.CreateFileMappingW(
        ctypes.wintypes.HANDLE(-1),
        ctypes.byref(sa),
        0x04,  # PAGE_READWRITE
        0,
        BUFFER_SIZE,
        "DBWIN_BUFFER"
    )
    
    if not file_mapping:
        print("[ERROR] Failed to create file mapping")
        kernel32.CloseHandle(buffer_ready)
        kernel32.CloseHandle(data_ready)
        return
    
    # Map into memory
    buffer_ptr = kernel32.MapViewOfFile(file_mapping, 0x0006, 0, 0, 0)
    if not buffer_ptr:
        print("[ERROR] Failed to map buffer")
        kernel32.CloseHandle(file_mapping)
        kernel32.CloseHandle(buffer_ready)
        kernel32.CloseHandle(data_ready)
        return
    
    print("[OK] Debug capture ready!")
    print("[OK] Launch your GameMaker game now...")
    print("[OK] Press Ctrl+C to stop")
    print()
    print("-" * 60)
    
    message_count = 0
    gm_message_count = 0
    
    try:
        while True:
            # Signal ready for data
            kernel32.SetEvent(buffer_ready)
            
            # Wait for data (500ms timeout)
            result = kernel32.WaitForSingleObject(data_ready, 500)
            
            if result == 0:  # WAIT_OBJECT_0
                # Read PID (first 4 bytes)
                pid = ctypes.cast(buffer_ptr, ctypes.POINTER(ctypes.wintypes.DWORD))[0]
                
                # Read message (after PID)
                msg_ptr = buffer_ptr + 4
                try:
                    message = ctypes.string_at(msg_ptr).decode('utf-8', errors='replace').strip()
                except:
                    message = "<decode error>"
                
                message_count += 1
                
                # Check if it's from GameMaker
                is_gm = "[MCP_TEST]" in message or "GameMaker" in message
                if is_gm:
                    gm_message_count += 1
                    prefix = "[GM] "
                else:
                    prefix = "     "
                
                print(f"{prefix}PID:{pid:5d} | {message[:100]}")
                
    except KeyboardInterrupt:
        print()
        print("-" * 60)
        print(f"[DONE] Captured {message_count} total messages")
        print(f"[DONE] GameMaker messages: {gm_message_count}")
        
        if gm_message_count > 0:
            print()
            print("[SUCCESS] GameMaker DOES emit to OutputDebugString!")
            print("          Zero-modification log capture is POSSIBLE!")
        elif message_count > 0:
            print()
            print("[INFO] Captured other debug messages but none from GameMaker.")
            print("       show_debug_message() may not use OutputDebugString.")
        else:
            print()
            print("[INFO] No messages captured at all.")
            print("       Either nothing emitted debug output, or capture failed.")
    
    finally:
        kernel32.UnmapViewOfFile(buffer_ptr)
        kernel32.CloseHandle(file_mapping)
        kernel32.CloseHandle(buffer_ready)
        kernel32.CloseHandle(data_ready)

if __name__ == "__main__":
    main()
