#include "ranking.h"

#include <float.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

static int compare_ranked_resources(
    const void *left,
    const void *right
)
{
    const RankedResource *a = left;
    const RankedResource *b = right;

    if (a->distance < b->distance) {
        return -1;
    }

    if (a->distance > b->distance) {
        return 1;
    }

    return strcmp(a->resource_id, b->resource_id);
}

RankingStatus rank_resource_candidates(
    const ReverseDijkstraResult *reverse,
    const ResourceCandidate *candidates,
    size_t candidate_count,
    RankedResource **ranked,
    size_t *ranked_count
)
{
    if (ranked == NULL || ranked_count == NULL) {
        return RANKING_INVALID_INPUT;
    }

    *ranked = NULL;
    *ranked_count = 0;

    if (reverse == NULL ||
        reverse->distances == NULL ||
        reverse->next_nodes == NULL ||
        reverse->node_count == 0 ||
        (candidate_count > 0 && candidates == NULL)) {
        return RANKING_INVALID_INPUT;
    }

    if (candidate_count == 0) {
        return RANKING_SUCCESS;
    }

    if (candidate_count > SIZE_MAX / sizeof(RankedResource)) {
        return RANKING_MEMORY_ERROR;
    }

    RankedResource *results = malloc(
        candidate_count * sizeof(RankedResource)
    );

    if (results == NULL) {
        return RANKING_MEMORY_ERROR;
    }

    size_t count = 0;

    for (size_t i = 0; i < candidate_count; i++) {
        const ResourceCandidate *candidate = &candidates[i];

        if (candidate->resource_id == NULL ||
            candidate->resource_id[0] == '\0') {
            free(results);
            return RANKING_INVALID_INPUT;
        }

        if (candidate->base_node >= reverse->node_count) {
            continue;
        }

        double distance = reverse->distances[candidate->base_node];

        if (distance == DBL_MAX || !isfinite(distance) || distance < 0.0) {
            continue;
        }

        results[count].resource_id = candidate->resource_id;
        results[count].base_node = candidate->base_node;
        results[count].distance = distance;
        count++;
    }

    qsort(
        results,
        count,
        sizeof(RankedResource),
        compare_ranked_resources
    );

    *ranked = results;
    *ranked_count = count;

    return RANKING_SUCCESS;
}

void ranked_resources_free(RankedResource *ranked)
{
    free(ranked);
}
