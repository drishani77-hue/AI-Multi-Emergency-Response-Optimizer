#ifndef RESQTECH_RANKING_H
#define RESQTECH_RANKING_H

#include "dijkstra.h"

#include <stdint.h>

typedef struct {
    const char *resource_id;
    size_t base_node;
} ResourceCandidate;

typedef struct {
    const char *resource_id;
    size_t base_node;
    double distance;
} RankedResource;

typedef enum {
    RANKING_SUCCESS = 1,
    RANKING_INVALID_INPUT = -1,
    RANKING_MEMORY_ERROR = -2
} RankingStatus;

RankingStatus rank_resource_candidates(
    const ReverseDijkstraResult *reverse,
    const ResourceCandidate *candidates,
    size_t candidate_count,
    RankedResource **ranked,
    size_t *ranked_count
);

void ranked_resources_free(RankedResource *ranked);

#endif
