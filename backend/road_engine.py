
from __future__ import annotations

import ctypes
import threading
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DLL_PATH = PROJECT_ROOT / "c_engine" / "build" / "resqtech_engine.dll"
NODES_CSV = PROJECT_ROOT / "data" / "road_nodes.csv"
EDGES_CSV = PROJECT_ROOT / "data" / "road_edges.csv"


class RoadEngineError(RuntimeError):
    """Raised when the native road engine cannot perform an operation."""


class RoadEngine:
    """Python interface to the native ResQTech C road engine."""

    OK = 0
    INVALID_ARGUMENT = 1
    LOAD_ERROR = 2
    NODE_NOT_FOUND = 3
    NO_PATH = 4
    MEMORY_ERROR = 5
    ENGINE_ERROR = 6

    def __init__(
        self,
        dll_path: Path = DLL_PATH,
        nodes_path: Path = NODES_CSV,
        edges_path: Path = EDGES_CSV,
    ) -> None:
        self.dll_path = Path(dll_path)
        self.nodes_path = Path(nodes_path)
        self.edges_path = Path(edges_path)

        for path in (self.dll_path, self.nodes_path, self.edges_path):
            if not path.is_file():
                raise RoadEngineError(f"Required engine file not found: {path}")

        try:
            self._dll = ctypes.CDLL(str(self.dll_path))
        except OSError as exc:
            raise RoadEngineError(
                f"Could not load the native road engine: {exc}"
            ) from exc

        self._configure_functions()

        self._lock = threading.RLock()
        self._handle = None

        error_buffer = ctypes.create_string_buffer(512)

        handle = self._dll.resqtech_engine_create(
            str(self.nodes_path).encode("utf-8"),
            str(self.edges_path).encode("utf-8"),
            error_buffer,
            ctypes.sizeof(error_buffer),
        )

        if not handle:
            message = error_buffer.value.decode("utf-8", errors="replace")
            raise RoadEngineError(
                message or "Native road engine initialization failed."
            )

        self._handle = handle

    def _configure_functions(self) -> None:
        dll = self._dll

        dll.resqtech_engine_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
        ]
        dll.resqtech_engine_create.restype = ctypes.c_void_p

        dll.resqtech_engine_destroy.argtypes = [ctypes.c_void_p]
        dll.resqtech_engine_destroy.restype = None

        dll.resqtech_engine_node_count.argtypes = [ctypes.c_void_p]
        dll.resqtech_engine_node_count.restype = ctypes.c_size_t

        dll.resqtech_engine_edge_count.argtypes = [ctypes.c_void_p]
        dll.resqtech_engine_edge_count.restype = ctypes.c_size_t

        dll.resqtech_engine_route.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint64)),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
        ]
        dll.resqtech_engine_route.restype = ctypes.c_int

        dll.resqtech_engine_rank_resources.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_size_t)),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_double)),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t,
        ]
        dll.resqtech_engine_rank_resources.restype = ctypes.c_int

        dll.resqtech_free.argtypes = [ctypes.c_void_p]
        dll.resqtech_free.restype = None

    @property
    def node_count(self) -> int:
        with self._lock:
            self._ensure_open()
            return int(self._dll.resqtech_engine_node_count(self._handle))

    @property
    def edge_count(self) -> int:
        with self._lock:
            self._ensure_open()
            return int(self._dll.resqtech_engine_edge_count(self._handle))

    def _ensure_open(self) -> None:
        if not self._handle:
            raise RoadEngineError("Road engine is closed.")

    @staticmethod
    def _error_message(buffer: ctypes.Array) -> str:
        return buffer.value.decode("utf-8", errors="replace")

    def route(
        self,
        source_osm_id: int,
        destination_osm_id: int,
    ) -> dict:
        if (
            isinstance(source_osm_id, bool)
            or not isinstance(source_osm_id, int)
            or source_osm_id < 0
            or source_osm_id > 18446744073709551615
        ):
            raise ValueError("source_osm_id must be a valid unsigned 64-bit integer.")

        if (
            isinstance(destination_osm_id, bool)
            or not isinstance(destination_osm_id, int)
            or destination_osm_id < 0
            or destination_osm_id > 18446744073709551615
        ):
            raise ValueError(
                "destination_osm_id must be a valid unsigned 64-bit integer."
            )

        with self._lock:
            self._ensure_open()

            route_pointer = ctypes.POINTER(ctypes.c_uint64)()
            route_count = ctypes.c_size_t()
            total_distance = ctypes.c_double()
            error_buffer = ctypes.create_string_buffer(512)

            status = self._dll.resqtech_engine_route(
                self._handle,
                source_osm_id,
                destination_osm_id,
                ctypes.byref(route_pointer),
                ctypes.byref(route_count),
                ctypes.byref(total_distance),
                error_buffer,
                ctypes.sizeof(error_buffer),
            )

            if status != self.OK:
                message = self._error_message(error_buffer)
                if status == self.NODE_NOT_FOUND:
                    raise ValueError(message or "An OSM node was not found.")
                if status == self.NO_PATH:
                    raise RoadEngineError(
                        message or "No directed road route exists."
                    )
                if status == self.MEMORY_ERROR:
                    raise MemoryError(message or "Route allocation failed.")
                raise RoadEngineError(
                    message or f"Route operation failed: {status}"
                )

            try:
                nodes = [
                    int(route_pointer[index])
                    for index in range(route_count.value)
                ]
            finally:
                if route_pointer:
                    self._dll.resqtech_free(route_pointer)

            return {
                "nodes": nodes,
                "node_count": len(nodes),
                "distance_metres": total_distance.value,
                "distance_km": total_distance.value / 1000.0,
            }

    def rank_resources(
        self,
        emergency_osm_id: int,
        candidates: list[dict],
    ) -> list[dict]:
        if (
            isinstance(emergency_osm_id, bool)
            or not isinstance(emergency_osm_id, int)
            or emergency_osm_id < 0
            or emergency_osm_id > 18446744073709551615
        ):
            raise ValueError("emergency_osm_id must be a valid unsigned 64-bit integer.")

        if not isinstance(candidates, list):
            raise TypeError("candidates must be a list.")

        encoded_ids = []
        base_ids = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise TypeError("Each candidate must be a dictionary.")

            resource_id = candidate.get("resource_id")
            base_osm_id = candidate.get("base_osm_id")

            if (
                not isinstance(resource_id, str)
                or not resource_id
                or "\x00" in resource_id
            ):
                raise ValueError("Every candidate needs a valid resource_id.")

            if (
                isinstance(base_osm_id, bool)
                or not isinstance(base_osm_id, int)
                or base_osm_id < 0
                or base_osm_id > 18446744073709551615
            ):
                raise ValueError(
                    "Every candidate needs a valid unsigned 64-bit base_osm_id."
                )

            encoded_ids.append(resource_id.encode("utf-8"))
            base_ids.append(base_osm_id)

        count = len(candidates)

        if count == 0:
            return []

        resource_array = (ctypes.c_char_p * count)(*encoded_ids)
        base_array = (ctypes.c_uint64 * count)(*base_ids)

        with self._lock:
            self._ensure_open()

            ranked_indices = ctypes.POINTER(ctypes.c_size_t)()
            ranked_distances = ctypes.POINTER(ctypes.c_double)()
            ranked_count = ctypes.c_size_t()
            error_buffer = ctypes.create_string_buffer(512)

            status = self._dll.resqtech_engine_rank_resources(
                self._handle,
                emergency_osm_id,
                resource_array,
                base_array,
                count,
                ctypes.byref(ranked_indices),
                ctypes.byref(ranked_distances),
                ctypes.byref(ranked_count),
                error_buffer,
                ctypes.sizeof(error_buffer),
            )

            if status != self.OK:
                message = self._error_message(error_buffer)
                if status == self.NODE_NOT_FOUND:
                    raise ValueError(
                        message or "Emergency OSM node was not found."
                    )
                if status == self.MEMORY_ERROR:
                    raise MemoryError(
                        message or "Resource ranking allocation failed."
                    )
                raise RoadEngineError(
                    message or f"Resource ranking failed with status {status}."
                )

            try:
                results = []

                for position in range(ranked_count.value):
                    original_index = int(ranked_indices[position])

                    if original_index >= count:
                        raise RoadEngineError(
                            "Native engine returned an invalid candidate index."
                        )

                    results.append(
                        {
                            "resource_id": candidates[original_index]["resource_id"],
                            "base_osm_id": base_ids[original_index],
                            "distance_metres": ranked_distances[position],
                            "distance_km": ranked_distances[position] / 1000.0,
                        }
                    )

                return results

            finally:
                if ranked_indices:
                    self._dll.resqtech_free(ranked_indices)
                if ranked_distances:
                    self._dll.resqtech_free(ranked_distances)

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._dll.resqtech_engine_destroy(self._handle)
                self._handle = None

    def __enter__(self) -> RoadEngine:
        with self._lock:
            self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
