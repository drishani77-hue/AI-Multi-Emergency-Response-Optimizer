#include "../src/graph.h"
#include "../src/dijkstra.h"

#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <float.h>

static int verify_route(
    const Graph *graph,
    const DijkstraResult *result,
    size_t source,
    size_t destination
)
{
    if (result->nodes == NULL ||
        result->node_count == 0 ||
        result->nodes[0] != source ||
        result->nodes[result->node_count - 1] != destination) {
        return 0;
    }

    double verified_distance = 0.0;

    for (size_t i = 0; i + 1 < result->node_count; i++) {
        size_t from = result->nodes[i];
        size_t to = result->nodes[i + 1];

        double minimum_edge_distance = DBL_MAX;

        for (size_t j = 0; j < graph->nodes[from].edge_count; j++) {
            GraphEdge *edge = &graph->nodes[from].edges[j];

            if (edge->destination == to &&
                edge->distance < minimum_edge_distance) {
                minimum_edge_distance = edge->distance;
            }
        }

        if (minimum_edge_distance == DBL_MAX) {
            return 0;
        }

        verified_distance += minimum_edge_distance;
    }

    return fabs(verified_distance - result->total_distance) < 0.001;
}

static int run_route_test(
    const Graph *graph,
    size_t source,
    size_t destination,
    double expected_distance,
    const char *direction
)
{
    DijkstraResult result = {0};

    printf("\n%s\n", direction);

    DijkstraStatus status = graph_dijkstra(
        graph,
        source,
        destination,
        &result
    );

    if (status != DIJKSTRA_SUCCESS) {
        printf("ROUTING FAILED. Status: %d\n", status);
        return 0;
    }

    printf("Route found: Yes\n");
    printf("Route nodes: %zu\n", result.node_count);
    printf("Total distance: %.2f metres\n", result.total_distance);
    printf("Total distance: %.3f km\n",
           result.total_distance / 1000.0);

    if (!verify_route(graph, &result, source, destination)) {
        printf("PATH VERIFICATION FAILED.\n");
        dijkstra_result_free(&result);
        return 0;
    }

    printf("Path and distance verification: PASSED\n");

    if (fabs(result.total_distance - expected_distance) > 0.05) {
        printf("PYTHON COMPARISON FAILED.\n");
        printf("Expected approximately: %.2f metres\n",
               expected_distance);
        dijkstra_result_free(&result);
        return 0;
    }

    printf("Python result comparison: PASSED\n");

    dijkstra_result_free(&result);
    return 1;
}

int main(void)
{
    Graph graph = {0};
    char error[256] = {0};

    printf("Loading OSM graph into C...\n");

    if (!graph_load_csv(
            &graph,
            "data/road_nodes.csv",
            "data/road_edges.csv",
            error,
            sizeof(error))) {
        printf("GRAPH LOAD FAILED: %s\n", error);
        return 1;
    }

    printf("Nodes: %zu\n", graph.node_count);
    printf("Directed edges: %zu\n", graph.edge_count);

    size_t west = graph_find_node(
        &graph,
        UINT64_C(10013517538)
    );

    size_t east = graph_find_node(
        &graph,
        UINT64_C(2365388391)
    );

    if (west == SIZE_MAX || east == SIZE_MAX) {
        printf("TEST NODE LOOKUP FAILED.\n");
        graph_free(&graph);
        return 1;
    }

    printf("Test node lookup: PASSED\n");

    int west_to_east = run_route_test(
        &graph,
        west,
        east,
        30840.91,
        "WEST TO EAST"
    );

    int east_to_west = run_route_test(
        &graph,
        east,
        west,
        31190.00,
        "EAST TO WEST"
    );

    DijkstraResult same_node = {0};

    DijkstraStatus same_status = graph_dijkstra(
        &graph,
        west,
        west,
        &same_node
    );

    int same_node_passed =
        same_status == DIJKSTRA_SUCCESS &&
        same_node.node_count == 1 &&
        same_node.nodes != NULL &&
        same_node.nodes[0] == west &&
        same_node.total_distance == 0.0;

    printf("\nSOURCE EQUALS DESTINATION\n");
    printf("Same-node test: %s\n",
           same_node_passed ? "PASSED" : "FAILED");

    dijkstra_result_free(&same_node);

    graph_free(&graph);

    if (west_to_east && east_to_west && same_node_passed) {
        printf("\nRESULT: ALL C DIJKSTRA TESTS PASSED\n");
        return 0;
    }

    printf("\nRESULT: ONE OR MORE C DIJKSTRA TESTS FAILED\n");
    return 1;
}
