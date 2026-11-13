
from __future__ import annotations

import ctypes
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DLL_PATH = (
    PROJECT_ROOT
    / "c_engine"
    / "build"
    / "resqtech_engine_with_heap.dll"
)


class PriorityHeapError(RuntimeError):
    """Raised when the native priority heap cannot perform an operation."""


class _CResqtechPriorityEntry(ctypes.Structure):
    _fields_ = [
        ("requirement_unit_id", ctypes.c_char_p),
        ("emergency_id", ctypes.c_char_p),
        ("resource_type", ctypes.c_int),
        ("severity", ctypes.c_int),
        ("reported_at", ctypes.c_char_p),
    ]


class PriorityHeap:
    """Python interface to one native ResQTech resource-type priority heap."""

    OK = 0
    INVALID_ARGUMENT = 1
    MEMORY_ERROR = 5
    HEAP_EMPTY = 7

    RESOURCE_TYPES = {
        # Canonical database resource types.
        "FIRE_VEHICLE": 1,
        "AMBULANCE": 2,
        "POLICE_UNIT": 3,
        "RESCUE_VEHICLE": 4,
        # Backwards-compatible aliases.
        "FIRE": 1,
        "POLICE": 3,
    }

    SEVERITIES = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }

    def __init__(
        self,
        resource_type: str,
        dll_path: Path = DEFAULT_DLL_PATH,
    ) -> None:
        if not isinstance(resource_type, str):
            raise TypeError("resource_type must be a string.")

        normalized_type = resource_type.strip().upper()

        if normalized_type not in self.RESOURCE_TYPES:
            raise ValueError(
                "resource_type must be FIRE_VEHICLE, AMBULANCE, "
                "POLICE_UNIT, or RESCUE_VEHICLE."
            )

        self.resource_type = normalized_type
        self._resource_type_value = self.RESOURCE_TYPES[normalized_type]
        self.dll_path = Path(dll_path)
        self._handle = None

        if not self.dll_path.is_file():
            raise PriorityHeapError(
                f"Priority heap DLL not found: {self.dll_path}"
            )

        try:
            self._dll = ctypes.CDLL(str(self.dll_path))
        except OSError as exc:
            raise PriorityHeapError(
                f"Could not load the priority heap DLL: {exc}"
            ) from exc

        self._configure_functions()

        self._handle = self._dll.resqtech_heap_create(
            self._resource_type_value
        )

        if not self._handle:
            raise PriorityHeapError(
                "Native priority heap initialization failed."
            )

    def _configure_functions(self) -> None:
        dll = self._dll
        entry_pointer = ctypes.POINTER(_CResqtechPriorityEntry)

        try:
            dll.resqtech_heap_create.argtypes = [ctypes.c_int]
            dll.resqtech_heap_create.restype = ctypes.c_void_p

            dll.resqtech_heap_push.argtypes = [
                ctypes.c_void_p,
                entry_pointer,
            ]
            dll.resqtech_heap_push.restype = ctypes.c_int

            dll.resqtech_heap_pop.argtypes = [
                ctypes.c_void_p,
                entry_pointer,
            ]
            dll.resqtech_heap_pop.restype = ctypes.c_int

            dll.resqtech_heap_entry_free.argtypes = [entry_pointer]
            dll.resqtech_heap_entry_free.restype = None

            dll.resqtech_heap_size.argtypes = [ctypes.c_void_p]
            dll.resqtech_heap_size.restype = ctypes.c_size_t

            dll.resqtech_heap_clear.argtypes = [ctypes.c_void_p]
            dll.resqtech_heap_clear.restype = None

            dll.resqtech_heap_destroy.argtypes = [ctypes.c_void_p]
            dll.resqtech_heap_destroy.restype = None

        except AttributeError as exc:
            raise PriorityHeapError(
                "The loaded DLL does not contain all required priority "
                "heap functions. Rebuild the DLL with priority_heap.c."
            ) from exc

    def _ensure_open(self) -> None:
        if not self._handle:
            raise PriorityHeapError("Priority heap is closed.")

    @staticmethod
    def _encode_string(value: str, field_name: str) -> bytes:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        if not value or "\x00" in value:
            raise ValueError(
                f"{field_name} must be non-empty and contain no NUL character."
            )

        try:
            return value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"{field_name} must be valid UTF-8 text."
            ) from exc

    def push(
        self,
        requirement_unit_id: str,
        emergency_id: str,
        severity: str,
        reported_at: str,
    ) -> None:
        self._ensure_open()

        unit_bytes = self._encode_string(
            requirement_unit_id,
            "requirement_unit_id",
        )
        emergency_bytes = self._encode_string(
            emergency_id,
            "emergency_id",
        )
        timestamp_bytes = self._encode_string(
            reported_at,
            "reported_at",
        )

        if not isinstance(severity, str):
            raise TypeError("severity must be a string.")

        normalized_severity = severity.strip().upper()

        if normalized_severity not in self.SEVERITIES:
            raise ValueError(
                "severity must be LOW, MEDIUM, HIGH, or CRITICAL."
            )

        entry = _CResqtechPriorityEntry(
            unit_bytes,
            emergency_bytes,
            self._resource_type_value,
            self.SEVERITIES[normalized_severity],
            timestamp_bytes,
        )

        status = self._dll.resqtech_heap_push(
            self._handle,
            ctypes.byref(entry),
        )

        self._check_status(status, "push")

    def pop(self) -> dict | None:
        self._ensure_open()

        entry = _CResqtechPriorityEntry()

        status = self._dll.resqtech_heap_pop(
            self._handle,
            ctypes.byref(entry),
        )

        if status == self.HEAP_EMPTY:
            return None

        if status != self.OK:
            self._check_status(status, "pop")

        try:
            return {
                "requirement_unit_id": ctypes.string_at(
                    entry.requirement_unit_id
                ).decode("utf-8"),
                "emergency_id": ctypes.string_at(
                    entry.emergency_id
                ).decode("utf-8"),
                "resource_type": self.resource_type,
                "severity": self._severity_name(entry.severity),
                "reported_at": ctypes.string_at(
                    entry.reported_at
                ).decode("utf-8"),
            }
        finally:
            self._dll.resqtech_heap_entry_free(
                ctypes.byref(entry)
            )

    @classmethod
    def _severity_name(cls, value: int) -> str:
        for name, number in cls.SEVERITIES.items():
            if number == value:
                return name

        raise PriorityHeapError(
            f"Native heap returned unknown severity: {value}"
        )

    def _check_status(self, status: int, operation: str) -> None:
        if status == self.OK:
            return

        if status == self.INVALID_ARGUMENT:
            raise ValueError(
                f"Native priority heap rejected the {operation} arguments."
            )

        if status == self.MEMORY_ERROR:
            raise MemoryError(
                f"Native priority heap memory allocation failed during {operation}."
            )

        raise PriorityHeapError(
            f"Priority heap {operation} failed with status {status}."
        )

    @property
    def size(self) -> int:
        self._ensure_open()
        return int(self._dll.resqtech_heap_size(self._handle))

    def clear(self) -> None:
        self._ensure_open()
        self._dll.resqtech_heap_clear(self._handle)

    def close(self) -> None:
        if self._handle:
            self._dll.resqtech_heap_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> PriorityHeap:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
