#ifndef RESQTECH_GRAPH_H
#define RESQTECH_GRAPH_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    size_t destination;
    double distance;
} GraphEdge;

typedef struct {
    uint64_t osm_id;
    double latitude;
    double longitude;

    GraphEdge *edges;
    size_t edge_count;
    size_t edge_capacity;
} GraphNode;

typedef struct {
    GraphNode *nodes;
    size_t node_count;
    size_t node_capacity;
    size_t edge_count;

    uint64_t *hash_keys;
    size_t *hash_values;
    size_t hash_capacity;
} Graph;

int graph_load_csv(
    Graph *graph,
    const char *nodes_path,
    const char *edges_path,
    char *error_message,
    size_t error_size
);

void graph_free(Graph *graph);

size_t graph_find_node(const Graph *graph, uint64_t osm_id);

#endif
