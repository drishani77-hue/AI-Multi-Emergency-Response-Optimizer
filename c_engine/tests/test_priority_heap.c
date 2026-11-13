#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/priority_heap.h"

static ResqtechPriorityEntry make_entry(
    const char *unit_id,
    const char *emergency_id,
    ResqtechSeverity severity,
    const char *reported_at)
{
    ResqtechPriorityEntry entry = {
        .requirement_unit_id = (char *)unit_id,
        .emergency_id = (char *)emergency_id,
        .resource_type = RESQTECH_RESOURCE_FIRE,
        .severity = severity,
        .reported_at = (char *)reported_at};

    return entry;
}

static int expect_pop(
    void *heap,
    const char *expected_unit_id)
{
    ResqtechPriorityEntry result = {0};

    int status = resqtech_heap_pop(heap, &result);

    int passed = (status == RESQTECH_OK &&
                  result.requirement_unit_id != NULL &&
                  strcmp(result.requirement_unit_id, expected_unit_id) == 0);

    resqtech_heap_entry_free(&result);
    return passed;
}

static int test_severity_order(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry entries[] = {
        make_entry("unit_low", "emergency_1",
                   RESQTECH_SEVERITY_LOW, "2026-01-01T10:00:00Z"),
        make_entry("unit_critical", "emergency_2",
                   RESQTECH_SEVERITY_CRITICAL, "2026-01-01T10:00:00Z"),
        make_entry("unit_medium", "emergency_3",
                   RESQTECH_SEVERITY_MEDIUM, "2026-01-01T10:00:00Z"),
        make_entry("unit_high", "emergency_4",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z")};

    int passed = 1;

    for (size_t i = 0; i < 4; i++)
    {
        if (resqtech_heap_push(heap, &entries[i]) != RESQTECH_OK)
        {
            passed = 0;
            break;
        }
    }

    const char *expected[] = {
        "unit_critical", "unit_high",
        "unit_medium", "unit_low"};

    for (size_t i = 0; passed && i < 4; i++)
    {
        passed = expect_pop(heap, expected[i]);
    }

    printf("Severity priority ordering: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_timestamp_order(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry entries[] = {
        make_entry("unit_late", "emergency_1",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T10:30:00Z"),
        make_entry("unit_early", "emergency_2",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T09:30:00Z")};

    int passed =
        resqtech_heap_push(heap, &entries[0]) == RESQTECH_OK &&
        resqtech_heap_push(heap, &entries[1]) == RESQTECH_OK &&
        expect_pop(heap, "unit_early") &&
        expect_pop(heap, "unit_late");

    printf("Earlier timestamp priority: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_unit_id_tie_break(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry entries[] = {
        make_entry("unit_C", "emergency_1",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z"),
        make_entry("unit_A", "emergency_2",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z"),
        make_entry("unit_B", "emergency_3",
                   RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z")};

    int passed = 1;

    for (size_t i = 0; i < 3; i++)
    {
        if (resqtech_heap_push(heap, &entries[i]) != RESQTECH_OK)
        {
            passed = 0;
            break;
        }
    }

    const char *expected[] = {
        "unit_A", "unit_B", "unit_C"};

    for (size_t i = 0; passed && i < 3; i++)
    {
        passed = expect_pop(heap, expected[i]);
    }

    printf("Requirement unit ID tie-break: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_empty_heap(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry result = {0};

    int status = resqtech_heap_pop(heap, &result);

    int passed = (status == RESQTECH_HEAP_EMPTY &&
                  result.requirement_unit_id == NULL &&
                  result.emergency_id == NULL &&
                  result.reported_at == NULL &&
                  resqtech_heap_size(heap) == 0);

    printf("Empty heap handling: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_entry_free(&result);
    resqtech_heap_destroy(heap);
    return passed;
}

static int test_invalid_inputs(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry valid = make_entry(
        "unit_1", "emergency_1",
        RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z");

    ResqtechPriorityEntry invalid_severity = valid;
    invalid_severity.severity = (ResqtechSeverity)99;

    ResqtechPriorityEntry invalid_resource = valid;
    invalid_resource.resource_type = RESQTECH_RESOURCE_POLICE;

    ResqtechPriorityEntry invalid_timestamp = valid;
    invalid_timestamp.reported_at = "2026-02-29T10:00:00Z";

    ResqtechPriorityEntry invalid_format = valid;
    invalid_format.reported_at = "2026/01/01 10:00:00";

    int passed =
        resqtech_heap_push(heap, &invalid_severity) ==
            RESQTECH_INVALID_ARGUMENT &&
        resqtech_heap_push(heap, &invalid_resource) ==
            RESQTECH_INVALID_ARGUMENT &&
        resqtech_heap_push(heap, &invalid_timestamp) ==
            RESQTECH_INVALID_ARGUMENT &&
        resqtech_heap_push(heap, &invalid_format) ==
            RESQTECH_INVALID_ARGUMENT &&
        resqtech_heap_size(heap) == 0;

    printf("Invalid input rejection: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_leap_year_validation(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry valid_leap = make_entry(
        "unit_leap", "emergency_1",
        RESQTECH_SEVERITY_HIGH, "2024-02-29T10:00:00Z");

    ResqtechPriorityEntry invalid_century = make_entry(
        "unit_century", "emergency_2",
        RESQTECH_SEVERITY_HIGH, "2100-02-29T10:00:00Z");

    int passed =
        resqtech_heap_push(heap, &valid_leap) == RESQTECH_OK &&
        resqtech_heap_push(heap, &invalid_century) ==
            RESQTECH_INVALID_ARGUMENT;

    printf("Leap-year calendar validation: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_clear(heap);
    resqtech_heap_destroy(heap);
    return passed;
}

static int test_dynamic_growth(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    int passed = 1;

    for (int i = 0; i < 100; i++)
    {
        char unit_id[32];
        char emergency_id[32];

        snprintf(unit_id, sizeof(unit_id), "unit_%03d", i);
        snprintf(emergency_id, sizeof(emergency_id),
                 "emergency_%03d", i);

        ResqtechPriorityEntry entry = make_entry(
            unit_id,
            emergency_id,
            RESQTECH_SEVERITY_MEDIUM,
            "2026-01-01T10:00:00Z");

        if (resqtech_heap_push(heap, &entry) != RESQTECH_OK)
        {
            passed = 0;
            break;
        }
    }

    if (passed && resqtech_heap_size(heap) != 100)
    {
        passed = 0;
    }

    for (int i = 0; passed && i < 100; i++)
    {
        char expected[32];
        snprintf(expected, sizeof(expected), "unit_%03d", i);

        if (!expect_pop(heap, expected))
        {
            passed = 0;
        }
    }

    printf("Dynamic growth and ordering (100 entries): %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_clear_heap(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    ResqtechPriorityEntry entry = make_entry(
        "unit_1", "emergency_1",
        RESQTECH_SEVERITY_HIGH, "2026-01-01T10:00:00Z");

    int passed =
        resqtech_heap_push(heap, &entry) == RESQTECH_OK;

    resqtech_heap_clear(heap);

    passed = passed &&
             resqtech_heap_size(heap) == 0;

    passed = passed &&
             resqtech_heap_push(heap, &entry) == RESQTECH_OK;

    passed = passed &&
             expect_pop(heap, "unit_1");

    printf("Clear and reuse heap: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

static int test_deep_copy_ownership(void)
{
    void *heap = resqtech_heap_create(RESQTECH_RESOURCE_FIRE);

    if (heap == NULL)
    {
        return 0;
    }

    char unit_id[] = "unit_original";
    char emergency_id[] = "emergency_original";
    char reported_at[] = "2026-01-01T10:00:00Z";

    ResqtechPriorityEntry entry = make_entry(
        unit_id,
        emergency_id,
        RESQTECH_SEVERITY_HIGH,
        reported_at);

    int passed =
        resqtech_heap_push(heap, &entry) == RESQTECH_OK;

    if (passed)
    {
        strcpy(unit_id, "unit_changed");
        strcpy(emergency_id, "emergency_changed");
        strcpy(reported_at, "2026-01-01T11:00:00Z");
    }

    ResqtechPriorityEntry result = {0};

    if (passed)
    {
        passed =
            resqtech_heap_pop(heap, &result) == RESQTECH_OK;
    }

    if (passed)
    {
        passed =
            strcmp(result.requirement_unit_id, "unit_original") == 0 &&
            strcmp(result.emergency_id, "emergency_original") == 0 &&
            strcmp(result.reported_at, "2026-01-01T10:00:00Z") == 0;
    }

    resqtech_heap_entry_free(&result);

    printf("Deep-copy ownership: %s\n",
           passed ? "PASSED" : "FAILED");

    resqtech_heap_destroy(heap);
    return passed;
}

int main(void)
{
    printf("Testing ResQTech priority heap...\n\n");

    int passed = 1;

    passed &= test_severity_order();
    passed &= test_timestamp_order();
    passed &= test_unit_id_tie_break();
    passed &= test_empty_heap();
    passed &= test_invalid_inputs();
    passed &= test_leap_year_validation();
    passed &= test_deep_copy_ownership();
    passed &= test_dynamic_growth();
    passed &= test_clear_heap();

    if (passed)
    {
        printf("\nRESULT: ALL PRIORITY HEAP TESTS PASSED\n");
        return EXIT_SUCCESS;
    }

    printf("\nRESULT: PRIORITY HEAP TESTS FAILED\n");
    return EXIT_FAILURE;
}
