#include "../src/graph.h"

#include <stdio.h>
#include <math.h>
#include <stdint.h>

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

    printf("\nGraph loaded successfully.\n");
    printf("Nodes: %zu\n", graph.node_count);
    printf("Directed edges: %zu\n", graph.edge_count);

    if (graph.node_count != 118628 ||
        graph.edge_count != 241998) {

        printf("COUNT CHECK FAILED.\n");
        graph_free(&graph);
        return 1;
    }

    printf("Node and edge counts: PASSED\n");

    size_t west = graph_find_node(&graph, UINT64_C(10013517538));
    size_t east = graph_find_node(&graph, UINT64_C(2365388391));

    if (west == SIZE_MAX || east == SIZE_MAX) {
        printf("KNOWN NODE LOOKUP FAILED.\n");
        graph_free(&graph);
        return 1;
    }

    printf("Known OSM node lookup: PASSED\n");
    printf("West node index: %zu\n", west);
    printf("East node index: %zu\n", east);

    size_t verified_edges = 0;

    for (size_t i = 0; i < graph.node_count; i++) {
        GraphNode *node = &graph.nodes[i];

        for (size_t j = 0; j < node->edge_count; j++) {
            GraphEdge *edge = &node->edges[j];

            if (edge->destination >= graph.node_count ||
                !isfinite(edge->distance) ||
                edge->distance <= 0.0) {

                printf("INVALID EDGE FOUND.\n");
                graph_free(&graph);
                return 1;
            }

            verified_edges++;
        }
    }

    if (verified_edges != graph.edge_count) {
        printf("EDGE COUNT VERIFICATION FAILED.\n");
        graph_free(&graph);
        return 1;
    }

    printf("All edge references and distances: PASSED\n");
    printf("Verified edges: %zu\n", verified_edges);

    graph_free(&graph);

    printf("\nRESULT: ALL C GRAPH LOADING TESTS PASSED\n");

    return 0;
}
