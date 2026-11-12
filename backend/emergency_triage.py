

"""Structured emergency triage and resource requirement calculation.

Severity is determined only from structured answers.
Description text is never keyword-scored.
"""

from collections import defaultdict


EMERGENCY_TYPES = {
    "MEDICAL_EMERGENCY",
    "FIRE",
    "ROAD_TRAFFIC_ACCIDENT",
    "THREAT_TO_LIFE_VIOLENCE",
    "TRAPPED_PERSON_RESCUE",
}

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

RESOURCE_TYPES = {
    "AMBULANCE",
    "FIRE_VEHICLE",
    "POLICE_UNIT",
    "RESCUE_VEHICLE",
}


QUESTION_OPTIONS = {
    "MEDICAL_EMERGENCY": {
        "awake": {"YES", "UNRESPONSIVE", "UNSURE"},
        "breathing": {"NORMAL", "ABNORMAL", "UNSURE"},
        "severe_bleeding": {"YES", "NO", "UNSURE"},
        "life_threatening_symptoms": {"YES", "NO", "UNSURE"},
        "serious_injury": {"YES", "NO", "UNSURE"},
        "rapidly_worsening": {"YES", "NO", "UNSURE"},
    },
    "FIRE": {
        "observable_signs": {
            "SMOKE_ONLY", "FLAMES", "BOTH",
            "SUSPECTED_NO_VISIBLE_SIGNS", "UNSURE",
        },
        "fire_area": {
            "OBJECT_SMALL_AREA", "ONE_ROOM_VEHICLE",
            "MULTIPLE_AREAS", "OUTDOORS_VEGETATION", "UNSURE",
        },
        "spread": {
            "NONE", "BEYOND_START_AREA",
            "MULTIPLE_AREAS_STRUCTURES", "UNSURE",
        },
        "trapped_person": {"YES", "NO", "UNSURE"},
        "injuries_or_breathing_difficulties": {"YES", "NO", "UNSURE"},
        "life_threatening_condition": {"YES", "NO", "UNSURE"},
        "additional_hazard": {
            "GAS_EXPLOSION_HAZMAT", "NONE_OBSERVED", "UNSURE",
        },
    },
    "ROAD_TRAFFIC_ACCIDENT": {
        "incident_type": {
            "COLLISION", "ROLLOVER", "PEDESTRIAN_INVOLVED",
            "VEHICLE_OFF_ROAD", "OTHER", "UNSURE",
        },
        "injuries": {"YES", "NO", "UNSURE"},
        "trapped_person": {"YES", "NO", "UNSURE"},
        "life_threatening_signs": {"YES", "NO", "UNSURE"},
        "fire_smoke_fuel_hazard": {"YES", "NO", "UNSURE"},
        "ongoing_danger_or_obstruction": {"YES", "NO", "UNSURE"},
    },
    "THREAT_TO_LIFE_VIOLENCE": {
        "happening_now": {"YES", "NO_ENDED", "UNSURE"},
        "immediate_harm_or_prevented_escape": {"YES", "NO", "UNSURE"},
        "weapon_present_or_used": {"YES", "NO", "UNSURE"},
        "injuries_or_urgent_medical_help": {"YES", "NO", "UNSURE"},
        "threat_escalating": {"YES", "NO", "UNSURE"},
    },
    "TRAPPED_PERSON_RESCUE": {
        "trapping_context": {
            "BUILDING_ROOM", "VEHICLE", "DEBRIS_COLLAPSE",
            "FLOODWATER_TERRAIN", "OTHER", "UNSURE",
        },
        "can_escape_without_help": {"YES", "NO", "UNSURE"},
        "responsive_and_breathing_normally": {"YES", "NO", "UNSURE"},
        "immediate_environmental_danger": {
            "FIRE_SMOKE_FLOOD_COLLAPSE", "OTHER_DANGER",
            "NONE_OBSERVED", "UNSURE",
        },
        "active_fire_or_smoke": {"YES", "NO", "UNSURE"},
        "condition_or_trapping_worsening": {"YES", "NO", "UNSURE"},
        "number_trapped": {"ONE", "MORE_THAN_ONE", "UNKNOWN"},
    },
}


BASE_REQUIREMENTS = {
    "MEDICAL_EMERGENCY": {
        "LOW": {"AMBULANCE": 1},
        "MEDIUM": {"AMBULANCE": 1},
        "HIGH": {"AMBULANCE": 2},
        "CRITICAL": {"AMBULANCE": 3},
    },
    "FIRE": {
        "LOW": {"FIRE_VEHICLE": 1},
        "MEDIUM": {
            "FIRE_VEHICLE": 1, "AMBULANCE": 1, "POLICE_UNIT": 1,
        },
        "HIGH": {
            "FIRE_VEHICLE": 2, "AMBULANCE": 2, "POLICE_UNIT": 1,
        },
        "CRITICAL": {
            "FIRE_VEHICLE": 3, "AMBULANCE": 3, "POLICE_UNIT": 2,
        },
    },
    "ROAD_TRAFFIC_ACCIDENT": {
        "LOW": {"AMBULANCE": 1, "POLICE_UNIT": 1},
        "MEDIUM": {"AMBULANCE": 1, "POLICE_UNIT": 1},
        "HIGH": {"AMBULANCE": 2, "POLICE_UNIT": 1},
        "CRITICAL": {"AMBULANCE": 3, "POLICE_UNIT": 2},
    },
    "THREAT_TO_LIFE_VIOLENCE": {
        "LOW": {"POLICE_UNIT": 1},
        "MEDIUM": {"POLICE_UNIT": 1},
        "HIGH": {"POLICE_UNIT": 2, "AMBULANCE": 1},
        "CRITICAL": {"POLICE_UNIT": 2, "AMBULANCE": 2},
    },
    "TRAPPED_PERSON_RESCUE": {
        "LOW": {"RESCUE_VEHICLE": 1},
        "MEDIUM": {"RESCUE_VEHICLE": 1, "AMBULANCE": 1},
        "HIGH": {
            "RESCUE_VEHICLE": 2, "AMBULANCE": 2, "POLICE_UNIT": 1,
        },
        "CRITICAL": {
            "RESCUE_VEHICLE": 3, "AMBULANCE": 3, "POLICE_UNIT": 2,
        },
    },
}


def validate_assessment(emergency_type, answers):
    """Validate category and submitted structured answers."""
    if not isinstance(emergency_type, str) or emergency_type not in EMERGENCY_TYPES:
        raise ValueError("Unsupported emergency type.")

    if not isinstance(answers, dict):
        raise ValueError("Assessment answers must be a JSON object.")

    allowed = QUESTION_OPTIONS[emergency_type]

    if any(not isinstance(key, str) for key in answers):
        raise ValueError("Assessment question keys must be strings.")

    unknown_keys = set(answers) - set(allowed)
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported assessment question(s): {names}")

    normalized = {}

    for key, value in answers.items():
        if not isinstance(value, str):
            raise ValueError(f"Answer '{key}' must be a string.")

        value = value.strip().upper()

        if value not in allowed[key]:
            raise ValueError(f"Invalid answer for '{key}'.")

        normalized[key] = value

    return normalized


def _missing_or_unsure(answers, required_keys):
    return [
        key for key in required_keys
        if key not in answers
        or answers[key] in {"UNSURE", "UNKNOWN"}
    ]


def detect_assessment_conflicts(emergency_type, answers):
    """Return clear contradictions without modifying submitted answers."""
    conflicts = []

    if (
        emergency_type == "ROAD_TRAFFIC_ACCIDENT"
        and answers.get("life_threatening_signs") == "YES"
        and answers.get("injuries") == "NO"
    ):
        conflicts.append(
            "Life-threatening signs were reported while injuries were marked absent."
        )

    if (
        emergency_type == "TRAPPED_PERSON_RESCUE"
        and answers.get("can_escape_without_help") == "YES"
        and answers.get("responsive_and_breathing_normally") == "NO"
    ):
        conflicts.append(
            "The person was reported able to escape without help but also not responsive or not breathing normally."
        )

    return conflicts


def assess_severity(emergency_type, answers):
    """Return (severity, uncertain, reasons) using structured answers."""
    answers = validate_assessment(emergency_type, answers)
    a = answers

    critical = False
    high = False
    low_eligible = False
    reasons = []

    required = set(QUESTION_OPTIONS[emergency_type])
    incomplete = _missing_or_unsure(a, required)
    conflicts = detect_assessment_conflicts(emergency_type, a)

    if emergency_type == "MEDICAL_EMERGENCY":
        critical = (
            a.get("awake") == "UNRESPONSIVE"
            or a.get("breathing") == "ABNORMAL"
            or a.get("severe_bleeding") == "YES"
            or a.get("life_threatening_symptoms") == "YES"
        )
        high = (
            a.get("serious_injury") == "YES"
            or a.get("rapidly_worsening") == "YES"
        )
        low_eligible = (
            a.get("awake") == "YES"
            and a.get("breathing") == "NORMAL"
            and a.get("severe_bleeding") == "NO"
            and a.get("life_threatening_symptoms") == "NO"
            and a.get("serious_injury") == "NO"
            and a.get("rapidly_worsening") == "NO"
        )

    elif emergency_type == "FIRE":
        critical = (
            a.get("trapped_person") == "YES"
            or a.get("life_threatening_condition") == "YES"
        )
        high = (
            a.get("spread") in {
                "BEYOND_START_AREA", "MULTIPLE_AREAS_STRUCTURES"
            }
            or a.get("fire_area") == "MULTIPLE_AREAS"
            or a.get("injuries_or_breathing_difficulties") == "YES"
            or a.get("additional_hazard") == "GAS_EXPLOSION_HAZMAT"
        )
        low_eligible = (
            a.get("observable_signs") in {
                "SMOKE_ONLY", "FLAMES", "BOTH",
                "SUSPECTED_NO_VISIBLE_SIGNS",
            }
            and a.get("fire_area") in {
                "OBJECT_SMALL_AREA", "ONE_ROOM_VEHICLE"
            }
            and a.get("spread") == "NONE"
            and a.get("trapped_person") == "NO"
            and a.get("injuries_or_breathing_difficulties") == "NO"
            and a.get("life_threatening_condition") == "NO"
            and a.get("additional_hazard") == "NONE_OBSERVED"
        )

    elif emergency_type == "ROAD_TRAFFIC_ACCIDENT":
        critical = (
            a.get("life_threatening_signs") == "YES"
            or (
                a.get("trapped_person") == "YES"
                and a.get("fire_smoke_fuel_hazard") == "YES"
            )
        )
        high = (
            a.get("injuries") == "YES"
            or a.get("trapped_person") == "YES"
            or a.get("fire_smoke_fuel_hazard") == "YES"
            or a.get("ongoing_danger_or_obstruction") == "YES"
        )
        low_eligible = (
            a.get("incident_type") not in {None, "UNSURE"}
            and a.get("injuries") == "NO"
            and a.get("trapped_person") == "NO"
            and a.get("life_threatening_signs") == "NO"
            and a.get("fire_smoke_fuel_hazard") == "NO"
            and a.get("ongoing_danger_or_obstruction") == "NO"
        )

    elif emergency_type == "THREAT_TO_LIFE_VIOLENCE":
        critical = (
            a.get("happening_now") == "YES"
            and a.get("immediate_harm_or_prevented_escape") == "YES"
        )
        high = (
            a.get("immediate_harm_or_prevented_escape") == "YES"
            or a.get("weapon_present_or_used") == "YES"
            or a.get("threat_escalating") == "YES"
        )
        low_eligible = (
            a.get("happening_now") == "NO_ENDED"
            and a.get("immediate_harm_or_prevented_escape") == "NO"
            and a.get("weapon_present_or_used") == "NO"
            and a.get("injuries_or_urgent_medical_help") == "NO"
            and a.get("threat_escalating") == "NO"
        )

    elif emergency_type == "TRAPPED_PERSON_RESCUE":
        person_is_trapped = a.get("can_escape_without_help") == "NO"
        environmental_danger = a.get("immediate_environmental_danger") in {
            "FIRE_SMOKE_FLOOD_COLLAPSE", "OTHER_DANGER"
        }

        critical = person_is_trapped and (
            a.get("responsive_and_breathing_normally") == "NO"
            or environmental_danger
        )
        high = (
            person_is_trapped
            or a.get("number_trapped") == "MORE_THAN_ONE"
            or a.get("condition_or_trapping_worsening") == "YES"
        )
        low_eligible = (
            a.get("can_escape_without_help") == "YES"
            and a.get("immediate_environmental_danger") == "NONE_OBSERVED"
            and a.get("condition_or_trapping_worsening") == "NO"
        )

    # Confirmed Critical conditions take precedence over uncertainty.
    if critical:
        severity = "CRITICAL"
        reasons.append(
            "A structured answer confirmed a Critical safety trigger."
        )
    elif high:
        severity = "HIGH"
        reasons.append(
            "One or more structured answers confirmed a High-risk condition."
        )
    elif incomplete or conflicts:
        severity = "HIGH"
        reasons.append(
            "Missing, uncertain, or contradictory safety information prevents a safe lower-severity assessment."
        )
    elif low_eligible:
        severity = "LOW"
        reasons.append(
            "All applicable low-severity conditions were satisfied."
        )
    else:
        severity = "MEDIUM"
        reasons.append(
            "A response is required, with no confirmed High or Critical trigger."
        )

    uncertain = bool((incomplete or conflicts) and not critical)

    if incomplete:
        reasons.append(
            "One or more required safety answers are missing or unsure."
        )

    for conflict in conflicts:
        reasons.append(f"Assessment discrepancy: {conflict}")

    return severity, uncertain, reasons


def calculate_requirements(emergency_type, severity, answers):
    """Calculate merged resource quantities, including conditional additions."""
    if not isinstance(emergency_type, str) or emergency_type not in EMERGENCY_TYPES:
        raise ValueError("Unsupported emergency type.")

    if not isinstance(severity, str) or severity not in SEVERITIES:
        raise ValueError("Unsupported severity.")

    answers = validate_assessment(emergency_type, answers)
    quantities = defaultdict(
        int, BASE_REQUIREMENTS[emergency_type][severity]
    )

    if emergency_type == "ROAD_TRAFFIC_ACCIDENT":
        if answers.get("trapped_person") == "YES":
            quantities["RESCUE_VEHICLE"] += 1

        if answers.get("fire_smoke_fuel_hazard") == "YES":
            quantities["FIRE_VEHICLE"] += 1

    elif emergency_type == "TRAPPED_PERSON_RESCUE":
        if answers.get("active_fire_or_smoke") == "YES":
            quantities["FIRE_VEHICLE"] += 1

    return {
        resource_type: quantity
        for resource_type, quantity in sorted(quantities.items())
        if quantity > 0
    }


def evaluate_emergency(emergency_type, answers):
    """Validate answers and return the complete triage result."""
    normalized = validate_assessment(emergency_type, answers)
    severity, uncertain, reasons = assess_severity(
        emergency_type, normalized
    )
    requirements = calculate_requirements(
        emergency_type, severity, normalized
    )

    return {
        "severity": severity,
        "assessment_uncertain": uncertain,
        "assessment_reasons": reasons,
        "assessment_answers": normalized,
        "severity_rule_version": "triage-v1",
        "requirements": requirements,
    }
