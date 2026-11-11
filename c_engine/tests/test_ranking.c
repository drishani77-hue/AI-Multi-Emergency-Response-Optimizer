#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <float.h>

#include "../src/ranking.h"

#define TEST_NODE_COUNT 6

static int test_ranking_order(void)
{
    double distances[TEST_NODE_COUNT] = {
        0.0, 500.0, 200.0, 500.0, DBL_MAX, 100.0
    };

    size_t next_nodes[TEST_NODE_COUNT] = {
        0, 0, 0, 0, SIZE_MAX, 0
    };

    ReverseDijkstraResult reverse = {
        .distances = distances,
        .next_nodes = next_nodes,
        .node_count = TEST_NODE_COUNT,
        .destination = 0
    };

    ResourceCandidate candidates[] = {
        {"res_C", 1},
        {"res_A", 2},
        {"res_B", 3},
        {"res_D", 4},
        {"res_E", 5},
        {"res_INVALID", 99}
    };

    RankedResource *ranked = NULL;
    size_t ranked_count = 0;

    RankingStatus status = rank_resource_candidates(
        &reverse,
        candidates,
        sizeof(candidates) / sizeof(candidates[0]),
        &ranked,
        &ranked_count
    );

    if (status != RANKING_SUCCESS || ranked_count != 4) {
        printf("Ranking count test: FAILED\n");
        ranked_resources_free(ranked);
        return 0;
    }

    const char *expected_ids[] = {
        "res_E", "res_A", "res_B", "res_C"
    };

    const double expected_distances[] = {
        100.0, 200.0, 500.0, 500.0
    };

    for (size_t i = 0; i < ranked_count; i++) {
        if (strcmp(ranked[i].resource_id, expected_ids[i]) != 0 ||
            ranked[i].distance != expected_distances[i]) {
            printf("Ranking order test: FAILED at position %zu\n", i);
            ranked_resources_free(ranked);
            return 0;
        }
    }

    printf("Ascending distance order: PASSED\n");
    printf("Equal-distance tie-break: PASSED\n");
    printf("Unreachable candidate exclusion: PASSED\n");
    printf("Invalid node exclusion: PASSED\n");

    ranked_resources_free(ranked);
    return 1;
}

static int test_empty_candidates(void)
{
    double distances[1] = {0.0};
    size_t next_nodes[1] = {0};

    ReverseDijkstraResult reverse = {
        .distances = distances,
        .next_nodes = next_nodes,
        .node_count = 1,
        .destination = 0
    };

    RankedResource *ranked = NULL;
    size_t ranked_count = 99;

    RankingStatus status = rank_resource_candidates(
        &reverse,
        NULL,
        0,
        &ranked,
        &ranked_count
    );

    int passed = (
        status == RANKING_SUCCESS &&
        ranked == NULL &&
        ranked_count == 0
    );

    printf(
        "Empty candidate list: %s\n",
        passed ? "PASSED" : "FAILED"
    );

    ranked_resources_free(ranked);
    return passed;
}

int main(void)
{
    printf("Testing resource candidate ranking...\n\n");

    int order_ok = test_ranking_order();
    int empty_ok = test_empty_candidates();

    if (order_ok && empty_ok) {
        printf("\nRESULT: ALL RANKING TESTS PASSED\n");
        return EXIT_SUCCESS;
    }

    printf("\nRESULT: RANKING TESTS FAILED\n");
    return EXIT_FAILURE;
}
