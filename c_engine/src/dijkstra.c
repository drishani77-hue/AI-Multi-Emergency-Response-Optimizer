#include "dijkstra.h"

#include <float.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    size_t node;
    double distance;
} HeapEntry;

typedef struct {
    HeapEntry *entries;
    size_t size;
    size_t capacity;
} MinHeap;

static int heap_push(MinHeap *heap, size_t node, double distance)
{
    if (heap->size == heap->capacity) {
        size_t new_capacity = heap->capacity == 0
            ? 256
            : heap->capacity * 2;

        if (new_capacity < heap->capacity ||
            new_capacity > SIZE_MAX / sizeof(HeapEntry)) {
            return 0;
        }

        HeapEntry *new_entries = realloc(
            heap->entries,
            new_capacity * sizeof(HeapEntry)
        );

        if (new_entries == NULL) {
            return 0;
        }

        heap->entries = new_entries;
        heap->capacity = new_capacity;
    }

    size_t index = heap->size++;

    while (index > 0) {
        size_t parent = (index - 1) / 2;

        if (heap->entries[parent].distance <= distance) {
            break;
        }

        heap->entries[index] = heap->entries[parent];
        index = parent;
    }

    heap->entries[index].node = node;
    heap->entries[index].distance = distance;

    return 1;
}

static HeapEntry heap_pop(MinHeap *heap)
{
    HeapEntry minimum = heap->entries[0];
    HeapEntry last = heap->entries[--heap->size];

    if (heap->size == 0) {
        return minimum;
    }

    heap->entries[0] = last;

    size_t index = 0;

    while (1) {
        size_t left = index * 2 + 1;
        size_t right = left + 1;
        size_t smallest = index;

        if (left < heap->size &&
            heap->entries[left].distance <
            heap->entries[smallest].distance) {
            smallest = left;
        }

        if (right < heap->size &&
            heap->entries[right].distance <
            heap->entries[smallest].distance) {
            smallest = right;
        }

        if (smallest == index) {
            break;
        }

        HeapEntry temporary = heap->entries[index];
        heap->entries[index] = heap->entries[smallest];
        heap->entries[smallest] = temporary;

        index = smallest;
    }

    return minimum;
}
DijkstraStatus graph_dijkstra(
    const Graph *graph,
    size_t source,
    size_t destination,
    DijkstraResult *result
)
{
    if (result == NULL) {
        return DIJKSTRA_INVALID_INPUT;
    }

    result->nodes = NULL;
    result->node_count = 0;
    result->total_distance = 0.0;

    if (graph == NULL ||
        graph->nodes == NULL ||
        graph->node_count == 0 ||
        source >= graph->node_count ||
        destination >= graph->node_count) {
        return DIJKSTRA_INVALID_INPUT;
    }

    if (graph->node_count > SIZE_MAX / sizeof(double) ||
        graph->node_count > SIZE_MAX / sizeof(size_t)) {
        return DIJKSTRA_MEMORY_ERROR;
    }

    size_t count = graph->node_count;

    double *distances = malloc(count * sizeof(double));
    size_t *previous = malloc(count * sizeof(size_t));
    unsigned char *visited = calloc(count, sizeof(unsigned char));

    if (distances == NULL ||
        previous == NULL ||
        visited == NULL) {
        free(distances);
        free(previous);
        free(visited);
        return DIJKSTRA_MEMORY_ERROR;
    }

    for (size_t i = 0; i < count; i++) {
        distances[i] = DBL_MAX;
        previous[i] = SIZE_MAX;
    }

    MinHeap heap = {0};

    distances[source] = 0.0;

    if (!heap_push(&heap, source, 0.0)) {
        free(distances);
        free(previous);
        free(visited);
        free(heap.entries);
        return DIJKSTRA_MEMORY_ERROR;
    }

    int found = 0;

    while (heap.size > 0) {
        HeapEntry current = heap_pop(&heap);
        size_t current_node = current.node;

        if (visited[current_node]) {
            continue;
        }

        if (current.distance > distances[current_node]) {
            continue;
        }

        visited[current_node] = 1;

        if (current_node == destination) {
            found = 1;
            break;
        }

        const GraphNode *node = &graph->nodes[current_node];

        for (size_t i = 0; i < node->edge_count; i++) {
            const GraphEdge *edge = &node->edges[i];
            size_t next_node = edge->destination;

            if (next_node >= count ||
                !isfinite(edge->distance) ||
                edge->distance <= 0.0 ||
                visited[next_node]) {
                continue;
            }

            double new_distance =
                distances[current_node] + edge->distance;

            if (new_distance < distances[next_node]) {
                distances[next_node] = new_distance;
                previous[next_node] = current_node;

                if (!heap_push(&heap, next_node, new_distance)) {
                    free(distances);
                    free(previous);
                    free(visited);
                    free(heap.entries);
                    return DIJKSTRA_MEMORY_ERROR;
                }
            }
        }
    }

    free(heap.entries);
    free(visited);

    if (!found) {
        free(distances);
        free(previous);
        return DIJKSTRA_NO_PATH;
    }

    size_t path_length = 1;
    size_t current = destination;

    while (current != source) {
        current = previous[current];

        if (current == SIZE_MAX || path_length >= count) {
            free(distances);
            free(previous);
            return DIJKSTRA_NO_PATH;
        }

        path_length++;
    }

    if (path_length > SIZE_MAX / sizeof(size_t)) {
        free(distances);
        free(previous);
        return DIJKSTRA_MEMORY_ERROR;
    }

    size_t *path = malloc(path_length * sizeof(size_t));

    if (path == NULL) {
        free(distances);
        free(previous);
        return DIJKSTRA_MEMORY_ERROR;
    }

    current = destination;

    for (size_t i = path_length; i > 0; i--) {
        path[i - 1] = current;

        if (i > 1) {
            current = previous[current];
        }
    }

    result->nodes = path;
    result->node_count = path_length;
    result->total_distance = distances[destination];

    free(distances);
    free(previous);

    return DIJKSTRA_SUCCESS;
}

typedef struct {
    size_t source;
    double distance;
} IncomingEdge;

DijkstraStatus graph_reverse_dijkstra(
    const Graph *graph,
    size_t destination,
    ReverseDijkstraResult *result
)
{
    if (result == NULL) {
        return DIJKSTRA_INVALID_INPUT;
    }

    result->distances = NULL;
    result->next_nodes = NULL;
    result->node_count = 0;
    result->destination = SIZE_MAX;

    if (graph == NULL ||
        graph->nodes == NULL ||
        graph->node_count == 0 ||
        destination >= graph->node_count) {
        return DIJKSTRA_INVALID_INPUT;
    }

    size_t count = graph->node_count;
    size_t edge_count = graph->edge_count;

    if (count >= SIZE_MAX / sizeof(size_t) ||
        count > SIZE_MAX / sizeof(double) ||
        edge_count > SIZE_MAX / sizeof(IncomingEdge)) {
        return DIJKSTRA_MEMORY_ERROR;
    }

    size_t *incoming_counts = calloc(count, sizeof(size_t));
    size_t *offsets = malloc((count + 1) * sizeof(size_t));
    size_t *cursor = malloc(count * sizeof(size_t));
    IncomingEdge *incoming = edge_count == 0
        ? NULL
        : malloc(edge_count * sizeof(IncomingEdge));

    double *distances = malloc(count * sizeof(double));
    size_t *next_nodes = malloc(count * sizeof(size_t));
    unsigned char *visited = calloc(count, sizeof(unsigned char));

    if (incoming_counts == NULL ||
        offsets == NULL ||
        cursor == NULL ||
        (edge_count > 0 && incoming == NULL) ||
        distances == NULL ||
        next_nodes == NULL ||
        visited == NULL) {
        free(incoming_counts);
        free(offsets);
        free(cursor);
        free(incoming);
        free(distances);
        free(next_nodes);
        free(visited);
        return DIJKSTRA_MEMORY_ERROR;
    }

    for (size_t u = 0; u < count; u++) {
        const GraphNode *node = &graph->nodes[u];

        for (size_t j = 0; j < node->edge_count; j++) {
            const GraphEdge *edge = &node->edges[j];

            if (edge->destination >= count ||
                !isfinite(edge->distance) ||
                edge->distance <= 0.0 ||
                incoming_counts[edge->destination] == SIZE_MAX) {
                free(incoming_counts);
                free(offsets);
                free(cursor);
                free(incoming);
                free(distances);
                free(next_nodes);
                free(visited);
                return DIJKSTRA_INVALID_INPUT;
            }

            incoming_counts[edge->destination]++;
        }
    }

    offsets[0] = 0;

    for (size_t i = 0; i < count; i++) {
        if (incoming_counts[i] > SIZE_MAX - offsets[i]) {
            free(incoming_counts);
            free(offsets);
            free(cursor);
            free(incoming);
            free(distances);
            free(next_nodes);
            free(visited);
            return DIJKSTRA_MEMORY_ERROR;
        }

        offsets[i + 1] = offsets[i] + incoming_counts[i];
        cursor[i] = offsets[i];
    }

    if (offsets[count] != edge_count) {
        free(incoming_counts);
        free(offsets);
        free(cursor);
        free(incoming);
        free(distances);
        free(next_nodes);
        free(visited);
        return DIJKSTRA_INVALID_INPUT;
    }

    for (size_t u = 0; u < count; u++) {
        const GraphNode *node = &graph->nodes[u];

        for (size_t j = 0; j < node->edge_count; j++) {
            const GraphEdge *edge = &node->edges[j];
            size_t v = edge->destination;
            size_t position = cursor[v]++;

            incoming[position].source = u;
            incoming[position].distance = edge->distance;
        }
    }

    free(incoming_counts);
    free(cursor);

    for (size_t i = 0; i < count; i++) {
        distances[i] = DBL_MAX;
        next_nodes[i] = SIZE_MAX;
    }

    MinHeap heap = {0};
    distances[destination] = 0.0;

    if (!heap_push(&heap, destination, 0.0)) {
        free(offsets);
        free(incoming);
        free(distances);
        free(next_nodes);
        free(visited);
        free(heap.entries);
        return DIJKSTRA_MEMORY_ERROR;
    }

    while (heap.size > 0) {
        HeapEntry current = heap_pop(&heap);
        size_t current_node = current.node;

        if (visited[current_node] ||
            current.distance > distances[current_node]) {
            continue;
        }

        visited[current_node] = 1;

        for (size_t i = offsets[current_node];
             i < offsets[current_node + 1];
             i++) {

            size_t predecessor = incoming[i].source;

            if (visited[predecessor]) {
                continue;
            }

            double new_distance =
                distances[current_node] + incoming[i].distance;

            if (!isfinite(new_distance)) {
                continue;
            }

            if (new_distance < distances[predecessor]) {
                distances[predecessor] = new_distance;
                next_nodes[predecessor] = current_node;

                if (!heap_push(
                        &heap,
                        predecessor,
                        new_distance)) {
                    free(offsets);
                    free(incoming);
                    free(distances);
                    free(next_nodes);
                    free(visited);
                    free(heap.entries);
                    return DIJKSTRA_MEMORY_ERROR;
                }
            }
        }
    }

    free(offsets);
    free(incoming);
    free(visited);
    free(heap.entries);

    result->distances = distances;
    result->next_nodes = next_nodes;
    result->node_count = count;
    result->destination = destination;

    return DIJKSTRA_SUCCESS;
}

DijkstraStatus reverse_dijkstra_get_route(
    const ReverseDijkstraResult *result,
    size_t source,
    size_t **route_nodes,
    size_t *route_count
)
{
    if (route_nodes == NULL || route_count == NULL) {
        return DIJKSTRA_INVALID_INPUT;
    }

    *route_nodes = NULL;
    *route_count = 0;

    if (result == NULL ||
        result->distances == NULL ||
        result->next_nodes == NULL ||
        result->node_count == 0 ||
        source >= result->node_count ||
        result->destination >= result->node_count) {
        return DIJKSTRA_INVALID_INPUT;
    }

    if (result->distances[source] == DBL_MAX ||
        !isfinite(result->distances[source])) {
        return DIJKSTRA_NO_PATH;
    }

    size_t length = 1;
    size_t current = source;

    while (current != result->destination) {
        size_t next = result->next_nodes[current];

        if (next >= result->node_count || length >= result->node_count) {
            return DIJKSTRA_NO_PATH;
        }

        current = next;
        length++;
    }

    if (length > SIZE_MAX / sizeof(size_t)) {
        return DIJKSTRA_MEMORY_ERROR;
    }

    size_t *path = malloc(length * sizeof(size_t));

    if (path == NULL) {
        return DIJKSTRA_MEMORY_ERROR;
    }

    current = source;

    for (size_t i = 0; i < length; i++) {
        path[i] = current;

        if (i + 1 < length) {
            current = result->next_nodes[current];
        }
    }

    *route_nodes = path;
    *route_count = length;

    return DIJKSTRA_SUCCESS;
}

void reverse_dijkstra_result_free(
    ReverseDijkstraResult *result
)
{
    if (result == NULL) {
        return;
    }

    free(result->distances);
    free(result->next_nodes);

    result->distances = NULL;
    result->next_nodes = NULL;
    result->node_count = 0;
    result->destination = SIZE_MAX;
}
void dijkstra_result_free(DijkstraResult *result)
{
    if (result == NULL) {
        return;
    }

    free(result->nodes);

    result->nodes = NULL;
    result->node_count = 0;
    result->total_distance = 0.0;
}
