#ifndef RESQTECH_BRIDGE_H
#define RESQTECH_BRIDGE_H

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
    #define RESQTECH_API __declspec(dllexport)
    #define RESQTECH_CALL __cdecl
#else
    #define RESQTECH_API __attribute__((visibility("default")))
    #define RESQTECH_CALL
#endif

enum {
    RESQTECH_OK = 0,
    RESQTECH_INVALID_ARGUMENT = 1,
    RESQTECH_LOAD_ERROR = 2,
    RESQTECH_NODE_NOT_FOUND = 3,
    RESQTECH_NO_PATH = 4,
    RESQTECH_MEMORY_ERROR = 5,
    RESQTECH_ENGINE_ERROR = 6
};

RESQTECH_API void * RESQTECH_CALL resqtech_engine_create(
    const char *nodes_path,
    const char *edges_path,
    char *error_message,
    size_t error_size
);

RESQTECH_API void RESQTECH_CALL resqtech_engine_destroy(
    void *engine
);

RESQTECH_API size_t RESQTECH_CALL resqtech_engine_node_count(
    void *engine
);

RESQTECH_API size_t RESQTECH_CALL resqtech_engine_edge_count(
    void *engine
);

RESQTECH_API int RESQTECH_CALL resqtech_engine_route(
    void *engine,
    uint64_t source_osm_id,
    uint64_t destination_osm_id,
    uint64_t **route_osm_ids,
    size_t *route_count,
    double *total_distance,
    char *error_message,
    size_t error_size
);

RESQTECH_API int RESQTECH_CALL resqtech_engine_rank_resources(
    void *engine,
    uint64_t emergency_osm_id,
    const char *const *resource_ids,
    const uint64_t *base_osm_ids,
    size_t candidate_count,
    size_t **ranked_candidate_indices,
    double **ranked_distances,
    size_t *ranked_count,
    char *error_message,
    size_t error_size
);

RESQTECH_API void RESQTECH_CALL resqtech_free(void *memory);

#endif
