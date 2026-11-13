#ifndef RESQTECH_PRIORITY_HEAP_H
#define RESQTECH_PRIORITY_HEAP_H

#include "bridge.h"

typedef enum {
    RESQTECH_RESOURCE_FIRE = 1,
    RESQTECH_RESOURCE_AMBULANCE = 2,
    RESQTECH_RESOURCE_POLICE = 3,
    RESQTECH_RESOURCE_RESCUE = 4
} ResqtechResourceType;

typedef enum {
    RESQTECH_SEVERITY_LOW = 1,
    RESQTECH_SEVERITY_MEDIUM = 2,
    RESQTECH_SEVERITY_HIGH = 3,
    RESQTECH_SEVERITY_CRITICAL = 4
} ResqtechSeverity;

enum {
    RESQTECH_HEAP_EMPTY = 7
};

/*
 * Strings returned by resqtech_heap_pop are heap-allocated.
 * Release them with resqtech_heap_entry_free.
 */
typedef struct {
    char *requirement_unit_id;
    char *emergency_id;
    ResqtechResourceType resource_type;
    ResqtechSeverity severity;
    char *reported_at;
} ResqtechPriorityEntry;

RESQTECH_API void * RESQTECH_CALL resqtech_heap_create(
    ResqtechResourceType resource_type
);

RESQTECH_API int RESQTECH_CALL resqtech_heap_push(
    void *heap,
    const ResqtechPriorityEntry *entry
);

RESQTECH_API int RESQTECH_CALL resqtech_heap_pop(
    void *heap,
    ResqtechPriorityEntry *entry
);

RESQTECH_API void RESQTECH_CALL resqtech_heap_entry_free(
    ResqtechPriorityEntry *entry
);

RESQTECH_API size_t RESQTECH_CALL resqtech_heap_size(
    void *heap
);

RESQTECH_API void RESQTECH_CALL resqtech_heap_clear(
    void *heap
);

RESQTECH_API void RESQTECH_CALL resqtech_heap_destroy(
    void *heap
);

#endif
