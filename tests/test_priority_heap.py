
import subprocess
from pathlib import Path

import pytest

from backend.priority_heap import PriorityHeap, PriorityHeapError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAP_SOURCE = PROJECT_ROOT / "c_engine" / "src" / "priority_heap.c"


@pytest.fixture(scope="module")
def heap_dll(tmp_path_factory):
    build_dir = tmp_path_factory.mktemp("priority_heap")
    dll_path = build_dir / "priority_heap_test.dll"

    command = [
        "gcc",
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-shared",
        "-o",
        str(dll_path),
        str(HEAP_SOURCE),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Priority heap DLL compilation failed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert dll_path.is_file()

    return dll_path


@pytest.fixture
def fire_heap(heap_dll):
    with PriorityHeap("FIRE", dll_path=heap_dll) as heap:
        yield heap


def test_heap_initializes_for_valid_resource_types(heap_dll):
    for resource_type in (
        "FIRE_VEHICLE",
        "AMBULANCE",
        "POLICE_UNIT",
        "RESCUE_VEHICLE",
        "FIRE",
        "POLICE",
    ):
        with PriorityHeap(resource_type, dll_path=heap_dll) as heap:
            assert heap.size == 0


def test_rescue_vehicle_heap_accepts_and_returns_entries(heap_dll):
    with PriorityHeap("RESCUE_VEHICLE", dll_path=heap_dll) as heap:
        heap.push(
            "RU001", "E001", "CRITICAL", "2026-11-12T10:00:00Z"
        )

        result = heap.pop()

        assert result == {
            "requirement_unit_id": "RU001",
            "emergency_id": "E001",
            "resource_type": "RESCUE_VEHICLE",
            "severity": "CRITICAL",
            "reported_at": "2026-11-12T10:00:00Z",
        }


def test_heap_rejects_invalid_resource_type(heap_dll):
    with pytest.raises(ValueError, match="resource_type"):
        PriorityHeap("UNKNOWN", dll_path=heap_dll)


def test_heap_orders_entries_by_severity(fire_heap):
    fire_heap.push(
        "U001", "E001", "LOW", "2026-11-12T10:00:00Z"
    )
    fire_heap.push(
        "U002", "E002", "CRITICAL", "2026-11-12T11:00:00Z"
    )
    fire_heap.push(
        "U003", "E003", "HIGH", "2026-11-12T09:00:00Z"
    )

    assert fire_heap.size == 3
    assert fire_heap.pop()["requirement_unit_id"] == "U002"
    assert fire_heap.pop()["requirement_unit_id"] == "U003"
    assert fire_heap.pop()["requirement_unit_id"] == "U001"


def test_heap_uses_timestamp_as_secondary_priority(fire_heap):
    fire_heap.push(
        "U001", "E001", "HIGH", "2026-11-12T11:00:00Z"
    )
    fire_heap.push(
        "U002", "E002", "HIGH", "2026-11-12T09:00:00Z"
    )

    assert fire_heap.pop()["requirement_unit_id"] == "U002"
    assert fire_heap.pop()["requirement_unit_id"] == "U001"


def test_heap_uses_unit_id_as_final_tie_break(fire_heap):
    fire_heap.push(
        "U002", "E002", "HIGH", "2026-11-12T09:00:00Z"
    )
    fire_heap.push(
        "U001", "E001", "HIGH", "2026-11-12T09:00:00Z"
    )

    assert fire_heap.pop()["requirement_unit_id"] == "U001"
    assert fire_heap.pop()["requirement_unit_id"] == "U002"


def test_heap_returns_none_when_empty(fire_heap):
    assert fire_heap.size == 0
    assert fire_heap.pop() is None


def test_heap_clear_and_reuse(fire_heap):
    fire_heap.push(
        "U001", "E001", "HIGH", "2026-11-12T09:00:00Z"
    )

    fire_heap.clear()

    assert fire_heap.size == 0
    assert fire_heap.pop() is None

    fire_heap.push(
        "U002", "E002", "MEDIUM", "2026-11-12T10:00:00Z"
    )

    assert fire_heap.size == 1
    assert fire_heap.pop()["requirement_unit_id"] == "U002"


def test_heap_rejects_wrong_severity(fire_heap):
    with pytest.raises(ValueError, match="severity"):
        fire_heap.push(
            "U001", "E001", "EXTREME", "2026-11-12T09:00:00Z"
        )


def test_heap_rejects_empty_identifiers(fire_heap):
    with pytest.raises(ValueError, match="requirement_unit_id"):
        fire_heap.push(
            "", "E001", "HIGH", "2026-11-12T09:00:00Z"
        )


def test_heap_rejects_invalid_timestamp(fire_heap):
    with pytest.raises(ValueError, match="Native priority heap"):
        fire_heap.push(
            "U001", "E001", "HIGH", "2026-02-30T09:00:00Z"
        )


def test_heap_rejects_missing_dll(tmp_path):
    missing_dll = tmp_path / "missing.dll"

    with pytest.raises(PriorityHeapError, match="DLL not found"):
        PriorityHeap("FIRE", dll_path=missing_dll)

def test_heap_rejects_dll_missing_required_exports(tmp_path):
    source_path = tmp_path / "incompatible.c"
    dll_path = tmp_path / "incompatible.dll"

    source_path.write_text(
        "void unrelated_function(void) {}",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "gcc",
            "-shared",
            "-o",
            str(dll_path),
            str(source_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Incompatible DLL compilation failed:\n{result.stderr}"
    )

    with pytest.raises(
        PriorityHeapError,
        match="does not contain all required priority heap functions",
    ):
        PriorityHeap("FIRE", dll_path=dll_path)


def test_closed_heap_rejects_operations(heap_dll):
    heap = PriorityHeap("FIRE", dll_path=heap_dll)
    heap.close()

    with pytest.raises(PriorityHeapError, match="closed"):
        heap.push(
            "U001", "E001", "HIGH", "2026-11-12T09:00:00Z"
        )

    with pytest.raises(PriorityHeapError, match="closed"):
        _ = heap.size

    with pytest.raises(PriorityHeapError, match="closed"):
        heap.pop()

    with pytest.raises(PriorityHeapError, match="closed"):
        heap.clear()
