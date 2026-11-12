
import pytest

from backend.emergency_triage import (
    QUESTION_OPTIONS,
    assess_severity,
    calculate_requirements,
    detect_assessment_conflicts,
    evaluate_emergency,
    validate_assessment,
)


def complete_answers(emergency_type, overrides=None):
    """Build a complete, conservative default assessment."""
    defaults = {
        "MEDICAL_EMERGENCY": {
            "awake": "YES",
            "breathing": "NORMAL",
            "severe_bleeding": "NO",
            "life_threatening_symptoms": "NO",
            "serious_injury": "NO",
            "rapidly_worsening": "NO",
        },
        "FIRE": {
            "observable_signs": "FLAMES",
            "fire_area": "OBJECT_SMALL_AREA",
            "spread": "NONE",
            "trapped_person": "NO",
            "injuries_or_breathing_difficulties": "NO",
            "life_threatening_condition": "NO",
            "additional_hazard": "NONE_OBSERVED",
        },
        "ROAD_TRAFFIC_ACCIDENT": {
            "incident_type": "COLLISION",
            "injuries": "NO",
            "trapped_person": "NO",
            "life_threatening_signs": "NO",
            "fire_smoke_fuel_hazard": "NO",
            "ongoing_danger_or_obstruction": "NO",
        },
        "THREAT_TO_LIFE_VIOLENCE": {
            "happening_now": "NO_ENDED",
            "immediate_harm_or_prevented_escape": "NO",
            "weapon_present_or_used": "NO",
            "injuries_or_urgent_medical_help": "NO",
            "threat_escalating": "NO",
        },
        "TRAPPED_PERSON_RESCUE": {
            "trapping_context": "BUILDING_ROOM",
            "can_escape_without_help": "YES",
            "responsive_and_breathing_normally": "YES",
            "immediate_environmental_danger": "NONE_OBSERVED",
            "active_fire_or_smoke": "NO",
            "condition_or_trapping_worsening": "NO",
            "number_trapped": "ONE",
        },
    }

    answers = defaults[emergency_type].copy()
    if overrides:
        answers.update(overrides)
    return answers


@pytest.mark.parametrize(
    "emergency_type",
    list(QUESTION_OPTIONS),
)
def test_complete_safe_assessment_is_low(emergency_type):
    severity, uncertain, _ = assess_severity(
        emergency_type, complete_answers(emergency_type)
    )
    assert severity == "LOW"
    assert uncertain is False


@pytest.mark.parametrize(
    "emergency_type,overrides,expected",
    [
        (
            "MEDICAL_EMERGENCY",
            {"awake": "UNRESPONSIVE"},
            "CRITICAL",
        ),
        (
            "MEDICAL_EMERGENCY",
            {"serious_injury": "YES"},
            "HIGH",
        ),
        (
            "FIRE",
            {"trapped_person": "YES"},
            "CRITICAL",
        ),
        (
            "FIRE",
            {"life_threatening_condition": "YES"},
            "CRITICAL",
        ),
        (
            "FIRE",
            {"injuries_or_breathing_difficulties": "YES"},
            "HIGH",
        ),
        (
            "FIRE",
            {"spread": "BEYOND_START_AREA"},
            "HIGH",
        ),
        (
            "ROAD_TRAFFIC_ACCIDENT",
            {"life_threatening_signs": "YES"},
            "CRITICAL",
        ),
        (
            "ROAD_TRAFFIC_ACCIDENT",
            {"trapped_person": "YES"},
            "HIGH",
        ),
        (
            "THREAT_TO_LIFE_VIOLENCE",
            {
                "happening_now": "YES",
                "immediate_harm_or_prevented_escape": "YES",
            },
            "CRITICAL",
        ),
        (
            "THREAT_TO_LIFE_VIOLENCE",
            {"weapon_present_or_used": "YES"},
            "HIGH",
        ),
        (
            "TRAPPED_PERSON_RESCUE",
            {
                "can_escape_without_help": "NO",
                "responsive_and_breathing_normally": "NO",
            },
            "CRITICAL",
        ),
        (
            "TRAPPED_PERSON_RESCUE",
            {"can_escape_without_help": "NO"},
            "HIGH",
        ),
    ],
)
def test_severity_triggers(emergency_type, overrides, expected):
    severity, _, _ = assess_severity(
        emergency_type,
        complete_answers(emergency_type, overrides),
    )
    assert severity == expected


@pytest.mark.parametrize(
    "emergency_type",
    list(QUESTION_OPTIONS),
)
def test_missing_answers_produce_provisional_high(emergency_type):
    severity, uncertain, reasons = assess_severity(
        emergency_type, {}
    )

    assert severity == "HIGH"
    assert uncertain is True
    assert any("missing" in reason.lower() for reason in reasons)


def test_confirmed_critical_takes_precedence_over_missing_answers():
    severity, uncertain, _ = assess_severity(
        "MEDICAL_EMERGENCY",
        {"awake": "UNRESPONSIVE"},
    )

    assert severity == "CRITICAL"
    assert uncertain is False


def test_fire_ordinary_injury_is_not_critical():
    answers = complete_answers(
        "FIRE",
        {"injuries_or_breathing_difficulties": "YES"},
    )

    severity, _, _ = assess_severity("FIRE", answers)

    assert severity == "HIGH"
    assert severity != "CRITICAL"


def test_fire_life_threatening_condition_is_critical():
    answers = complete_answers(
        "FIRE",
        {"life_threatening_condition": "YES"},
    )

    severity, _, _ = assess_severity("FIRE", answers)

    assert severity == "CRITICAL"


def test_trapped_rescue_flood_does_not_automatically_add_fire_vehicle():
    answers = complete_answers(
        "TRAPPED_PERSON_RESCUE",
        {
            "can_escape_without_help": "NO",
            "immediate_environmental_danger": "FIRE_SMOKE_FLOOD_COLLAPSE",
            "active_fire_or_smoke": "NO",
        },
    )

    requirements = calculate_requirements(
        "TRAPPED_PERSON_RESCUE", "HIGH", answers
    )

    assert "FIRE_VEHICLE" not in requirements


def test_trapped_rescue_active_fire_adds_one_fire_vehicle():
    answers = complete_answers(
        "TRAPPED_PERSON_RESCUE",
        {
            "can_escape_without_help": "NO",
            "active_fire_or_smoke": "YES",
        },
    )

    requirements = calculate_requirements(
        "TRAPPED_PERSON_RESCUE", "HIGH", answers
    )

    assert requirements["FIRE_VEHICLE"] == 1


def test_rta_conditional_resources_are_added_once():
    answers = complete_answers(
        "ROAD_TRAFFIC_ACCIDENT",
        {
            "trapped_person": "YES",
            "fire_smoke_fuel_hazard": "YES",
        },
    )

    requirements = calculate_requirements(
        "ROAD_TRAFFIC_ACCIDENT", "MEDIUM", answers
    )

    assert requirements == {
        "AMBULANCE": 1,
        "FIRE_VEHICLE": 1,
        "POLICE_UNIT": 1,
        "RESCUE_VEHICLE": 1,
    }


def test_resource_matrix_medical():
    answers = complete_answers("MEDICAL_EMERGENCY")

    assert calculate_requirements(
        "MEDICAL_EMERGENCY", "LOW", answers
    ) == {"AMBULANCE": 1}

    assert calculate_requirements(
        "MEDICAL_EMERGENCY", "HIGH", answers
    ) == {"AMBULANCE": 2}

    assert calculate_requirements(
        "MEDICAL_EMERGENCY", "CRITICAL", answers
    ) == {"AMBULANCE": 3}


def test_resource_matrix_fire():
    answers = complete_answers("FIRE")

    assert calculate_requirements(
        "FIRE", "LOW", answers
    ) == {"FIRE_VEHICLE": 1}

    assert calculate_requirements(
        "FIRE", "MEDIUM", answers
    ) == {
        "AMBULANCE": 1,
        "FIRE_VEHICLE": 1,
        "POLICE_UNIT": 1,
    }

    assert calculate_requirements(
        "FIRE", "HIGH", answers
    ) == {
        "AMBULANCE": 2,
        "FIRE_VEHICLE": 2,
        "POLICE_UNIT": 1,
    }

    assert calculate_requirements(
        "FIRE", "CRITICAL", answers
    ) == {
        "AMBULANCE": 3,
        "FIRE_VEHICLE": 3,
        "POLICE_UNIT": 2,
    }


def test_resource_matrix_rta():
    answers = complete_answers("ROAD_TRAFFIC_ACCIDENT")

    assert calculate_requirements(
        "ROAD_TRAFFIC_ACCIDENT", "CRITICAL", answers
    ) == {
        "AMBULANCE": 3,
        "POLICE_UNIT": 2,
    }


def test_resource_matrix_threat():
    answers = complete_answers("THREAT_TO_LIFE_VIOLENCE")

    assert calculate_requirements(
        "THREAT_TO_LIFE_VIOLENCE", "HIGH", answers
    ) == {
        "AMBULANCE": 1,
        "POLICE_UNIT": 2,
    }

    assert calculate_requirements(
        "THREAT_TO_LIFE_VIOLENCE", "CRITICAL", answers
    ) == {
        "AMBULANCE": 2,
        "POLICE_UNIT": 2,
    }


def test_resource_matrix_trapped_rescue():
    answers = complete_answers("TRAPPED_PERSON_RESCUE")

    assert calculate_requirements(
        "TRAPPED_PERSON_RESCUE", "CRITICAL", answers
    ) == {
        "AMBULANCE": 3,
        "POLICE_UNIT": 2,
        "RESCUE_VEHICLE": 3,
    }


def test_rta_conflicting_answers_are_preserved_and_flagged():
    answers = complete_answers(
        "ROAD_TRAFFIC_ACCIDENT",
        {
            "injuries": "NO",
            "life_threatening_signs": "YES",
        },
    )

    conflicts = detect_assessment_conflicts(
        "ROAD_TRAFFIC_ACCIDENT", answers
    )

    assert len(conflicts) == 1

    result = evaluate_emergency("ROAD_TRAFFIC_ACCIDENT", answers)

    assert result["assessment_answers"]["injuries"] == "NO"
    assert result["assessment_answers"]["life_threatening_signs"] == "YES"
    assert result["severity"] == "CRITICAL"


def test_invalid_question_is_rejected():
    with pytest.raises(ValueError):
        validate_assessment(
            "MEDICAL_EMERGENCY",
            {"unknown_question": "YES"},
        )


def test_invalid_answer_is_rejected():
    with pytest.raises(ValueError):
        validate_assessment(
            "MEDICAL_EMERGENCY",
            {"awake": "MAYBE"},
        )


def test_answers_are_normalized():
    answers = validate_assessment(
        "MEDICAL_EMERGENCY",
        {"awake": " yes "},
    )

    assert answers["awake"] == "YES"


def test_evaluate_emergency_returns_complete_result():
    result = evaluate_emergency(
        "MEDICAL_EMERGENCY",
        complete_answers("MEDICAL_EMERGENCY"),
    )

    assert result["severity"] == "LOW"
    assert result["assessment_uncertain"] is False
    assert result["severity_rule_version"] == "triage-v1"
    assert result["requirements"] == {"AMBULANCE": 1}
    assert isinstance(result["assessment_reasons"], list)
