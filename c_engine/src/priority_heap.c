#include "priority_heap.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define INITIAL_CAPACITY 16

typedef struct {
    ResqtechResourceType resource_type;
    ResqtechPriorityEntry *entries;
    size_t size;
    size_t capacity;
} ResqtechPriorityHeap;

static char *copy_string(const char *source)
{
    if (source == NULL) {
        return NULL;
    }

    size_t length = strlen(source);

    if (length == SIZE_MAX) {
        return NULL;
    }

    char *copy = malloc(length + 1);

    if (copy != NULL) {
        memcpy(copy, source, length + 1);
    }

    return copy;
}

static int is_leap_year(int year)
{
    return year % 400 == 0 ||
           (year % 4 == 0 && year % 100 != 0);
}

static int valid_timestamp(const char *value)
{
    if (value == NULL || strlen(value) != 20) {
        return 0;
    }

    if (value[4] != '-' ||
        value[7] != '-' ||
        value[10] != 'T' ||
        value[13] != ':' ||
        value[16] != ':' ||
        value[19] != 'Z') {
        return 0;
    }

    const int digit_positions[] = {
        0, 1, 2, 3, 5, 6, 8, 9,
        11, 12, 14, 15, 17, 18
    };

    for (size_t i = 0;
         i < sizeof(digit_positions) / sizeof(digit_positions[0]);
         i++) {
        char character = value[digit_positions[i]];

        if (character < '0' || character > '9') {
            return 0;
        }
    }

    int year =
        (value[0] - '0') * 1000 +
        (value[1] - '0') * 100 +
        (value[2] - '0') * 10 +
        (value[3] - '0');

    int month =
        (value[5] - '0') * 10 +
        (value[6] - '0');

    int day =
        (value[8] - '0') * 10 +
        (value[9] - '0');

    int hour =
        (value[11] - '0') * 10 +
        (value[12] - '0');

    int minute =
        (value[14] - '0') * 10 +
        (value[15] - '0');

    int second =
        (value[17] - '0') * 10 +
        (value[18] - '0');

    if (year < 1 || month < 1 || month > 12 ||
        hour > 23 || minute > 59 || second > 59) {
        return 0;
    }

    static const int days_per_month[] = {
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    };

    int maximum_day = days_per_month[month - 1];

    if (month == 2 && is_leap_year(year)) {
        maximum_day = 29;
    }

    return day >= 1 && day <= maximum_day;
}

static int valid_resource_type(ResqtechResourceType type)
{
    return type == RESQTECH_RESOURCE_FIRE ||
           type == RESQTECH_RESOURCE_AMBULANCE ||
           type == RESQTECH_RESOURCE_POLICE ||
           type == RESQTECH_RESOURCE_RESCUE;
}

static int valid_severity(ResqtechSeverity severity)
{
    return severity >= RESQTECH_SEVERITY_LOW &&
           severity <= RESQTECH_SEVERITY_CRITICAL;
}

static void release_entry(ResqtechPriorityEntry *entry)
{
    if (entry == NULL) {
        return;
    }

    free(entry->requirement_unit_id);
    free(entry->emergency_id);
    free(entry->reported_at);

    memset(entry, 0, sizeof(*entry));
}

static int copy_entry(
    const ResqtechPriorityEntry *source,
    ResqtechPriorityEntry *destination
)
{
    memset(destination, 0, sizeof(*destination));

    destination->requirement_unit_id =
        copy_string(source->requirement_unit_id);

    destination->emergency_id =
        copy_string(source->emergency_id);

    destination->reported_at =
        copy_string(source->reported_at);

    if (destination->requirement_unit_id == NULL ||
        destination->emergency_id == NULL ||
        destination->reported_at == NULL) {
        release_entry(destination);
        return RESQTECH_MEMORY_ERROR;
    }

    destination->resource_type = source->resource_type;
    destination->severity = source->severity;

    return RESQTECH_OK;
}

/*
 * Returns a negative value when left has higher priority,
 * a positive value when right has higher priority,
 * and zero when both entries have equal priority.
 */
static int compare_entries(
    const ResqtechPriorityEntry *left,
    const ResqtechPriorityEntry *right
)
{
    if (left->severity != right->severity) {
        return left->severity > right->severity ? -1 : 1;
    }

    int time_comparison = strcmp(
        left->reported_at,
        right->reported_at
    );

    if (time_comparison != 0) {
        return time_comparison;
    }

    return strcmp(
        left->requirement_unit_id,
        right->requirement_unit_id
    );
}

static void swap_entries(
    ResqtechPriorityEntry *left,
    ResqtechPriorityEntry *right
)
{
    ResqtechPriorityEntry temporary = *left;
    *left = *right;
    *right = temporary;
}

static int grow_heap(ResqtechPriorityHeap *heap)
{
    if (heap->capacity > SIZE_MAX / 2) {
        return RESQTECH_MEMORY_ERROR;
    }

    size_t new_capacity = heap->capacity * 2;

    if (new_capacity > SIZE_MAX / sizeof(ResqtechPriorityEntry)) {
        return RESQTECH_MEMORY_ERROR;
    }

    ResqtechPriorityEntry *new_entries = realloc(
        heap->entries,
        new_capacity * sizeof(ResqtechPriorityEntry)
    );

    if (new_entries == NULL) {
        return RESQTECH_MEMORY_ERROR;
    }

    heap->entries = new_entries;
    heap->capacity = new_capacity;

    return RESQTECH_OK;
}

static void sift_up(ResqtechPriorityHeap *heap, size_t index)
{
    while (index > 0) {
        size_t parent = (index - 1) / 2;

        if (compare_entries(
            &heap->entries[index],
            &heap->entries[parent]
        ) >= 0) {
            break;
        }

        swap_entries(
            &heap->entries[index],
            &heap->entries[parent]
        );

        index = parent;
    }
}

static void sift_down(ResqtechPriorityHeap *heap, size_t index)
{
    while (index < heap->size / 2) {
        size_t left = index * 2 + 1;
        size_t right = left + 1;
        size_t highest = left;

        if (right < heap->size &&
            compare_entries(
                &heap->entries[right],
                &heap->entries[left]
            ) < 0) {
            highest = right;
        }

        if (compare_entries(
            &heap->entries[highest],
            &heap->entries[index]
        ) >= 0) {
            break;
        }

        swap_entries(
            &heap->entries[index],
            &heap->entries[highest]
        );

        index = highest;
    }
}

void * RESQTECH_CALL resqtech_heap_create(
    ResqtechResourceType resource_type
)
{
    if (!valid_resource_type(resource_type)) {
        return NULL;
    }

    ResqtechPriorityHeap *heap = calloc(1, sizeof(*heap));

    if (heap == NULL) {
        return NULL;
    }

    heap->entries = calloc(
        INITIAL_CAPACITY,
        sizeof(ResqtechPriorityEntry)
    );

    if (heap->entries == NULL) {
        free(heap);
        return NULL;
    }

    heap->resource_type = resource_type;
    heap->capacity = INITIAL_CAPACITY;

    return heap;
}

int RESQTECH_CALL resqtech_heap_push(
    void *handle,
    const ResqtechPriorityEntry *entry
)
{
    if (handle == NULL || entry == NULL ||
        entry->requirement_unit_id == NULL ||
        entry->emergency_id == NULL ||
        entry->reported_at == NULL ||
        entry->requirement_unit_id[0] == '\0' ||
        entry->emergency_id[0] == '\0') {
        return RESQTECH_INVALID_ARGUMENT;
    }

    ResqtechPriorityHeap *heap = handle;

    if (entry->resource_type != heap->resource_type ||
        !valid_severity(entry->severity) ||
        !valid_timestamp(entry->reported_at)) {
        return RESQTECH_INVALID_ARGUMENT;
    }

    if (heap->size == heap->capacity) {
        int status = grow_heap(heap);

        if (status != RESQTECH_OK) {
            return status;
        }
    }

    ResqtechPriorityEntry copied_entry = {0};

    int status = copy_entry(entry, &copied_entry);

    if (status != RESQTECH_OK) {
        return status;
    }

    heap->entries[heap->size] = copied_entry;

    sift_up(heap, heap->size);

    heap->size++;

    return RESQTECH_OK;
}

int RESQTECH_CALL resqtech_heap_pop(
    void *handle,
    ResqtechPriorityEntry *entry
)
{
    if (handle == NULL || entry == NULL) {
        return RESQTECH_INVALID_ARGUMENT;
    }

    memset(entry, 0, sizeof(*entry));

    ResqtechPriorityHeap *heap = handle;

    if (heap->size == 0) {
        return RESQTECH_HEAP_EMPTY;
    }

    *entry = heap->entries[0];

    heap->size--;

    if (heap->size > 0) {
        heap->entries[0] = heap->entries[heap->size];

        memset(
            &heap->entries[heap->size],
            0,
            sizeof(ResqtechPriorityEntry)
        );

        sift_down(heap, 0);
    } else {
        memset(
            &heap->entries[0],
            0,
            sizeof(ResqtechPriorityEntry)
        );
    }

    return RESQTECH_OK;
}

void RESQTECH_CALL resqtech_heap_entry_free(
    ResqtechPriorityEntry *entry
)
{
    release_entry(entry);
}

size_t RESQTECH_CALL resqtech_heap_size(void *handle)
{
    if (handle == NULL) {
        return 0;
    }

    const ResqtechPriorityHeap *heap = handle;
    return heap->size;
}

void RESQTECH_CALL resqtech_heap_clear(void *handle)
{
    if (handle == NULL) {
        return;
    }

    ResqtechPriorityHeap *heap = handle;

    for (size_t i = 0; i < heap->size; i++) {
        release_entry(&heap->entries[i]);
    }

    heap->size = 0;
}

void RESQTECH_CALL resqtech_heap_destroy(void *handle)
{
    if (handle == NULL) {
        return;
    }

    ResqtechPriorityHeap *heap = handle;

    resqtech_heap_clear(heap);
    free(heap->entries);
    free(heap);
}
