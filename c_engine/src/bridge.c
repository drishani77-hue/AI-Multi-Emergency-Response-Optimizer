#include "bridge.h"

#include "graph.h"
#include "dijkstra.h"
#include "ranking.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct {
    Graph graph;
} ResqtechEngine;

static void set_bridge_error(
    char *buffer,
    size_t size,
    const char *message
)
{
    if (buffer != NULL && size > 0) {
        snprintf(buffer, size, "%s", message);
    }
}

void * RESQTECH_CALL resqtech_engine_create(
    const char *nodes_path,
    const char *edges_path,
    char *error_message,
    size_t error_size
)
{
    if (nodes_path == NULL || edges_path == NULL) {
        set_bridge_error(
            error_message,
            error_size,
            "Node or edge CSV path is null."
        );
        return NULL;
    }

    ResqtechEngine *engine = calloc(1, sizeof(ResqtechEngine));

    if (engine == NULL) {
        set_bridge_error(
            error_message,
            error_size,
            "Engine memory allocation failed."
        );
        return NULL;
    }

    if (!graph_load_csv(
        &engine->graph,
        nodes_path,
        edges_path,
        error_message,
        error_size
    )) {
        graph_free(&engine->graph);
        free(engine);
        return NULL;
    }

    return engine;
}

void RESQTECH_CALL resqtech_engine_destroy(void *handle)
{
    if (handle == NULL) {
        return;
    }

    ResqtechEngine *engine = handle;

    graph_free(&engine->graph);
    free(engine);
}

size_t RESQTECH_CALL resqtech_engine_node_count(void *handle)
{
    if (handle == NULL) {
        return 0;
    }

    const ResqtechEngine *engine = handle;
    return engine->graph.node_count;
}

size_t RESQTECH_CALL resqtech_engine_edge_count(void *handle)
{
    if (handle == NULL) {
        return 0;
    }

    const ResqtechEngine *engine = handle;
    return engine->graph.edge_count;
}

int RESQTECH_CALL resqtech_engine_route(
    void *handle,
    uint64_t source_osm_id,
    uint64_t destination_osm_id,
    uint64_t **route_osm_ids,
    size_t *route_count,
    double *total_distance,
    char *error_message,
    size_t error_size
)
{
    if (route_osm_ids == NULL ||
        route_count == NULL ||
        total_distance == NULL) {
        set_bridge_error(
            error_message,
            error_size,
            "Route output arguments are invalid."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    *route_osm_ids = NULL;
    *route_count = 0;
    *total_distance = 0.0;

    if (handle == NULL) {
        set_bridge_error(
            error_message,
            error_size,
            "Engine handle is null."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    ResqtechEngine *engine = handle;
    Graph *graph = &engine->graph;

    size_t source = graph_find_node(graph, source_osm_id);
    size_t destination = graph_find_node(graph, destination_osm_id);

    if (source == SIZE_MAX || destination == SIZE_MAX) {
        set_bridge_error(
            error_message,
            error_size,
            "Source or destination OSM node was not found."
        );
        return RESQTECH_NODE_NOT_FOUND;
    }

    DijkstraResult result = {0};

    DijkstraStatus status = graph_dijkstra(
        graph,
        source,
        destination,
        &result
    );

    if (status == DIJKSTRA_NO_PATH) {
        dijkstra_result_free(&result);

        set_bridge_error(
            error_message,
            error_size,
            "No directed road route exists between the nodes."
        );
        return RESQTECH_NO_PATH;
    }

    if (status == DIJKSTRA_MEMORY_ERROR) {
        dijkstra_result_free(&result);

        set_bridge_error(
            error_message,
            error_size,
            "Route memory allocation failed."
        );
        return RESQTECH_MEMORY_ERROR;
    }

    if (status != DIJKSTRA_SUCCESS) {
        dijkstra_result_free(&result);

        set_bridge_error(
            error_message,
            error_size,
            "Dijkstra returned an internal error."
        );
        return RESQTECH_ENGINE_ERROR;
    }

    if (result.node_count == 0 ||
        result.node_count > SIZE_MAX / sizeof(uint64_t)) {
        dijkstra_result_free(&result);

        set_bridge_error(
            error_message,
            error_size,
            "Invalid route result size."
        );
        return RESQTECH_ENGINE_ERROR;
    }

    uint64_t *osm_ids = malloc(
        result.node_count * sizeof(uint64_t)
    );

    if (osm_ids == NULL) {
        dijkstra_result_free(&result);

        set_bridge_error(
            error_message,
            error_size,
            "Route output allocation failed."
        );
        return RESQTECH_MEMORY_ERROR;
    }

    for (size_t i = 0; i < result.node_count; i++) {
        if (result.nodes[i] >= graph->node_count) {
            free(osm_ids);
            dijkstra_result_free(&result);

            set_bridge_error(
                error_message,
                error_size,
                "Dijkstra returned an invalid node index."
            );
            return RESQTECH_ENGINE_ERROR;
        }

        osm_ids[i] = graph->nodes[result.nodes[i]].osm_id;
    }

    *route_osm_ids = osm_ids;
    *route_count = result.node_count;
    *total_distance = result.total_distance;

    dijkstra_result_free(&result);

    return RESQTECH_OK;
}

int RESQTECH_CALL resqtech_engine_rank_resources(
    void *handle,
    uint64_t emergency_osm_id,
    const char *const *resource_ids,
    const uint64_t *base_osm_ids,
    size_t candidate_count,
    size_t **ranked_candidate_indices,
    double **ranked_distances,
    size_t *ranked_count,
    char *error_message,
    size_t error_size
)
{
    if (ranked_candidate_indices == NULL ||
        ranked_distances == NULL ||
        ranked_count == NULL ||
        (candidate_count > 0 &&
         (resource_ids == NULL || base_osm_ids == NULL))) {
        set_bridge_error(
            error_message,
            error_size,
            "Resource ranking arguments are invalid."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    *ranked_candidate_indices = NULL;
    *ranked_distances = NULL;
    *ranked_count = 0;

    if (handle == NULL) {
        set_bridge_error(
            error_message,
            error_size,
            "Engine handle is null."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    if (candidate_count > SIZE_MAX / sizeof(ResourceCandidate) ||
        candidate_count > SIZE_MAX / sizeof(unsigned char)) {
        set_bridge_error(
            error_message,
            error_size,
            "Candidate list is too large."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    ResqtechEngine *engine = handle;
    Graph *graph = &engine->graph;

    size_t destination = graph_find_node(
        graph,
        emergency_osm_id
    );

    if (destination == SIZE_MAX) {
        set_bridge_error(
            error_message,
            error_size,
            "Emergency OSM node was not found."
        );
        return RESQTECH_NODE_NOT_FOUND;
    }

    ResourceCandidate *candidates = NULL;
    unsigned char *used = NULL;

    if (candidate_count > 0) {
        candidates = calloc(
            candidate_count,
            sizeof(ResourceCandidate)
        );

        used = calloc(candidate_count, sizeof(unsigned char));

        if (candidates == NULL || used == NULL) {
            free(candidates);
            free(used);

            set_bridge_error(
                error_message,
                error_size,
                "Candidate memory allocation failed."
            );
            return RESQTECH_MEMORY_ERROR;
        }

        for (size_t i = 0; i < candidate_count; i++) {
            candidates[i].resource_id = resource_ids[i];
            candidates[i].base_node = graph_find_node(
                graph,
                base_osm_ids[i]
            );
        }
    }

    ReverseDijkstraResult reverse = {0};

    DijkstraStatus dijkstra_status = graph_reverse_dijkstra(
        graph,
        destination,
        &reverse
    );

    if (dijkstra_status != DIJKSTRA_SUCCESS) {
        free(candidates);
        free(used);
        reverse_dijkstra_result_free(&reverse);

        if (dijkstra_status == DIJKSTRA_MEMORY_ERROR) {
            set_bridge_error(
                error_message,
                error_size,
                "Reverse-Dijkstra memory allocation failed."
            );
            return RESQTECH_MEMORY_ERROR;
        }

        set_bridge_error(
            error_message,
            error_size,
            "Reverse-Dijkstra failed."
        );
        return RESQTECH_ENGINE_ERROR;
    }

    RankedResource *ranked = NULL;
    size_t count = 0;

    RankingStatus ranking_status = rank_resource_candidates(
        &reverse,
        candidates,
        candidate_count,
        &ranked,
        &count
    );

    if (ranking_status != RANKING_SUCCESS) {
        free(candidates);
        free(used);
        reverse_dijkstra_result_free(&reverse);
        ranked_resources_free(ranked);

        if (ranking_status == RANKING_MEMORY_ERROR) {
            set_bridge_error(
                error_message,
                error_size,
                "Resource ranking memory allocation failed."
            );
            return RESQTECH_MEMORY_ERROR;
        }

        set_bridge_error(
            error_message,
            error_size,
            "Resource ranking rejected its input."
        );
        return RESQTECH_INVALID_ARGUMENT;
    }

    size_t *indices = NULL;
    double *distances = NULL;

    if (count > 0) {
        if (count > SIZE_MAX / sizeof(size_t) ||
            count > SIZE_MAX / sizeof(double)) {
            free(candidates);
            free(used);
            reverse_dijkstra_result_free(&reverse);
            ranked_resources_free(ranked);

            set_bridge_error(
                error_message,
                error_size,
                "Ranking output is too large."
            );
            return RESQTECH_MEMORY_ERROR;
        }

        indices = malloc(count * sizeof(size_t));
        distances = malloc(count * sizeof(double));

        if (indices == NULL || distances == NULL) {
            free(indices);
            free(distances);
            free(candidates);
            free(used);
            reverse_dijkstra_result_free(&reverse);
            ranked_resources_free(ranked);

            set_bridge_error(
                error_message,
                error_size,
                "Ranking output allocation failed."
            );
            return RESQTECH_MEMORY_ERROR;
        }
    }

    for (size_t j = 0; j < count; j++) {
        size_t original_index = SIZE_MAX;

        for (size_t i = 0; i < candidate_count; i++) {
            if (!used[i] &&
                candidates[i].resource_id == ranked[j].resource_id &&
                candidates[i].base_node == ranked[j].base_node) {
                original_index = i;
                used[i] = 1;
                break;
            }
        }

        if (original_index == SIZE_MAX) {
            free(indices);
            free(distances);
            free(candidates);
            free(used);
            reverse_dijkstra_result_free(&reverse);
            ranked_resources_free(ranked);

            set_bridge_error(
                error_message,
                error_size,
                "Could not map a ranked resource to its input."
            );
            return RESQTECH_ENGINE_ERROR;
        }

        indices[j] = original_index;
        distances[j] = ranked[j].distance;
    }

    *ranked_candidate_indices = indices;
    *ranked_distances = distances;
    *ranked_count = count;

    free(candidates);
    free(used);
    reverse_dijkstra_result_free(&reverse);
    ranked_resources_free(ranked);

    return RESQTECH_OK;
}

void RESQTECH_CALL resqtech_free(void *memory)
{
    free(memory);
}
