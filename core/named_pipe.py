"""Small length-prefixed JSON protocol over a local Windows Named Pipe."""

import ctypes
import json
import os
import struct
import time
from ctypes import wintypes
from typing import Any, Dict, Tuple

MAX_MESSAGE_BYTES = 64 * 1024
DEFAULT_PIPE_NAME = r"\\.\pipe\OpsAgentBroker"


class PipeError(RuntimeError):
    pass


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    ERROR_PIPE_CONNECTED = 535
    ERROR_PIPE_BUSY = 231
    ERROR_FILE_NOT_FOUND = 2
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_READMODE_BYTE = 0x00000000
    PIPE_WAIT = 0x00000000
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    TOKEN_QUERY = 0x0008
    TokenUser = 1

    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetCurrentThread.restype = wintypes.HANDLE
    kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.ImpersonateNamedPipeClient.argtypes = [wintypes.HANDLE]
    advapi32.OpenThreadToken.restype = wintypes.BOOL
    advapi32.OpenThreadToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]


def _ensure_windows() -> None:
    if os.name != "nt":
        raise PipeError("Windows Named Pipes are only available on Windows")


def _close(handle: int) -> None:
    if handle and handle != INVALID_HANDLE_VALUE:
        kernel32.CloseHandle(handle)


def _read_exact(handle: int, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        buffer = ctypes.create_string_buffer(size - len(data))
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            raise PipeError(f"Named Pipe read failed: {ctypes.get_last_error()}")
        if read.value == 0:
            raise PipeError("Named Pipe peer closed the connection")
        data.extend(buffer.raw[:read.value])
    return bytes(data)


def _write_all(handle: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = wintypes.DWORD()
        chunk = data[offset:]
        if not kernel32.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None):
            raise PipeError(f"Named Pipe write failed: {ctypes.get_last_error()}")
        offset += written.value


def receive_json(handle: int) -> Dict[str, Any]:
    size = struct.unpack("!I", _read_exact(handle, 4))[0]
    if not 0 < size <= MAX_MESSAGE_BYTES:
        raise PipeError("Invalid Named Pipe message size")
    value = json.loads(_read_exact(handle, size).decode("utf-8"))
    if not isinstance(value, dict):
        raise PipeError("Named Pipe payload must be a JSON object")
    return value


def send_json(handle: int, value: Dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise PipeError("Named Pipe response exceeds maximum size")
    _write_all(handle, struct.pack("!I", len(payload)) + payload)


def get_client_sid(handle: int) -> str:
    """Read the caller SID by impersonating the connected pipe client."""
    _ensure_windows()
    if not advapi32.ImpersonateNamedPipeClient(handle):
        raise PipeError(f"Unable to impersonate Named Pipe client: {ctypes.get_last_error()}")
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenThreadToken(kernel32.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token)):
            raise PipeError(f"Unable to open client token: {ctypes.get_last_error()}")
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(token, TokenUser, buffer, needed.value, ctypes.byref(needed)):
            raise PipeError(f"Unable to read client token: {ctypes.get_last_error()}")
        sid = ctypes.c_void_p.from_buffer(buffer).value
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise PipeError(f"Unable to convert client SID: {ctypes.get_last_error()}")
        try:
            return sid_text.value
        finally:
            kernel32.LocalFree(sid_text)
    finally:
        if token.value:
            _close(token.value)
        advapi32.RevertToSelf()


class NamedPipeServer:
    def __init__(self, pipe_name: str = DEFAULT_PIPE_NAME):
        _ensure_windows()
        self.pipe_name = pipe_name

    def accept(self) -> int:
        handle = kernel32.CreateNamedPipeW(
            self.pipe_name,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            16,
            MAX_MESSAGE_BYTES,
            MAX_MESSAGE_BYTES,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise PipeError(f"CreateNamedPipe failed: {ctypes.get_last_error()}")
        if not kernel32.ConnectNamedPipe(handle, None):
            error = ctypes.get_last_error()
            if error != ERROR_PIPE_CONNECTED:
                _close(handle)
                raise PipeError(f"ConnectNamedPipe failed: {error}")
        return handle


class NamedPipeClient:
    def __init__(self, pipe_name: str = DEFAULT_PIPE_NAME, timeout_seconds: float = 3.0):
        _ensure_windows()
        self.pipe_name = pipe_name
        self.timeout_seconds = timeout_seconds

    def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        handle = INVALID_HANDLE_VALUE
        while time.monotonic() < deadline:
            handle = kernel32.CreateFileW(
                self.pipe_name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
            )
            if handle != INVALID_HANDLE_VALUE:
                break
            error = ctypes.get_last_error()
            if error not in {ERROR_PIPE_BUSY, ERROR_FILE_NOT_FOUND}:
                raise PipeError(f"Unable to connect to Broker pipe: {error}")
            kernel32.WaitNamedPipeW(self.pipe_name, 200)
        if handle == INVALID_HANDLE_VALUE:
            raise PipeError("OpsAgent Broker is unavailable")
        try:
            send_json(handle, payload)
            return receive_json(handle)
        finally:
            _close(handle)
