"""Read and switch the Windows default recording device.

The tray calls this only when the user picks 「录音豆」 or 「系统麦克风」 in
the panel; the bridge itself never changes a default device. Switching sets
the console, multimedia and communications roles together, the same as
picking the device in the Windows sound settings plus 「设为默认通信设备」.

The COM calls are plain ctypes and are made only inside the functions, so the
module imports anywhere and the choice logic can be tested off Windows.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from soundcore_diag.cable import is_standard_cable_output

CLSID_MMDEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
# IPolicyConfig is undocumented but stable since Windows 7; the Windows sound
# settings and common audio switchers use it to set the default endpoint.
CLSID_POLICY_CONFIG_CLIENT = "{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}"
IID_IPOLICY_CONFIG = "{F8679F50-850A-41CF-9C72-430F290290C8}"
PKEY_DEVICE_FRIENDLY_NAME = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)

E_CAPTURE = 1
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications
DEVICE_STATE_ACTIVE = 0x1
CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
STGM_READ = 0
VT_LPWSTR = 31

# vtable slots, counting IUnknown's three
_RELEASE = 2
_ENUM_AUDIO_ENDPOINTS = 3
_GET_DEFAULT_AUDIO_ENDPOINT = 4
_COLLECTION_GET_COUNT = 3
_COLLECTION_ITEM = 4
_DEVICE_OPEN_PROPERTY_STORE = 4
_DEVICE_GET_ID = 5
_STORE_GET_VALUE = 5
_POLICY_SET_DEFAULT_ENDPOINT = 13


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str

    @property
    def is_bean(self) -> bool:
        return is_standard_cable_output(self.name)


@dataclass(frozen=True)
class Mics:
    """Active recording devices and which one is the default now."""

    default_id: str
    endpoints: tuple[Endpoint, ...]

    @property
    def bean(self) -> Endpoint | None:
        found = [item for item in self.endpoints if item.is_bean]
        return found[0] if len(found) == 1 else None

    @property
    def current(self) -> str:
        """"bean", "system", or "" when there is no default."""
        for item in self.endpoints:
            if item.id == self.default_id:
                return "bean" if item.is_bean else "system"
        return ""

    def system(self, remembered: str = "") -> Endpoint | None:
        """The microphone to go back to: the one in use before the bean, if
        it is still there, else the current default, else the first one."""
        others = [item for item in self.endpoints if not item.is_bean]
        for wanted in (remembered, self.default_id):
            for item in others:
                if item.id == wanted:
                    return item
        return others[0] if others else None


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("value", ctypes.c_void_p),
        ("extra", ctypes.c_void_p),
    ]


def _guid(text: str) -> _GUID:
    out = _GUID()
    if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(out)) != 0:
        raise OSError("bad guid")
    return out


def _method(obj: ctypes.c_void_p, slot: int, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    func = proto(vtable[slot])
    return lambda *args: func(obj, *args)


def _release(obj: ctypes.c_void_p) -> None:
    if obj and obj.value:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])(obj)
        obj.value = None


def _create(clsid: str, iid: str) -> ctypes.c_void_p:
    obj = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(
        ctypes.byref(_guid(clsid)), None, CLSCTX_ALL, ctypes.byref(_guid(iid)), ctypes.byref(obj)
    )
    if hr < 0 or not obj.value:
        raise OSError(f"CoCreateInstance 0x{hr & 0xFFFFFFFF:08X}")
    return obj


class _Com:
    def __enter__(self) -> "_Com":
        ole32 = ctypes.windll.ole32
        ole32.CoCreateInstance.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p
        ]
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        ole32.CLSIDFromString.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.PropVariantClear.argtypes = [ctypes.c_void_p]
        hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED) & 0xFFFFFFFF
        # S_OK or S_FALSE need a matching uninit; RPC_E_CHANGED_MODE does not.
        self._uninit = hr in (0, 1)
        return self

    def __exit__(self, *_exc) -> None:
        if self._uninit:
            ctypes.windll.ole32.CoUninitialize()


def _device_id(device: ctypes.c_void_p) -> str:
    raw = ctypes.c_void_p()
    if _method(device, _DEVICE_GET_ID, ctypes.c_void_p)(ctypes.byref(raw)) < 0 or not raw.value:
        return ""
    try:
        return ctypes.wstring_at(raw.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(raw)


def _friendly_name(device: ctypes.c_void_p) -> str:
    store = ctypes.c_void_p()
    if _method(device, _DEVICE_OPEN_PROPERTY_STORE, ctypes.c_uint32, ctypes.c_void_p)(
        STGM_READ, ctypes.byref(store)
    ) < 0:
        return ""
    try:
        key = _PROPERTYKEY(_guid(PKEY_DEVICE_FRIENDLY_NAME[0]), PKEY_DEVICE_FRIENDLY_NAME[1])
        value = _PROPVARIANT()
        if _method(store, _STORE_GET_VALUE, ctypes.c_void_p, ctypes.c_void_p)(
            ctypes.byref(key), ctypes.byref(value)
        ) < 0:
            return ""
        try:
            if value.vt == VT_LPWSTR and value.value:
                return ctypes.wstring_at(value.value)
            return ""
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))
    finally:
        _release(store)


def read() -> Mics | None:
    """The active recording devices, or None if Windows would not say."""
    try:
        with _Com():
            enum = _create(CLSID_MMDEVICE_ENUMERATOR, IID_IMMDEVICE_ENUMERATOR)
            try:
                default_id = ""
                device = ctypes.c_void_p()
                get_default = _method(enum, _GET_DEFAULT_AUDIO_ENDPOINT, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
                if get_default(E_CAPTURE, 0, ctypes.byref(device)) >= 0 and device.value:
                    default_id = _device_id(device)
                _release(device)

                collection = ctypes.c_void_p()
                list_endpoints = _method(enum, _ENUM_AUDIO_ENDPOINTS, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p)
                if list_endpoints(E_CAPTURE, DEVICE_STATE_ACTIVE, ctypes.byref(collection)) < 0:
                    return None
                endpoints = []
                try:
                    count = ctypes.c_uint32()
                    _method(collection, _COLLECTION_GET_COUNT, ctypes.c_void_p)(ctypes.byref(count))
                    item_at = _method(collection, _COLLECTION_ITEM, ctypes.c_uint32, ctypes.c_void_p)
                    for index in range(count.value):
                        item = ctypes.c_void_p()
                        if item_at(index, ctypes.byref(item)) < 0 or not item.value:
                            continue
                        try:
                            endpoint_id = _device_id(item)
                            if endpoint_id:
                                endpoints.append(Endpoint(endpoint_id, _friendly_name(item)))
                        finally:
                            _release(item)
                finally:
                    _release(collection)
                return Mics(default_id, tuple(endpoints))
            finally:
                _release(enum)
    except (OSError, AttributeError, ValueError):
        return None


def set_default(endpoint_id: str) -> bool:
    """Make endpoint_id the default recording device for every role."""
    try:
        with _Com():
            policy = _create(CLSID_POLICY_CONFIG_CLIENT, IID_IPOLICY_CONFIG)
            try:
                set_endpoint = _method(policy, _POLICY_SET_DEFAULT_ENDPOINT, ctypes.c_wchar_p, ctypes.c_int)
                return all(set_endpoint(endpoint_id, role) >= 0 for role in ROLES)
            finally:
                _release(policy)
    except (OSError, AttributeError, ValueError):
        return False
