#include "graph.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>

#define CSV_LINE_SIZE 256

static void set_error(char *buffer, size_t size, const char *message)
{
    if (buffer != NULL && size > 0) {
        snprintf(buffer, size, "%s", message);
    }
}

static uint64_t hash_id(uint64_t value)
{
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    value ^= value >> 31;
    return value;
}

static int reserve_nodes(Graph *graph)
{
    if (graph->node_count < graph->node_capacity) {
        return 1;
    }

    size_t new_capacity =
        graph->node_capacity == 0 ? 1024 : graph->node_capacity * 2;

    GraphNode *new_nodes = realloc(
        graph->nodes,
        new_capacity * sizeof(GraphNode)
    );

    if (new_nodes == NULL) {
        return 0;
    }

    graph->nodes = new_nodes;
    graph->node_capacity = new_capacity;
    return 1;
}

static int reserve_edges(GraphNode *node)
{
    if (node->edge_count < node->edge_capacity) {
        return 1;
    }

    size_t new_capacity =
        node->edge_capacity == 0 ? 4 : node->edge_capacity * 2;

    GraphEdge *new_edges = realloc(
        node->edges,
        new_capacity * sizeof(GraphEdge)
    );

    if (new_edges == NULL) {
        return 0;
    }

    node->edges = new_edges;
    node->edge_capacity = new_capacity;
    return 1;
}

static int build_hash_table(Graph *graph)
{
    size_t capacity = 1;

    while (capacity < graph->node_count * 2) {
        capacity *= 2;
    }

    graph->hash_keys = calloc(capacity, sizeof(uint64_t));
    graph->hash_values = calloc(capacity, sizeof(size_t));

    if (graph->hash_keys == NULL || graph->hash_values == NULL) {
        return 0;
    }

    graph->hash_capacity = capacity;

    for (size_t i = 0; i < graph->node_count; i++) {
        uint64_t id = graph->nodes[i].osm_id;
        size_t slot = (size_t)(hash_id(id) & (capacity - 1));

        while (graph->hash_values[slot] != 0) {
            if (graph->hash_keys[slot] == id) {
                return 0;
            }

            slot = (slot + 1) & (capacity - 1);
        }

        graph->hash_keys[slot] = id;
        graph->hash_values[slot] = i + 1;
    }

    return 1;
}

size_t graph_find_node(const Graph *graph, uint64_t osm_id)
{
    if (graph == NULL || graph->hash_capacity == 0) {
        return SIZE_MAX;
    }

    size_t slot = (size_t)(
        hash_id(osm_id) & (graph->hash_capacity - 1)
    );

    while (graph->hash_values[slot] != 0) {
        if (graph->hash_keys[slot] == osm_id) {
            return graph->hash_values[slot] - 1;
        }

        slot = (slot + 1) & (graph->hash_capacity - 1);
    }

    return SIZE_MAX;
}

static int parse_uint64(const char *text, uint64_t *result)
{
    char *end;
    errno = 0;

    unsigned long long value = strtoull(text, &end, 10);

    if (errno != 0 || end == text || *end != '\0') {
        return 0;
    }

    *result = (uint64_t)value;
    return 1;
}

static int parse_double(const char *text, double *result)
{
    char *end;
    errno = 0;

    double value = strtod(text, &end);

    if (errno != 0 || end == text || *end != '\0' ||
        !isfinite(value)) {
        return 0;
    }

    *result = value;
    return 1;
}

static void remove_line_end(char *line)
{
    line[strcspn(line, "\r\n")] = '\0';
}

int graph_load_csv(
    Graph *graph,
    const char *nodes_path,
    const char *edges_path,
    char *error_message,
    size_t error_size
)
{
    if (graph == NULL || nodes_path == NULL || edges_path == NULL) {
        set_error(error_message, error_size, "Invalid input arguments.");
        return 0;
    }

    memset(graph, 0, sizeof(Graph));

    FILE *nodes_file = fopen(nodes_path, "r");

    if (nodes_file == NULL) {
        set_error(error_message, error_size, "Could not open road_nodes.csv.");
        return 0;
    }

    char line[CSV_LINE_SIZE];

    if (fgets(line, sizeof(line), nodes_file) == NULL) {
        fclose(nodes_file);
        set_error(error_message, error_size, "Node CSV is empty.");
        return 0;
    }


    while (fgets(line, sizeof(line), nodes_file) != NULL) {
        remove_line_end(line);

        if (line[0] == '\0') {
            continue;
        }

        char *id_text = strtok(line, ",");
        char *lat_text = strtok(NULL, ",");
        char *lon_text = strtok(NULL, ",");

        uint64_t id;
        double latitude;
        double longitude;

        if (id_text == NULL || lat_text == NULL || lon_text == NULL ||
            strtok(NULL, ",") != NULL ||
            !parse_uint64(id_text, &id) ||
            !parse_double(lat_text, &latitude) ||
            !parse_double(lon_text, &longitude) ||
            id == 0 ||
            latitude < -90.0 || latitude > 90.0 ||
            longitude < -180.0 || longitude > 180.0) {

            fclose(nodes_file);
            set_error(error_message, error_size, "Invalid row in node CSV.");
            graph_free(graph);
            return 0;
        }

        if (!reserve_nodes(graph)) {
            fclose(nodes_file);
            set_error(error_message, error_size, "Node memory allocation failed.");
            graph_free(graph);
            return 0;
        }

        GraphNode *node = &graph->nodes[graph->node_count];

        node->osm_id = id;
        node->latitude = latitude;
        node->longitude = longitude;
        node->edges = NULL;
        node->edge_count = 0;
        node->edge_capacity = 0;

        graph->node_count++;
    }

    if (ferror(nodes_file)) {
        fclose(nodes_file);
        set_error(error_message, error_size, "Error reading node CSV.");
        graph_free(graph);
        return 0;
    }

    fclose(nodes_file);

    if (graph->node_count == 0) {
        set_error(error_message, error_size, "No graph nodes were loaded.");
        graph_free(graph);
        return 0;
    }

    if (!build_hash_table(graph)) {
        set_error(error_message, error_size, "Could not build node lookup table.");
        graph_free(graph);
        return 0;
    }

    FILE *edges_file = fopen(edges_path, "r");

    if (edges_file == NULL) {
        set_error(error_message, error_size, "Could not open road_edges.csv.");
        graph_free(graph);
        return 0;
    }

    if (fgets(line, sizeof(line), edges_file) == NULL) {
        fclose(edges_file);
        set_error(error_message, error_size, "Edge CSV is empty.");
        graph_free(graph);
        return 0;
    }

    while (fgets(line, sizeof(line), edges_file) != NULL) {
        remove_line_end(line);

        if (line[0] == '\0') {
            continue;
        }

        char *source_text = strtok(line, ",");
        char *destination_text = strtok(NULL, ",");
        char *distance_text = strtok(NULL, ",");

        uint64_t source_id;
        uint64_t destination_id;
        double distance;

        if (source_text == NULL || destination_text == NULL ||
            distance_text == NULL || strtok(NULL, ",") != NULL ||
            !parse_uint64(source_text, &source_id) ||
            !parse_uint64(destination_text, &destination_id) ||
            !parse_double(distance_text, &distance) ||
            source_id == 0 || destination_id == 0 || distance <= 0.0) {

            fclose(edges_file);
            set_error(error_message, error_size, "Invalid row in edge CSV.");
            graph_free(graph);
            return 0;
        }

        size_t source_index = graph_find_node(graph, source_id);
        size_t destination_index = graph_find_node(graph, destination_id);

        if (source_index == SIZE_MAX || destination_index == SIZE_MAX) {
            fclose(edges_file);
            set_error(error_message, error_size, "Edge references an unknown node.");
            graph_free(graph);
            return 0;
        }

        GraphNode *source = &graph->nodes[source_index];

        if (!reserve_edges(source)) {
            fclose(edges_file);
            set_error(error_message, error_size, "Edge memory allocation failed.");
            graph_free(graph);
            return 0;
        }

        GraphEdge *edge = &source->edges[source->edge_count];

        edge->destination = destination_index;
        edge->distance = distance;

        source->edge_count++;
        graph->edge_count++;
    }

    if (ferror(edges_file)) {
        fclose(edges_file);
        set_error(error_message, error_size, "Error reading edge CSV.");
        graph_free(graph);
        return 0;
    }

    fclose(edges_file);

    set_error(error_message, error_size, "OK");
    return 1;
}

void graph_free(Graph *graph)
{
    if (graph == NULL) {
        return;
    }

    for (size_t i = 0; i < graph->node_count; i++) {
        free(graph->nodes[i].edges);
    }

    free(graph->nodes);
    free(graph->hash_keys);
    free(graph->hash_values);

    memset(graph, 0, sizeof(Graph));
}
