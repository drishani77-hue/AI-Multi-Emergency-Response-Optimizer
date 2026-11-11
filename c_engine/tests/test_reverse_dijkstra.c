#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>
#include <float.h>

#include "../src/graph.h"
#include "../src/dijkstra.h"

#define WEST_NODE UINT64_C(10013517538)
#define EAST_NODE UINT64_C(2365388391)
#define DISTANCE_TOLERANCE 0.01

static int verify_route(
    const Graph *graph,
    const ReverseDijkstraResult *reverse,
    size_t source,
    size_t destination
)
{
    size_t *route = NULL;
    size_t route_count = 0;

    DijkstraStatus status = reverse_dijkstra_get_route(
        reverse,
        source,
        &route,
        &route_count
    );

    if (status != DIJKSTRA_SUCCESS) {
        printf("Route reconstruction failed. Status: %d\n", status);
        return 0;
    }

    if (route_count == 0 ||
        route[0] != source ||
        route[route_count - 1] != destination) {
        printf("Route endpoints are incorrect.\n");
        free(route);
        return 0;
    }

    double total_distance = 0.0;

    for (size_t i = 0; i + 1 < route_count; i++) {
        size_t from = route[i];
        size_t to = route[i + 1];

        double minimum_edge_distance = INFINITY;

        for (size_t j = 0; j < graph->nodes[from].edge_count; j++) {
            const GraphEdge *edge = &graph->nodes[from].edges[j];

            if (edge->destination == to &&
                edge->distance < minimum_edge_distance) {
                minimum_edge_distance = edge->distance;
            }
        }

        if (!isfinite(minimum_edge_distance)) {
            printf("Invalid directed road edge in reconstructed route.\n");
            free(route);
            return 0;
        }

        total_distance += minimum_edge_distance;
    }

    if (fabs(total_distance - reverse->distances[source]) >
        DISTANCE_TOLERANCE) {
        printf("Route distance does not match reverse-Dijkstra distance.\n");
        free(route);
        return 0;
    }

    printf("Route nodes: %zu\n", route_count);
    printf("Route distance: %.2f metres\n", total_distance);
    printf("Route direction and distance verification: PASSED\n");

    free(route);
    return 1;
}

static int test_direction(
    const Graph *graph,
    size_t source,
    size_t destination,
    const char *label
)
{
    printf("\n%s\n", label);

    ReverseDijkstraResult reverse = {0};
    DijkstraResult forward = {0};

    DijkstraStatus reverse_status = graph_reverse_dijkstra(
        graph,
        destination,
        &reverse
    );

    if (reverse_status != DIJKSTRA_SUCCESS) {
        printf("Reverse-Dijkstra failed. Status: %d\n", reverse_status);
        return 0;
    }

    printf("Reverse-Dijkstra completed successfully.\n");

    if (reverse.node_count != graph->node_count ||
        reverse.destination != destination) {
        printf("Reverse-Dijkstra result metadata is incorrect.\n");
        reverse_dijkstra_result_free(&reverse);
        return 0;
    }

    if (reverse.distances[source] == INFINITY ||
        reverse.distances[source] == HUGE_VAL ||
        reverse.distances[source] == DBL_MAX) {
        printf("Expected route was not found.\n");
        reverse_dijkstra_result_free(&reverse);
        return 0;
    }

    DijkstraStatus forward_status = graph_dijkstra(
        graph,
        source,
        destination,
        &forward
    );

    if (forward_status != DIJKSTRA_SUCCESS) {
        printf("Forward-Dijkstra comparison failed.\n");
        reverse_dijkstra_result_free(&reverse);
        return 0;
    }

    printf("Reverse distance: %.2f metres\n", reverse.distances[source]);
    printf("Forward distance: %.2f metres\n", forward.total_distance);

    if (fabs(reverse.distances[source] - forward.total_distance) >
        DISTANCE_TOLERANCE) {
        printf("Forward and reverse distances do not match.\n");
        dijkstra_result_free(&forward);
        reverse_dijkstra_result_free(&reverse);
        return 0;
    }

    printf("Forward/reverse comparison: PASSED\n");

    int route_ok = verify_route(
        graph,
        &reverse,
        source,
        destination
    );

    dijkstra_result_free(&forward);
    reverse_dijkstra_result_free(&reverse);

    return route_ok;
}

int main(void)
{
    Graph graph = {0};
    char error_message[256] = {0};

    printf("Loading OSM road graph...\n");

    if (!graph_load_csv(
            &graph,
            "data/road_nodes.csv",
            "data/road_edges.csv",
            error_message,
            sizeof(error_message))) {
        printf("Graph loading failed: %s\n", error_message);
        return EXIT_FAILURE;
    }

    printf("Nodes: %zu\n", graph.node_count);
    printf("Directed edges: %zu\n", graph.edge_count);

    size_t west = graph_find_node(&graph, WEST_NODE);
    size_t east = graph_find_node(&graph, EAST_NODE);

    if (west == SIZE_MAX || east == SIZE_MAX) {
        printf("Test nodes could not be found.\n");
        graph_free(&graph);
        return EXIT_FAILURE;
    }

    printf("Test node lookup: PASSED\n");

    int west_to_east = test_direction(
        &graph,
        west,
        east,
        "WEST TO EAST"
    );

    int east_to_west = test_direction(
        &graph,
        east,
        west,
        "EAST TO WEST"
    );

    printf("\nSOURCE EQUALS DESTINATION\n");

    ReverseDijkstraResult same_node = {0};

    DijkstraStatus same_status = graph_reverse_dijkstra(
        &graph,
        west,
        &same_node
    );

    int same_ok = 0;

    if (same_status == DIJKSTRA_SUCCESS &&
        same_node.distances[west] == 0.0) {
        size_t *route = NULL;
        size_t route_count = 0;

        if (reverse_dijkstra_get_route(
                &same_node,
                west,
                &route,
                &route_count
            ) == DIJKSTRA_SUCCESS &&
            route_count == 1 &&
            route[0] == west) {
            same_ok = 1;
        }

        free(route);
    }

    printf("Same-node test: %s\n", same_ok ? "PASSED" : "FAILED");

    reverse_dijkstra_result_free(&same_node);
    graph_free(&graph);

    if (west_to_east && east_to_west && same_ok) {
        printf("\nRESULT: ALL REVERSE-DIJKSTRA TESTS PASSED\n");
        return EXIT_SUCCESS;
    }

    printf("\nRESULT: REVERSE-DIJKSTRA TESTS FAILED\n");
    return EXIT_FAILURE;
}
