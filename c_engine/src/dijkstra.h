#ifndef RESQTECH_DIJKSTRA_H
#define RESQTECH_DIJKSTRA_H

#include "graph.h"

typedef struct {
    size_t *nodes;
    size_t node_count;
    double total_distance;
} DijkstraResult;

typedef struct {
    double *distances;
    size_t *next_nodes;
    size_t node_count;
    size_t destination;
} ReverseDijkstraResult;

typedef enum {
    DIJKSTRA_SUCCESS = 1,
    DIJKSTRA_NO_PATH = 0,
    DIJKSTRA_INVALID_INPUT = -1,
    DIJKSTRA_MEMORY_ERROR = -2
} DijkstraStatus;

DijkstraStatus graph_dijkstra(
    const Graph *graph,
    size_t source,
    size_t destination,
    DijkstraResult *result
);

void dijkstra_result_free(DijkstraResult *result);

DijkstraStatus graph_reverse_dijkstra(
    const Graph *graph,
    size_t destination,
    ReverseDijkstraResult *result
);

DijkstraStatus reverse_dijkstra_get_route(
    const ReverseDijkstraResult *result,
    size_t source,
    size_t **route_nodes,
    size_t *route_count
);

void reverse_dijkstra_result_free(
    ReverseDijkstraResult *result
);

#endif
