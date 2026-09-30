"""Store the local DeepSeek key with Windows user-scoped DPAPI encryption."""
import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


KEY_FILE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ParisBuilder' / 'deepseek.dpapi'


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _transform(value: bytes, encrypt: bool) -> bytes:
    source_buffer = ctypes.create_string_buffer(value)
    source = DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DataBlob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError(ctypes.get_last_error(), 'Windows DPAPI operation failed')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(target.data)


def save_key(key: str) -> None:
    if os.name != 'nt':
        raise RuntimeError('Persistent credentials require Windows DPAPI')
    encrypted = _transform(key.encode('utf-8'), True)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(base64.b64encode(encrypted).decode('ascii'), encoding='ascii')


def load_key() -> str:
    if os.name != 'nt' or not KEY_FILE.exists():
        return ''
    try:
        return _transform(base64.b64decode(KEY_FILE.read_text(encoding='ascii')), False).decode('utf-8')
    except (OSError, ValueError, UnicodeError):
        return ''
