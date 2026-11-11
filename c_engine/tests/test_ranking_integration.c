#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <float.h>
#include <math.h>
#include <string.h>

#include "../src/graph.h"
#include "../src/dijkstra.h"
#include "../src/ranking.h"

#define WEST_NODE UINT64_C(10013517538)
#define EAST_NODE UINT64_C(2365388391)
#define TOLERANCE 0.01

int main(void)
{
    Graph graph = {0};
    ReverseDijkstraResult reverse = {0};
    RankedResource *ranked = NULL;
    size_t ranked_count = 0;
    char error_message[256] = {0};

    printf("Loading actual OSM road graph...\n");

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
        printf("Test nodes not found.\n");
        graph_free(&graph);
        return EXIT_FAILURE;
    }

    printf("Test node lookup: PASSED\n");

    printf("\nCalculating distances to emergency location...\n");

    DijkstraStatus status = graph_reverse_dijkstra(
        &graph,
        east,
        &reverse
    );

    if (status != DIJKSTRA_SUCCESS) {
        printf("Reverse-Dijkstra failed: %d\n", status);
        graph_free(&graph);
        return EXIT_FAILURE;
    }

    printf("Reverse-Dijkstra: PASSED\n");

    size_t unreachable = SIZE_MAX;

    for (size_t i = 0; i < graph.node_count; i++) {
        if (reverse.distances[i] == DBL_MAX &&
            i != west &&
            i != east) {
            unreachable = i;
            break;
        }
    }

    ResourceCandidate candidates[4] = {
        {"res_west", west},
        {"res_east", east},
        {"res_unreachable", unreachable},
        {"res_invalid", graph.node_count + 1}
    };

    size_t candidate_count = unreachable == SIZE_MAX ? 3 : 4;

    printf("\nRanking resource candidates...\n");

    RankingStatus ranking_status = rank_resource_candidates(
        &reverse,
        candidates,
        candidate_count,
        &ranked,
        &ranked_count
    );

    if (ranking_status != RANKING_SUCCESS) {
        printf("Resource ranking failed: %d\n", ranking_status);
        reverse_dijkstra_result_free(&reverse);
        graph_free(&graph);
        return EXIT_FAILURE;
    }

    printf("Eligible reachable candidates: %zu\n", ranked_count);

    for (size_t i = 0; i < ranked_count; i++) {
        printf(
            "%zu. %s ? %.2f metres\n",
            i + 1,
            ranked[i].resource_id,
            ranked[i].distance
        );
    }

    int passed = ranked_count == 2;

    if (passed) {
        passed =
            strcmp(ranked[0].resource_id, "res_east") == 0 &&
            strcmp(ranked[1].resource_id, "res_west") == 0 &&
            fabs(ranked[0].distance) <= TOLERANCE &&
            fabs(ranked[1].distance - 30840.91) <= TOLERANCE;
    }

    printf(
        "\nActual graph ranking verification: %s\n",
        passed ? "PASSED" : "FAILED"
    );

    ranked_resources_free(ranked);
    reverse_dijkstra_result_free(&reverse);
    graph_free(&graph);

    if (passed) {
        printf("\nRESULT: RESOURCE RANKING INTEGRATION PASSED\n");
        return EXIT_SUCCESS;
    }

    printf("\nRESULT: RESOURCE RANKING INTEGRATION FAILED\n");
    return EXIT_FAILURE;
}
