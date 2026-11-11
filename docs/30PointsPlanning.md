# AI-Assisted Multi-Emergency Response & Resource Optimizer

## Final Master Planning Document — v12 Session-Management Revision

**Project type:** 3-person Data Structures using C PBL project
**Team:** ResQTech
**Demonstration area:** Dehradun, Uttarakhand
**Deployment:** Local, zero-cost academic prototype
**Primary languages:** C and Python
**Frontend:** React + TypeScript
**Database:** SQLite

### Document status

This document is the **current planning source of truth for implementation**. This is the v12 session-management revision. It builds on the v11 authentication/documentation baseline and v8 application-service baseline. It adds a server-side Sessions schema, a local Admin password-hash bootstrap utility, and schema/bootstrap tests. Flask authentication and frontend workflows remain specified, not implemented; the presence of the Sessions table does not mean login, logout, CSRF enforcement, or session middleware has been implemented.

It preserves the finalized project structure and incorporates the later corrections made during the final consistency review. If a future implementation decision conflicts with this document, it should be treated as a **scope/architecture change**, not as an implicit change to the baseline.

---

# 1. Project Scope

The system is an **AI-assisted multi-emergency response and resource optimization system** that begins only after a human reports an emergency.

The system does **not** predict that an individual fire, heart attack, accident, crime, or other emergency will occur. It does not automatically detect emergencies.

The core workflow is:

**Emergency Report → Requirement Groups/Units → Priority Processing → Suitable Resources → Road-Distance Ranking → Organization Confirmation → Dispatch → Reassignment if Required → Completion → Historical Analytics → AI/ML Decision Support**

The project demonstrates this workflow in **Dehradun** using predefined locations and a locally prepared OpenStreetMap road network.

The system supports:

- multiple simultaneous emergencies;
- government and private organizations;
- multiple resource types;
- multiple resource units for one emergency;
- priority-based allocation;
- shortest physical road-distance routing;
- organization acceptance before dispatch;
- rejection, timeout and failure handling;
- reassignment;
- completion and return;
- historical analytics;
- AI/ML decision support.

The system does **not** include:

- live GPS;
- live vehicle movement;
- live traffic;
- live ETA;
- automatic emergency detection;
- emergency-occurrence prediction;
- automatic dispatch without organization acceptance;
- SMS/email/push infrastructure;
- paid APIs or services.

Emergency and resource locations use:

**District → Locality → Specific Location**

with optional free-text additional details.

Approximately **100–200 meaningful predefined locations** are planned for the demonstration area. The exact number is an implementation choice.

The design supports multiple simultaneous emergencies without imposing an artificial project-level hard limit.

---

# 2. Emergency Reporting and Public Workflow

The reporter does not need an account.

Three reporting sources are supported through a self-declared `reporter_type` field:

- `CITIZEN`
- `BYSTANDER`
- `AUTHORIZED_EMERGENCY_OPERATOR`

`reporter_type` is informational and self-declared. It is not proof of identity, employment, authority, or emergency-service affiliation.

The reporter enters:

- Emergency Type
- District → Locality → Specific Location (submitted text is retained if it cannot be matched to a routable predefined point)
- Optional additional location details
- Category-specific structured safety answers; applicable questions may be missing, and `UNSURE` is distinct from `NO`
- Description (required, 5–300 words; contextual only and never keyword-scored for severity)
- Reporter Name and Phone
- Reporter Type (`CITIZEN`, `BYSTANDER`, or `AUTHORIZED_EMERGENCY_OPERATOR`; self-declared and informational only)

The backend creates an **Emergency ID**. Each reporter form instance generates one UUID idempotency key and reuses that same UUID for retries of the same submission. A new form instance gets a new UUID. If a concurrent duplicate submission causes a database integrity error, the handler re-reads by idempotency key and returns the existing emergency when the payload matches; if the same key is reused with a different payload, return a conflict. The key is unique and required in SQLite; a retry must not generate a replacement key for the same form submission.

### Idempotency key and canonical payload

The `idempotency_key` must be a valid UUID generated once per reporter form instance. The same key must be reused for every retry of that submission. A new form instance generates a new UUID.

The canonical payload used for comparison consists of:

- `emergency_type` (`MEDICAL_EMERGENCY`, `FIRE`, `ROAD_TRAFFIC_ACCIDENT`, `THREAT_TO_LIFE_VIOLENCE`, `TRAPPED_PERSON_RESCUE`)
- `location_id`
- `location_text` (canonical submitted district/locality/specific-location text)
- `assessment_answers` (normalized category-specific answers; missing and `UNSURE` remain distinct)
- `description`
- `reporter_name`
- `reporter_phone`
- `reporter_type`
- `additional_details`

Normalize canonical values before storing and before comparing. Trim leading/trailing whitespace from text fields; if `additional_details` is omitted or null, store `''`, never SQL `NULL`. Store and compare the normalized reporter phone as exactly 10 digits for this India-only prototype: remove permitted spaces, hyphens and parentheses, accept a 10-digit number or `+91` followed by 10 digits, and reject other country codes or lengths. Thus `+91 98765 43210` and `9876543210` compare equally. Normalize enum values to the exact uppercase contract strings and reject unknown values. Do not otherwise alter description/name content.

The `idempotency_key` is not part of the canonical payload.

When a request uses an existing idempotency key:

1. If its canonical payload matches the stored payload, return the original emergency result without creating another Emergency, Requirement Group, Requirement Unit, or rerunning initial emergency creation.
2. If its canonical payload differs, return HTTP `409` with error code `IDEMPOTENCY_KEY_CONFLICT`. Do not modify the original emergency.
3. If concurrent requests cause a database integrity error, re-read the existing Emergency by `idempotency_key`. Return the original result only if the canonical payload matches; otherwise return the conflict response.

The `idempotency_key` must be a valid UUID at the API boundary and `NOT NULL` and `UNIQUE` in SQLite. The stored emergency fields provide the canonical payload for comparison; the implementation must compare all fields listed above, including normalized `additional_details`. A retry must never generate a replacement key for the same form submission.

The reporter can later use **Emergency ID + Phone** to check the emergency status. The backend compares both values and returns the same generic failure response for an unknown Emergency ID, a wrong phone number, or a mismatched pair; it must not reveal which value was wrong.

Status-verification throttling uses `STATUS_VERIFY_MAX_FAILURES = 10` and `STATUS_VERIFY_WINDOW_SECONDS = 300`. Track failures in memory by client address; after the threshold is reached, temporarily throttle further attempts. This is a lightweight local-prototype safeguard, not production-grade distributed rate limiting.

The reporter-facing terminal wording for an emergency with an unfulfilled requirement is: **“Resource requirement could not be fully fulfilled.”** Do not expose private resource IDs, internal candidate rankings, or internal failure reasons.

The public interface includes:

- Home
- Report Emergency
- Confirmation
- Check Status
- Guidelines/Information
- Registered Organizations
- Organization Registration (public organization onboarding; no admin self-registration)
- Login (public navigation entry for registered organization and provisioned admin users; protected dashboards require authentication and authorization)

Emergency type is a dropdown with `MEDICAL_EMERGENCY`, `FIRE`, `ROAD_TRAFFIC_ACCIDENT`, `THREAT_TO_LIFE_VIOLENCE`, and `TRAPPED_PERSON_RESCUE`. The reporter does **not** choose severity or resource quantities. The backend assigns severity from validated structured answers using the versioned category-specific rules below. The reporter may leave safety answers missing; the report is accepted when core fields are valid and missing answers are preserved as missing.

The reporting workflow is:

1. Reporter submits the emergency.
2. Backend validates the submission.
3. Backend creates the emergency and requirement groups/units.
4. Requirement units enter the priority/allocation workflow.
5. Suitable resources are identified.
6. Candidates are ranked by shortest road distance.
7. One candidate is requested at a time.
8. The organization has the configured response deadline: 30 seconds in the normal profile or 20 seconds in the demo profile. The selected startup profile is authoritative; the UI must display the actual deadline for that run.
9. Acceptance causes dispatch.
10. Rejection or timeout causes reassignment.
11. If a dispatched resource fails, replacement processing begins.
12. Completion occurs only after work completion, resource return, and readiness confirmation.
13. Requirement units become fulfilled.
14. Emergency status is derived from the current requirement-unit states.

The reporter never sees internal candidate rankings, internal resource IDs, private organization information, or internal decision structures.

---

# 3. Emergency Types, Structured Assessment, Severity and Quantity Rules

The five canonical emergency types and API values are:

1. `MEDICAL_EMERGENCY` — Medical Emergency
2. `FIRE` — Fire
3. `ROAD_TRAFFIC_ACCIDENT` — Road Traffic Accident
4. `THREAT_TO_LIFE_VIOLENCE` — Threat to Life / Violence
5. `TRAPPED_PERSON_RESCUE` — Trapped Person / Rescue

Severity is assigned by backend rules, not selected by the reporter or frontend. Severity levels are `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, ordered **Critical > High > Medium > Low**. These are project-defined demonstration rules, not validated clinical, fire-service, police, or official triage standards. Persist the assigned severity, rule version, assessment reasons, uncertainty flag, and structured answers. The description is contextual only: do not score keywords or use description text to assign severity.

## Core report validation and incomplete answers

Core required fields are emergency type, submitted location hierarchy, a 5–300-word description, reporter name, reporter phone, reporter type, and idempotency key. If the submitted location cannot be matched to a routable predefined point, accept and retain the report as location-unresolved, keep it visible for urgent handling, and pause candidate selection and normal dispatch until the location is resolved. Only an authenticated, explicitly authorized emergency operator/admin may resolve it by selecting a valid predefined `location_id` with a routable `road_node_id`; the service must verify the location/node relationship and record the resolving actor, UTC timestamp, and reason in the audit/event log. Preserve the original submitted `location_text` and resolution history. Do not invent coordinates or a road node. After resolution, re-enter the ordinary coordinator workflow using the existing severity and requirements; do not create a second emergency or reset its priority/pending deadlines. An unresolved location alone must never cause `NO_ROUTE` or `UNFULFILLED`. Add a coordinator/state-service test that submits an unresolved emergency, runs the coordinator, and verifies it remains visible while candidate selection/routing is skipped without raising an error or creating `NO_ROUTE`/`UNFULFILLED` events. This test belongs with the coordinator tests once that implementation exists; the current schema-only tests do not verify coordinator behavior.

Category-specific questions are shown only for the selected emergency type. Every applicable safety question allows `UNSURE`/`UNKNOWN` where relevant. `UNSURE` is not `NO`; an omitted answer remains missing. Do not block a report solely because a safety answer is missing. If missing or conflicting safety information prevents safe assessment and no Critical trigger is confirmed, assign provisional `HIGH`, set `assessment_uncertain = true`, and record the reason. A confirmed Critical trigger takes precedence even if other answers are missing. Missing or contradictory answers must never silently produce `LOW`.

If structured answers conflict, preserve the submitted answers and record the discrepancy. If description text sounds more serious than the structured answers, preserve the description and record a discrepancy, but do not use text keywords to change severity. Resource unavailability never lowers severity. No separate `NEEDS_REVIEW` emergency status is introduced.

## Category-specific questionnaire

- **Fire:** observable signs (smoke only, flames, both, suspected fire without visible signs, unsure); apparent fire area (object/small area, one room/vehicle, multiple areas, outdoors/vegetation, unsure); spread (none observed, beyond start area, multiple areas/structures, unsure); anyone trapped/unable to evacuate (yes/no/unsure); injuries or breathing difficulties (yes/no/unsure); additional hazard (gas/explosion/hazardous material, none observed, unsure).
- **Medical Emergency:** awake/responding normally (yes, unresponsive/difficult to wake, unsure); breathing normally (yes/no or severe difficulty/unsure); severe bleeding (yes/no/unsure); possible life-threatening symptoms (yes/no/unsure); serious injury (yes/no/unsure); rapidly worsening (yes/no/unsure).
- **Road Traffic Accident:** incident type; injuries (yes/no/unsure); trapped in vehicle/unable to exit (yes/no/unsure); unresponsive, abnormal breathing, or severe bleeding (yes/no/unsure); fire/smoke/fuel leakage/other hazard (yes/no/unsure); road obstruction or ongoing danger (yes/no/unsure).
- **Threat to Life / Violence:** happening now (yes/no ended/unsure); attack, immediate-harm threat, or prevented escape (yes/no/unsure); weapon reportedly present/used (yes/no/unsure); injuries/urgent medical help reported (yes/no/unsure); threat escalating/spreading (yes/no/unsure).
- **Trapped Person / Rescue:** trapping context (building/room, vehicle, debris/collapse, floodwater/terrain, other/unsure); can person escape without help (yes/no/unsure); responsive and breathing normally as far as reporter can tell (yes/no/unsure); immediate environmental danger (fire/smoke/flood/collapse/other, none observed, unsure); condition/trapping worsening (yes/no/unsure); number trapped (one/more than one/unknown). A person still trapped cannot be classified Low merely because they seem responsive.

## Severity rule order and conservative fallback

Evaluate confirmed Critical triggers first, then High triggers, then Medium. Assign Low only when explicit low-severity conditions are satisfied and the answers are sufficiently complete and consistent. A confirmed Critical trigger cannot be cancelled by unrelated negative answers.

| Category | Critical triggers | High triggers | Medium | Low eligibility (all must hold) |
|---|---|---|---|---|
| Medical Emergency | Unresponsive/difficult to wake; abnormal breathing/severe breathing difficulty; severe bleeding; reported potentially life-threatening symptoms | Serious injury or rapidly worsening condition without a Critical trigger | Medical response needed, without High/Critical trigger | Clearly limited condition; responsive, breathing normally, no severe bleeding, serious injury, life-threatening symptoms, or rapid worsening |
| Fire | Person trapped in fire; reported life-threatening condition; immediate life-threatening explosion or similar hazard | Fire spreading across multiple areas/structures; significant danger without Critical trigger | Confirmed fire requiring response without High/Critical trigger | Clearly confined/limited or suspected fire; no spread, injuries, or additional hazards; answers sufficiently complete and consistent |
| Road Traffic Accident | Life-threatening medical signs, or trapped person with immediate life-threatening hazard | Serious crash, trapped person, significant hazard, or substantial ongoing danger without Critical trigger | Accident requiring response without High/Critical trigger | Clearly limited collision; no injuries, entrapment, fire/fuel hazard, or ongoing danger; answers sufficiently complete and consistent |
| Threat to Life / Violence | Immediate credible threat of death or serious harm, including ongoing life-threatening attack | Active serious threat, reported weapon, prevented escape, or escalating violence without Critical trigger | Reported threat/violence requiring response without High/Critical trigger | Threat ended; no injury, weapon, immediate threat, or continuing danger; answers sufficiently complete and consistent |
| Trapped Person / Rescue | Trapped person unresponsive, breathing abnormally, or facing immediate life-threatening environmental hazard | Unable to escape, multiple people trapped, worsening conditions, or substantial environmental danger without Critical trigger | Rescue needed without High/Critical trigger | No longer trapped and no continuing danger or injury; answers sufficiently complete and consistent |

If a required safety answer is missing or contradictory and no Critical trigger is confirmed, use provisional `HIGH` with uncertainty where that information blocks safe assessment. If Critical is confirmed, use `CRITICAL` even with other missing answers. Description is never keyword-scored.

## Atomic Requirement Group Quantity Reconciliation

`Requirement_Groups.quantity_required` is the **effective active-unit quantity** for that resource type after reconciliation. It must equal the number of child Requirement Units whose status is not `CANCELLED`. The severity matrix supplies the new target quantity; the effective quantity may be higher when already-dispatched or fulfilled units must be preserved.

All quantity changes occur inside the same `BEGIN IMMEDIATE` transaction as the operational severity update and its `Severity_Audit_History` insert. The central state-transition service calls one reconciliation procedure per affected resource type, then recomputes group and Emergency statuses before commit. Any failed step rolls back the severity change, audit row, unit changes, allocation cancellations, resource releases, events, and status recomputations together.

Rules:

1. **Increase:** retain every existing unit and allocation-history row. Append new `PENDING` Requirement Units with monotonically increasing `unit_number` values; never reuse a unit ID or unit number.
2. **Decrease:** preserve every `DISPATCHED` and `FULFILLED` unit. These are protected commitments/history and are never withdrawn or rewritten.
3. Retire surplus units in descending `unit_number` order, considering only `PENDING`, `REQUESTED`, or `UNFULFILLED` units. Set retired units to the terminal internal status `CANCELLED` and clear `pending_since`/`expires_at`. Keep their rows so existing allocation/event foreign keys and history remain valid.
4. If a surplus unit is `REQUESTED`, its single active Allocation must be changed to `CLOSED` / `CANCELLED`, `response_at` must be recorded, the reserved Resource must return to `AVAILABLE`, and a `CANCELLED` Allocation Decision Event must be written. These changes and the unit retirement are atomic. A missing or multiple active Allocation for a `REQUESTED` unit is an invariant failure and aborts the transaction.
5. The effective quantity is `max(new severity-matrix target, count(DISPATCHED + FULFILLED units))`. Thus a severity decrease may temporarily leave `quantity_required` above the new matrix target when protected units exceed it. No additional units are created for that excess; no new dispatch is made for retired units.
6. After reconciliation, `quantity_required` must equal the count of non-`CANCELLED` child units. Group and Emergency statuses are derived only from non-`CANCELLED` units. A group/Emergency cannot have zero active units. The SQLite trigger `trg_requirement_group_summary_matches_units` validates the child-unit count and derived group status whenever the parent summary is updated. The reconciliation service updates child units first and the summary second, within one transaction. SQLite has no deferred cross-table constraints, so child-unit writes remain restricted to the reconciliation/state-transition services; `assert_invariants()` checks both group and Emergency summary statuses after each completed transition.
7. A severity increase appends only the difference between the new target and current active-unit count. A decrease retires only the surplus over the effective quantity. If an operation cannot satisfy these postconditions, it fails and rolls back.
8. A historical severity correction after Emergency `COMPLETED` is audit-only: it does not call quantity reconciliation, change `quantity_required`, alter units, or reopen allocation.

`CANCELLED` is an internal Requirement Unit terminal status meaning the unit was removed from the active target by an authorized severity reduction. It is distinct from `UNFULFILLED`, which means a still-required unit could not be fulfilled. Cancelled units are excluded from active quantity and group/Emergency status derivation, but retained permanently for referential and audit history.

**Existing database note:** adding `CANCELLED` changes the `Requirement_Units.status` CHECK constraint. `CREATE TABLE IF NOT EXISTS` does not alter an existing v6 table. A v6 database must be rebuilt from the v7 schema or upgraded with a separately tested SQLite table-rebuild migration before this code is used; do not assume rerunning `schema.sql` applies the new constraint. A v7 database already has the `CANCELLED` status; v8 adds the `trg_requirement_group_summary_matches_units` trigger, which can be installed with the updated schema script, but verify the existing group quantity/status data with `assert_invariants()` before enabling normal writes.

## Resource requirement quantities

Fixed baseline quantities are based on emergency category and assigned severity. Conditional additions are applied once each based on structured answers: (1) Road Traffic Accident adds one `RESCUE_VEHICLE` if someone is trapped and adds one `FIRE_VEHICLE` if fire, smoke, or fuel leakage is reported; (2) Trapped Person / Rescue adds one `FIRE_VEHICLE` if an active fire or smoke hazard is reported. Do not duplicate an addition for repeated answers indicating the same condition.

| Emergency | Low | Medium | High | Critical |
|---|---|---|---|---|
| Medical Emergency | 1 Ambulance | 1 Ambulance | 2 Ambulances | 3 Ambulances |
| Fire | 1 Fire Vehicle | 1 Fire Vehicle + 1 Ambulance + 1 Police Unit | 2 Fire Vehicles + 2 Ambulances + 1 Police Unit | 3 Fire Vehicles + 3 Ambulances + 2 Police Units |
| Road Traffic Accident | 1 Ambulance + 1 Police Unit | 1 Ambulance + 1 Police Unit | 2 Ambulances + 1 Police Unit | 3 Ambulances + 2 Police Units |
| Threat to Life / Violence | 1 Police Unit | 1 Police Unit | 2 Police Units + 1 Ambulance | 2 Police Units + 2 Ambulances |
| Trapped Person / Rescue | 1 Rescue Vehicle | 1 Rescue Vehicle + 1 Ambulance | 2 Rescue Vehicles + 2 Ambulances + 1 Police Unit | 3 Rescue Vehicles + 3 Ambulances + 2 Police Units |

A quantity such as three ambulances expands into three individual Requirement Units. Conditional additions are merged into the same requirement group for the matching resource type.

## Severity changes after allocation begins

A severity reduction after dispatch does not withdraw resources already dispatched: keep those resources assigned until their response is completed. Completed (`FULFILLED`) units are also preserved as historical responses. Cancel outstanding requests that are no longer required, release their reserved resources, and stop future dispatches for requirements removed by the revised matrix. Preserve valid existing assignments and recompute only outstanding requirements; do not create duplicate fulfillment. Every operational override records old/new severity, reason, actor, timestamp, and assessment/rule context. After emergency completion, an authorized actor may make an audited historical severity correction, but it must not reopen the emergency, alter completed allocation history, or trigger any new resource request/dispatch. See the atomic Requirement Group Quantity Reconciliation rule below for exact unit-level behavior.

# 4. Resources and Organizations

Four resource types are finalized:

- Ambulance
- Fire Vehicle
- Police Unit
- Rescue Vehicle

Organizations are classified as:

- Hospital/Medical
- Fire Service
- Police/Security
- Rescue/Disaster Response

Organizations may be:

- Government
- Private

Government and private ownership do **not** create a preference once a resource is otherwise eligible.

Organization type is an administrative classification. It is **not** a separate specialist capability-matching engine.

Resource eligibility is primarily based on the required resource type.

The project deliberately avoids unnecessary specialist capability, certification, equipment, or skill scoring.

---

# 5. Organization Registration and Deactivation

Organizations register through the organization interface.

A newly registered organization is:

**ACTIVE**

There is no separate approval workflow in v1. The public registration form requires organization name, organization type, ownership, email, and password; phone is optional. The backend accepts ASCII email addresses, trims and lowercases them before lookup/storage, validates uniqueness case-insensitively, generates the organization ID, hashes the password server-side, and sets status to `ACTIVE`. The client must never submit `organization_id`, `password_hash`, or `status`. A successful registration returns the organization ID/name/status and directs the user to the shared Login page; it does not automatically create an authenticated session. Duplicate email returns `409 EMAIL_ALREADY_REGISTERED`.

Passwords are never stored or logged in plaintext. v1 uses PBKDF2-HMAC-SHA256 with a fresh cryptographically random 16-byte salt and 600,000 iterations. Store the encoded form `pbkdf2_sha256$600000$<salt_base64>$<digest_base64>`; compare hashes using a constant-time comparison. Organization passwords must contain 12–128 characters. Registration and login transmit passwords only over HTTPS in hosted use; local development may use localhost.

Organizations can later become:

**INACTIVE**

Inactive organizations:

- cannot receive new requests;
- cannot add active resources;
- cannot accept requests;
- retain their historical records.

## Administrator account provisioning and server-side sessions

There is no public administrator registration endpoint and no Admin credentials table in v1. Provision exactly one Admin identity locally before starting Flask using `RESQTECH_ADMIN_ID`, `RESQTECH_ADMIN_EMAIL`, and `RESQTECH_ADMIN_PASSWORD_HASH`. The Admin email must be a valid ASCII email, normalized by trimming and lowercasing, and must not match any organization email. Startup must fail closed if a required setting is missing or invalid, the encoded hash does not use the approved PBKDF2 parameters/lengths, the override flag is not exactly `true` or `false`, or the Admin email collides with an organization. The Admin ID is an environment-backed principal identifier, not a foreign key to an Admin table.

The local utility `scripts/bootstrap_admin.py` prompts for the Admin ID, email, and password (without echoing the password), validates them, and prints PowerShell environment-variable assignments for the current terminal session. It generates `pbkdf2_sha256$600000$<salt_base64>$<digest_base64>` using a fresh cryptographically random 16-byte salt and a 32-byte PBKDF2-HMAC-SHA256 digest. It does not create a database row, write the plaintext password/hash to a file, or persist environment variables. Do not commit, publish, or paste the generated hash into source control or public messages. Run Flask from the same terminal session after setting the values.

`RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY` defaults to `false`; only the exact value `true` grants `EMERGENCY_SEVERITY_OVERRIDE`. The `ADMIN` role alone grants monitoring access, not severity override or allocation/dispatch control. Multiple Admin accounts and an Admin management UI are out of scope for v1.

### Shared server-side session contract

Organization and Admin users authenticate through the same `POST /auth/login` endpoint. A successful login creates one server-side row in `Sessions`; this table stores session metadata and token digests, not Admin credentials. Generate independent cryptographically random 32-byte session and CSRF tokens. Encode each as unpadded URL-safe Base64 for transport and store only its lowercase SHA-256 hex digest in `session_token_hash` and `csrf_token_hash`. Never store or return the raw session token in JSON.

Set the session token in the `resqtech_session` cookie with `HttpOnly`, `SameSite=Lax`, `Path=/`, and an eight-hour `Max-Age`; set `Secure` on hosted HTTPS deployments (localhost development may omit `Secure`). Set the CSRF token in a separate `resqtech_csrf` cookie with `SameSite=Lax`, `Path=/`, the same lifetime and HTTPS `Secure` rule, intentionally without `HttpOnly` so same-origin frontend code can read it and copy it into the `X-CSRF-Token` request header. The server hashes the header value and constant-time compares it with the current session's stored CSRF digest. The CSRF token is session-bound; do not accept a token from a different session. Do not put either token in localStorage/sessionStorage or application logs.

Every protected request must hash the session cookie and find a matching `Sessions` row with `revoked_at IS NULL` and `expires_at` later than the current UTC time. Organization sessions additionally require the referenced organization to remain `ACTIVE`; Admin sessions require the principal ID to match the validated configured Admin identity. Enforce role, ownership, and permission checks on every endpoint. Every authenticated state-changing request, including logout, must pass the CSRF header check. Prefer serving React and Flask behind one origin. If local development serves them on separate origins/ports, allow only the exact configured frontend origin and enable credentialed CORS for that origin alone; validate the `Origin` header on state-changing requests and never use wildcard credentialed CORS. The frontend must send credentials with requests. `SameSite=Lax` is defense in depth, not a replacement for CSRF validation. Frontend route guards are not authorization controls.

Sessions have an absolute eight-hour lifetime and are not sliding-renewed. `POST /auth/logout` revokes the current row by setting `revoked_at` inside a transaction, then clears both cookies using matching path/SameSite/Secure attributes. A copied/replayed session token is rejected immediately after revocation; cleanup of expired rows is optional maintenance and is not relied on for logout. On expiry, clear both cookies and require login again. The v1 `Sessions` table permits Admin sessions with `organization_id=NULL` and Organization sessions whose `principal_id` equals the foreign-key `organization_id`; Admin identity remains environment-backed.

The schema's `Sessions` table and its constraints/indexes are implemented in v12. Flask login/session middleware, CSRF checks, origin checks, revocation handling, and end-to-end authentication tests are still implementation work and must not be described as completed until built and tested.

## Deactivation rule

Deactivation is allowed only after resolving active operational work.

If an organization requests deactivation, use this single ordered procedure:

1. Acquire the coordinator RLock and inspect authoritative SQLite state before making any changes.
2. If any allocation for the organization is `DISPATCHED`, reject deactivation and return a conflict response. **No allocation, resource, Requirement Unit, Requirement Group, Emergency, or organization state is changed.**
3. Otherwise, perform one `BEGIN IMMEDIATE` transaction. Revalidate that no `DISPATCHED` allocation exists. Cancel every `REQUESTED` allocation; set its resource to `AVAILABLE` as an intermediate state and then to `INACTIVE`; return the affected Requirement Unit to `PENDING` while preserving its current pending-episode timestamps; write the applicable cancellation events; move the organization's `AVAILABLE` and `UNAVAILABLE` resources to `INACTIVE`; set the organization to `INACTIVE`; recompute/materialize affected Requirement Group and Emergency statuses; then commit.
4. After a successful commit, run the coordinator so returned pending units can be processed against the now-updated authoritative state.

There is therefore **no inactive-organization completion path**. Historical records remain retained. The DISPATCHED pre-check must happen before any cancellation or resource mutation; do not duplicate this rule elsewhere with a different sequence.

---

# 6. Resource Lifecycle and State Rules

Final resource states:

- `AVAILABLE`
- `REQUESTED`
- `DISPATCHED`
- `UNAVAILABLE`
- `INACTIVE`

Allowed transitions:

| Current    | Event                                | Next       | Required behavior                                                   |
|------------|--------------------------------------|------------|---------------------------------------------------------------------|
| AVAILABLE  | Atomic reservation                   | REQUESTED  | Resource is reserved for one allocation request                     |
| REQUESTED  | Organization accepts before deadline | DISPATCHED | Allocation becomes accepted; Requirement Unit becomes DISPATCHED    |
| REQUESTED  | Organization rejects                 | AVAILABLE  | Allocation closes as rejected; Requirement Unit returns to PENDING  |
| REQUESTED  | Request times out                    | AVAILABLE  | Allocation closes as timed out; Requirement Unit returns to PENDING |
| REQUESTED  | Allocation is cancelled              | AVAILABLE  | Allocation closes as cancelled; Requirement Unit returns to PENDING |
| DISPATCHED | Resource failure                     | UNAVAILABLE| Allocation becomes failed; Requirement Unit returns to PENDING;   reassignment is evaluated                                                                                                              |
| DISPATCHED | Completion + return/readiness        | AVAILABLE  | Allocation becomes completed; Requirement Unit becomes FULFILLED; history is recorded                                                                                                                    |
| AVAILABLE  | Manual unavailable                   | UNAVAILABLE| Organization removes resource from service                          |
| UNAVAILABLE| Manual available                     | AVAILABLE  | Resource becomes available for eligibility checks                   |
| AVAILABLE  | Individual resource deactivation     | INACTIVE   | Allowed through central state-transition service                    |
| UNAVAILABLE| Individual resource deactivation     | INACTIVE   | Allowed through central state-transition service                    |
| REQUESTED  | Organization deactivation, with no DISPATCHED allocation | AVAILABLE → INACTIVE | Deactivation transaction cancels request, returns unit to PENDING, then deactivates resource                                                                            |
| AVAILABLE  | Organization deactivation, with no DISPATCHED allocation | INACTIVE | Deactivation transaction deactivates resource     |
| UNAVAILABLE| Organization deactivation, with no DISPATCHED allocation | INACTIVE | Deactivation transaction deactivates resource     |

Blocked transitions:

- `REQUESTED → UNAVAILABLE`
- `REQUESTED → INACTIVE`
- `DISPATCHED → INACTIVE`
- `DISPATCHED → AVAILABLE` through a generic status endpoint
- `INACTIVE → AVAILABLE` in v1

A resource has at most **one active assignment**.

All critical resource state changes pass through the central state-transition service.

The organization resource-status endpoint does not directly mutate the database state.

---

# 7. Priority Processing and Pending Resource Heaps

The project uses real C priority structures rather than replacing the data-structure requirement with database sorting.

There is one **pending min-heap per resource type**:

- Ambulance
- Fire Vehicle
- Police Unit
- Rescue Vehicle

Each heap contains references only to `PENDING` Requirement Units of its corresponding required resource type. New Requirement Units start in `PENDING` and are inserted into the matching heap. **Every transition into `PENDING` must enqueue the unit** after the authoritative SQLite transition succeeds.

Heap ordering uses the **Canonical Priority Comparator** within each resource-type heap:

1. Higher severity (`CRITICAL > HIGH > MEDIUM > LOW`)
2. Earlier parent-emergency `reported_at`
3. Lower `requirement_unit_id`

There is no cross-resource-type competition: an Ambulance heap is compared only with Ambulance units, a Fire Vehicle heap only with Fire Vehicle units, and so on. The same canonical comparator is used wherever pending units of one resource type are ordered.

The heaps are **derived indexes**, not the source of truth.

SQLite remains authoritative.

A stale heap entry must be revalidated against SQLite before it is used. The C heap implementation maintains an `in_heap` flag per Requirement Unit and deduplicates insertion: if the unit is already represented in the heap, do not add a duplicate. A state change that makes a unit ineligible is resolved through authoritative revalidation; stale entries are skipped/removed safely.

During a coordinator pass, a unit temporarily set aside because its resource type or current candidate evaluation cannot be processed must be reinserted after that pass if it remains `PENDING` and is not already in the heap.

A top unit for which every candidate returns `NO_ROUTE` must not block lower-priority units of the same resource type. Record route failures per `(requirement_unit_id, resource_id)` and continue scanning the remaining eligible units/candidates for that pass.

There is **no separate “ready heap.”**

When a resource becomes available, the coordinator:

1. identifies relevant pending units through the resource-type heap;
2. revalidates their current SQLite state;
3. applies the Canonical Priority Comparator to valid units within this resource-type heap;
4. continues past a unit whose candidate set contains only `NO_ROUTE` results so it cannot block lower-priority units;
5. selects the highest-priority valid unit with a routable candidate;
6. performs candidate selection and atomic reservation.

The type-specific heaps apply the Canonical Priority Comparator within each resource type; resource types do not compete against one another in a single global heap.

A new emergency does not interrupt an allocation operation already in progress. A coordinator pass must remain bounded: if one Requirement Unit has no routable candidates, continue scanning lower-priority units in that same resource-type heap; after the pass, reinsert every set-aside unit that remains `PENDING` and is not already represented (`in_heap` prevents duplicates).

---

# 8. Candidate Resource Selection

For each Requirement Unit, candidates are evaluated in this order:

1. Required resource type
2. ACTIVE organization
3. AVAILABLE resource
4. Valid base location
5. No active assignment
6. Shortest road distance
7. Resource ID tie-break
8. Atomic SQLite reservation
9. Organization acceptance request

Government and private resources are treated equally.

Routing uses the resource's **base location**, not its last reported location.

A candidate with no valid road path is excluded.

Candidates are requested **one at a time**.

A candidate resource with **any Allocation row for the same Requirement Unit is permanently excluded from future candidate selection for that unit**. Allocation history is authoritative and this exclusion survives restart. The transient C-side tried-candidate set is used only for reservation races within the current coordinator pass.

A failed reservation race is **not an allocation attempt unless an Allocation record was successfully created**.

Every actual candidate attempt is therefore traceable through the Allocation table.

---

# 9. Requirement-Unit Lifecycle

Every individual required resource unit has its own lifecycle:

**PENDING → REQUESTED → DISPATCHED → FULFILLED**

Additional transitions:

**REQUESTED → PENDING**

after rejection, timeout, or cancellation. Preserve `pending_since`, `expires_at`, and `episode_count` through `REQUESTED`; a rejection, timeout, or cancellation alone does not reset the current pending episode.

**DISPATCHED → PENDING**

when a dispatched resource fails and replacement is required. Entry into `DISPATCHED` clears `pending_since` and `expires_at`. After a dispatched failure, the unit returns to `PENDING` and the unified pending rule in §§11–12 applies; a new episode may be started if the episode-count limit permits.

On transitions to `FULFILLED`, `UNFULFILLED`, or `CANCELLED`, clear `pending_since` and `expires_at`. Keep `episode_count` as the historical count for the unit.

**PENDING → UNFULFILLED**

when the applicable pending deadline expires and the requirement can no longer be fulfilled.

**PENDING / REQUESTED / UNFULFILLED → CANCELLED**

only when an authorized operational severity reduction removes that unit from the revised requirement. A `REQUESTED` unit's active Allocation is closed as `CANCELLED` and its reserved resource is released in the same transaction. Ordinary candidate rejection/timeout/cancellation still returns a still-required unit to `PENDING`.

A unit becomes `FULFILLED` only after:

1. response work is complete;
2. resource has returned;
3. organization confirms readiness.

A multi-resource emergency therefore has multiple independent requirement units and allocation attempts.

---

# 10. Allocation State Model

An Allocation represents **one candidate attempt**.

A Requirement Unit may have multiple Allocation records over time.

## Allocation response status

- `PENDING`
- `ACCEPTED`
- `REJECTED`
- `TIMEOUT`
- `CANCELLED`

## Allocation operational status

- `REQUESTED`
- `DISPATCHED`
- `COMPLETED`
- `FAILED`
- `CLOSED`

Initial allocation:

**REQUESTED + PENDING**

Accepted:

**DISPATCHED + ACCEPTED**

Completed:

**COMPLETED + ACCEPTED**

Failed:

**FAILED + ACCEPTED**

Rejected:

**CLOSED + REJECTED**

Timeout:

**CLOSED + TIMEOUT**

Cancelled:

**CLOSED + CANCELLED**

Completion and failure operations are valid only while the allocation is operationally `DISPATCHED`.

### Allowed response/operational status combinations and invariants

The only valid persisted combinations are:

| Operational status | Response status | Meaning                                                                         |
| ------------------ | --------------- | --------------------------------------------------------------------------------|
| `REQUESTED`        | `PENDING`       | Waiting for the organization response                                           |
| `DISPATCHED`       | `ACCEPTED`      | Accepted and currently dispatched                                               |
| `COMPLETED`        | `ACCEPTED`      | Response work and resource return/readiness are complete                        |
| `FAILED`           | `ACCEPTED`      | The dispatched response failed; reassignment may follow                         |
| `CLOSED`           | `REJECTED`      | Organization rejected before dispatch                                           |
| `CLOSED`           | `TIMEOUT`       | No valid response before the deadline                                           |
| `CLOSED`           | `CANCELLED`     | Request cancelled before dispatch, including permitted organization deactivation|

No other combination is valid. In particular, `DISPATCHED`, `COMPLETED`, or `FAILED` requires `ACCEPTED`; `REJECTED`, `TIMEOUT`, and `CANCELLED` require `CLOSED`. A terminal Allocation never reopens and receives only one terminal outcome. A failed or closed Allocation remains in history; a later attempt creates a new Allocation row. Resource and Requirement Unit state must be changed in the same authoritative transition as the Allocation, with affected Requirement Group and Emergency statuses recomputed in that workflow.

Duplicate or conflicting terminal actions are rejected.

---

# 11. Pending-Episode Window

The pending-episode window belongs to a **Requirement Unit's pending episode**, not to each candidate attempt.

A Requirement Unit may have:

- `PENDING` with `pending_since = NULL` and `expires_at = NULL` → ready for allocation processing and not currently waiting in an active pending episode;
- `PENDING` with timestamps set → active pending episode.

When a new waiting episode begins, perform one SQLite transaction that sets `pending_since`, sets `expires_at`, increments `episode_count`, writes `PENDING_STARTED`, recomputes/materializes Requirement Group and Emergency statuses, and commits.

`expires_at = pending_since + PENDING_EPISODE_SECONDS` using the selected profile's value

A rejection or timeout does **not** automatically restart the pending-episode window.

If another candidate is immediately available, reassignment proceeds without resetting the existing episode.

Dispatch clears `pending_since` and `expires_at` when the Requirement Unit enters `DISPATCHED`. If that dispatched resource later fails, the unit returns to `PENDING` and the unified pending rule in §§11–12 applies. A second pending episode is possible only if `episode_count < MAX_PENDING_EPISODES`; this bounded rule prevents unlimited episodes.

The backend sweeper is authoritative.

The browser is never the authority for pending expiry.

The sweeper expires only `PENDING` units. Timestamp policy is explicit: timestamps are preserved through `REQUESTED`; they are cleared on entry to `DISPATCHED`, and on transition to `FULFILLED` or `UNFULFILLED`. After rejection, timeout, or ordinary candidate-request cancellation, a still-required unit returns to `PENDING` with its existing episode timestamps preserved. The separate severity-reduction retirement path sets surplus units to `CANCELLED` and clears those timestamps. A dispatched failure returns the unit to `PENDING` after the timestamps were cleared at dispatch, so the unified rule may start a new episode if the episode-count limit allows. When an episode expires, candidate eligibility is rechecked first. If a candidate exists, allocation is attempted; if no candidate exists, the Terminal Episode Rule marks the unit `UNFULFILLED` and clears the episode timestamps atomically. An expired episode remains the current episode until that terminal transition occurs.

---

# 12. Rejection, Timeout and Reassignment

When an organization rejects a request:

1. The central state service verifies the current allocation state.
2. The rejection is recorded.
3. The Allocation is closed.
4. The resource returns to `AVAILABLE`.
5. For rejection, timeout, ordinary candidate-request cancellation, and dispatched-resource failure, the still-required Requirement Unit returns to `PENDING`; the pending rules then decide candidate selection, episode handling, or `UNFULFILLED`. A severity-reduction retirement is the explicit exception: a no-longer-required unit becomes `CANCELLED`.
6. The coordinator immediately evaluates the next eligible candidate.

When a request times out, the equivalent transition occurs through the timeout workflow.

The existing pending episode is preserved.

The timer is **not reset**.

All paths that return a Requirement Unit to `PENDING`—rejection, timeout, cancellation, and dispatched-resource failure—must call the same pending-resolution procedure. Do not implement separate episode logic in the coordinator, sweeper, accept/reject handlers, or failure handler.

**Unified pending-resolution procedure:**

1. Re-read the Requirement Unit, parent Emergency, Requirement Group, and relevant Allocation/resource state from SQLite under the coordinator RLock; never trust a stale heap entry or in-memory status.
2. If a valid routable candidate exists, attempt the normal one-at-a-time atomic reservation. A successful transition to `REQUESTED` preserves the current `pending_since`, `expires_at`, and `episode_count` unchanged.
3. If no candidate exists and `expires_at` is set and is at or before server time, apply the Terminal Episode Rule and mark the unit `UNFULFILLED` atomically.
4. If no candidate exists and the unit has an active, unexpired episode, leave its timestamps/count unchanged and keep it `PENDING`. Event-driven triggers should retry when a relevant resource becomes available or a candidate attempt closes; as a safety net, the sweeper also re-runs the same unified procedure for active-episode `PENDING` units every `PENDING_REEVALUATION_TICKS` sweeper ticks (approximately every 5 seconds), without resetting timestamps or incrementing `episode_count` unless a new episode actually starts.
5. If no candidate exists, no episode is active (`pending_since` and `expires_at` are both `NULL`), and `episode_count < MAX_PENDING_EPISODES`, start one episode atomically.
6. If no candidate exists, no episode is active, and `episode_count >= MAX_PENDING_EPISODES`, mark the unit `UNFULFILLED` atomically.
7. Recompute/materialize Requirement Group and Emergency statuses in the same transaction as any persisted unit transition. After commit, reconcile derived C heap state.

**Terminal Episode Rule:** if a Requirement Unit's current pending episode has expired and candidate evaluation finds no eligible routable candidate, the unit becomes `UNFULFILLED`; clear `pending_since` and `expires_at` as part of that terminal transaction. An expired episode remains the current episode until this terminal transition occurs. Candidate evaluation must happen before terminalizing an expired episode, so a currently eligible candidate can still be requested.

Starting an episode is atomic: set `pending_since` and `expires_at`, increment `episode_count`, write `PENDING_STARTED`, recompute/materialize Requirement Group and Emergency statuses, and commit in one SQLite transaction. The `UNFULFILLED` transition is also atomic: clear timestamps, write `UNFULFILLED`, recompute/materialize statuses, and commit in one transaction.

The transition and reassignment logic must avoid unnecessarily holding a large transaction open while searching for another candidate.

The accept-vs-timeout race is resolved authoritatively by the backend:

- current allocation state is checked;
- server deadline is checked;
- organization status is checked;
- reservation/state transition is performed inside the authoritative workflow.

If the request has already expired according to the server, **timeout wins**.

The accept handler itself executes the complete timeout transition under the coordinator RLock if the Allocation is still `REQUESTED`: Allocation becomes `CLOSED` + `TIMEOUT`, Resource becomes `AVAILABLE`, Requirement Unit returns to `PENDING`, one `TIMEOUT` event is written, statuses are recomputed, reassignment is evaluated, and the organization receives an `expired` response.

If the sweeper has already closed the Allocation as `TIMEOUT`, the accept handler returns `expired` without writing another event or repeating resource/unit updates or reassignment. If the Allocation is already closed for another reason, it is not reopened or overwritten; return the appropriate already-closed/conflict response. Any state returned by the endpoint is derived from the authoritative Allocation record; duplicate requests must be idempotent and must not duplicate history/events or repeat reassignment.

Exactly one terminal outcome is allowed.

---

# 13. Emergency Status Model

Emergency status is **derived from Requirement Unit states**.

Final emergency statuses:

- `PENDING`
- `PARTIALLY_ALLOCATED`
- `FULLY_ALLOCATED`
- `COMPLETED`
- `UNFULFILLED`

## Exact rules

Every accepted emergency must create at least one Requirement Group and at least one Requirement Unit. A zero-unit Emergency is invalid and must be rejected during creation rather than assigned an ambiguous status.

Emergency status is computed using the following precedence, in order, after each relevant authoritative transition:

1. `UNFULFILLED` if at least one Requirement Unit is terminally `UNFULFILLED` and full fulfillment is no longer possible.
2. `COMPLETED` if every Requirement Unit is `FULFILLED`.
3. `FULLY_ALLOCATED` if every Requirement Unit is `DISPATCHED` or `FULFILLED` (and at least one is `DISPATCHED`).
4. `PARTIALLY_ALLOCATED` if at least one Requirement Unit is `DISPATCHED` or `FULFILLED`, but the conditions above are not met.
5. `PENDING` otherwise.

This precedence prevents `COMPLETED` from overlapping with `FULLY_ALLOCATED`; `COMPLETED` takes precedence once every unit is fulfilled.

### PENDING

No requirement unit has been dispatched or fulfilled, and there is no terminal unfulfilled requirement that makes full fulfillment impossible.

### PARTIALLY_ALLOCATED

At least one requirement unit is `DISPATCHED` or `FULFILLED`, but not all units are `DISPATCHED`/`FULFILLED`, and the emergency is not terminally unfulfilled.

### FULLY_ALLOCATED

Every Requirement Unit is `DISPATCHED` or `FULFILLED`, at least one Requirement Unit is `DISPATCHED`, and no Requirement Unit is terminally `UNFULFILLED`. If every unit is `FULFILLED`, the earlier `COMPLETED` precedence applies instead.

### COMPLETED

Every requirement unit is `FULFILLED`.

### UNFULFILLED

At least one requirement unit is terminally `UNFULFILLED` and the original requirement can no longer be fully fulfilled.

`UNFULFILLED` takes precedence when full fulfillment is no longer possible.

`FULLY_ALLOCATED` does **not** mean completed.

If a dispatched unit fails and returns to `PENDING`, an emergency can move from `FULLY_ALLOCATED` back to `PARTIALLY_ALLOCATED`.

A single resource allocation can be `COMPLETED` while the overall emergency remains `PARTIALLY_ALLOCATED`.

Emergency status is recomputed and persisted as part of the authoritative state-transition workflow whenever relevant Requirement Unit/Allocation state changes.

Where the state transition affects the emergency status, the status update occurs **atomically with the relevant database transaction/workflow**.

---

# 14. Routing and OpenStreetMap

The project uses real OpenStreetMap road-network data prepared locally for Dehradun.

The project does not use:

- Google Maps routing;
- live routing APIs;
- live traffic;
- live ETA;
- runtime geocoding.

Each predefined location contains:

- location ID;
- district;
- locality;
- specific location;
- latitude;
- longitude;
- road-network node ID.

The road network contains:

- source node;
- destination node;
- physical distance;
- direction.

The C graph is a **directed weighted adjacency list**.

One-way roads are represented by one directed edge.

Two-way roads are represented by two directed edges.

Edge weight is physical road distance.

---

# 15. Dijkstra and Reverse-Dijkstra

Dijkstra is implemented in C.

It provides:

- shortest physical road distance;
- route node sequence.

For candidate ranking, **reverse-Dijkstra** may be used.

The directed road graph is reversed and a single run from the emergency node can obtain distances from multiple candidate bases to that emergency.

This preserves directed-road behavior.

Route reconstruction is performed separately.

If no valid route exists, the candidate is excluded.

Leaflet displays:

- emergency marker;
- selected resource-base marker;
- route;
- physical road distance.

No live movement is shown.

---

# 16. C ↔ Python Integration

C owns the computational algorithms and data structures.

C responsibilities include:

- priority heaps;
- resource-type pending heaps;
- graph/adjacency list;
- Dijkstra;
- reverse-Dijkstra;
- candidate ranking;
- tried-candidate tracking;
- reassignment selection.

Python/Flask owns:

- HTTP;
- authentication;
- authorization;
- validation;
- SQLite;
- business rules;
- workflow;
- central state transitions;
- coordination;
- timers;
- analytics;
- AI/ML.

Primary integration:

**React → Flask/Python → ctypes → C shared library → result → Flask → React**

A structured-input/output standalone C executable is only a fallback if ctypes integration is temporarily unavailable.

C never writes directly to SQLite.

SQLite is the persistent source of truth.

C structures are derived working state and can be rebuilt after restart.

A Python lock protects mutable shared C structures where required.

The Python lock does **not** replace SQLite transaction atomicity.

---

# 17. Database Design

The database contains the following core entities. `APIContracts.md` must carry the exact SQL schema and migration definitions; the constraints below are mandatory design requirements, not optional implementation suggestions.

## Organizations

- `organization_id`
- `name`
- `organization_type` (`HOSPITAL_MEDICAL`, `FIRE_SERVICE`, `POLICE_SECURITY`, `RESCUE_DISASTER_RESPONSE`)
- `ownership` (`GOVERNMENT`, `PRIVATE`)
- `phone`
- `email`
- `password_hash`
- `status`

## Resources

- `resource_id`
- `organization_id`
- `resource_type`
- `base_location_id`
- `last_reported_location_id`
- `status`
- `last_updated`

`base_location_id` is used as the routing origin.

`last_reported_location_id` is stored for operational information and is **not** the v1 routing origin.

## Locations

- `location_id`
- `district`
- `locality`
- `specific_location`
- `latitude`
- `longitude`
- `road_node_id`

## Emergencies

- `emergency_id`
- `emergency_type` (`MEDICAL_EMERGENCY`, `FIRE`, `ROAD_TRAFFIC_ACCIDENT`, `THREAT_TO_LIFE_VIOLENCE`, `TRAPPED_PERSON_RESCUE`)
- `location_id`
- `location_text` (canonical submitted district/locality/specific-location text)
- `location_resolved` (0/1; unresolved reports remain visible but normal dispatch is paused)
- `assessment_answers_json` (normalized category-specific answers; missing and `UNSURE` remain distinct)
- `assessment_uncertain` (0/1)
- `assessment_reasons`
- `severity_rule_version`
- `additional_details`
- `description`
- `reporter_name`
- `reporter_phone`
- `reporter_type` (self-declared `CITIZEN`, `BYSTANDER`, or `AUTHORIZED_EMERGENCY_OPERATOR`; informational only)
- `reported_at`
- `status`
- `data_source` (defaults to `OPERATIONAL` in SQLite; public emergency creation explicitly sets `OPERATIONAL` in the backend)
- `idempotency_key`

## Severity Audit History

- `severity_audit_id`, `emergency_id`, `old_severity`, `new_severity`, `reason`, `actor_id`, `changed_at`, `change_kind` (`OPERATIONAL_OVERRIDE` or `HISTORICAL_CORRECTION`)

**Enforcement requirement:** the central state-transition service is the sole application writer allowed to change `Emergencies.severity`. A severity change and its `Severity_Audit_History` insert MUST occur in the same `BEGIN IMMEDIATE` transaction. Validate the actor's explicit severity-override permission, non-empty reason, current old severity, requested new severity, and `change_kind`; insert the audit row and update severity in that transaction, then commit. If either write or any required follow-up fails, roll back the entire transaction so neither the severity change nor a partial audit remains. Do not expose a direct severity-update route or let other modules write this column. Run `assert_invariants(db)` after the transition and include a severity-audit invariant: audit rows form an ordered old→new chain per emergency (ordered by `changed_at`, then SQLite insertion `rowid` for same-second changes), the Emergency's current severity equals the final `new_severity`, and every row has a non-blank actor/reason, a valid change kind, and an actual severity change. The invariant check is diagnostic; it does not replace the atomic transaction. Direct SQL access is internal/test-only, not an application write path. The state-service test suite must include a negative test that attempts a severity transition without its audit insert and proves the transaction is rejected/rolled back, plus a rollback test where either write fails. It must call `assert_invariants(db)` after each transition. Until the central state-transition service exists, these are required future service tests—not tests covered by the current schema-only suite.
- Database safeguard: `Severity_Audit_History` is append-only; corrections create a new audit row. Requirement Group identity/type is locked once units exist, and Requirement Unit identity/type is locked once allocation history exists.

A completed emergency may receive a historical correction only; it remains completed and no allocation/dispatch may be triggered. The idempotency key protects against duplicate emergency creation and is unrelated to severity auditing.

## Requirement Groups

- `requirement_group_id`
- `emergency_id`
- `resource_type`
- `quantity_required`
- derived/summary status

A Requirement Group represents the required quantity for one resource type within one Emergency. Use the explicit group status enum: `PENDING`, `PARTIALLY_ALLOCATED`, `FULLY_ALLOCATED`, `COMPLETED`, and `UNFULFILLED`. Derive group status only from non-`CANCELLED` Requirement Units using this precedence: `UNFULFILLED` if any active unit is terminally `UNFULFILLED`; `COMPLETED` if every active unit is `FULFILLED`; `FULLY_ALLOCATED` if every active unit is `DISPATCHED` or `FULFILLED` and at least one is `DISPATCHED`; `PARTIALLY_ALLOCATED` if at least one active unit is `DISPATCHED` or `FULFILLED` but the preceding conditions do not apply; otherwise `PENDING`. `CANCELLED` units are retained history and excluded from `quantity_required` and status derivation. `quantity_required` must equal the number of non-`CANCELLED` child units. Do not confuse a group-level status with the parent Emergency status.

## Requirement Units

- `requirement_unit_id`
- `requirement_group_id`
- `unit_number`
- `resource_type`
- `status` (`PENDING`, `REQUESTED`, `DISPATCHED`, `FULFILLED`, `UNFULFILLED`, `CANCELLED`)
- `pending_since`
- `expires_at`
- `episode_count` (integer, initialized to `0`; incremented atomically each time a new pending episode starts)

`CANCELLED` is a terminal internal status used only when an authorized severity reduction removes a no-longer-required unit. It is distinct from `UNFULFILLED`: a cancelled unit is no longer part of the active target. Retain cancelled unit rows and all allocation/event history; clear pending timestamps. Cancelled units are excluded from group/Emergency status derivation and from `quantity_required`.

## Allocations

- `allocation_id`
- `emergency_id`
- `requirement_unit_id`
- `resource_id`
- `requested_at`
- `deadline_at`
- `response_at`
- `response_status`
- `rejection_reason`
- `distance_km`
- `status`

## Response History

- `history_id`
- `allocation_id` (unique foreign key to `Allocations`)
- `final_status` (`COMPLETED` or `FAILED`)

Dispatch/completion/return timestamps are stored only in `Allocations`; `Response_History` references the allocation and does not duplicate those timestamps.

Final history statuses:

- `COMPLETED`
- `FAILED`

## Allocation Decision Events

- `event_id`
- `emergency_id`
- `requirement_unit_id`
- `resource_id` nullable
- `event_type`
- `event_time`
- `distance_km` nullable
- `reason` nullable

## ML Feature Snapshots

- `snapshot_id`
- `requirement_unit_id` (unique foreign key; one snapshot per Requirement Unit)
- `snapshot_at`
- available resource count
- active emergency count
- higher-priority pending count
- `nearest_eligible_distance_km` (the nearest eligible resource distance known at the snapshot/decision time)
- time/day information
- relevant emergency/resource attributes

The feature snapshot represents the historical state available **at the decision/report time**.

## Required relational constraints and indexes

The executable schema must also enforce these invariants: exactly one active (`REQUESTED`/`DISPATCHED`) Allocation per resource and per Requirement Unit; a resource's `resource_type` must equal both its Requirement Unit and Requirement Group resource types on allocation insert/update; each Requirement Unit's resource type must equal its parent Requirement Group's type; immutable `Resources.resource_type`; locked `base_location_id` while a resource is `REQUESTED` or `DISPATCHED`; a fixed eleven-value `Allocation_Decision_Events.event_type` enum; valid organization-type, ownership and emergency-type enums; normalized `Emergencies.additional_details` stored as non-null text; and no pending timestamps when a Requirement Unit is `DISPATCHED`, `FULFILLED`, `UNFULFILLED` or `CANCELLED`; `quantity_required` must equal the number of non-`CANCELLED` child units. `expires_at`, when present, must be later than `pending_since`. All persisted timestamps use UTC whole-second `YYYY-MM-DDTHH:MM:SSZ` format. SQLite checks enforce the fixed shape plus year 0001–9999, month 01–12, day 01–31, hour 00–23, and minute/second 00–59; `parse_utc()` remains responsible for rejecting calendar-impossible dates such as February 30. Allocation timestamp checks require `dispatched_at` for `DISPATCHED`/`COMPLETED`/`FAILED`, `completed_at` and `returned_at` for `COMPLETED`, and `response_at` for every status except `REQUESTED`. The sweeper uses an index on `Requirement_Units(status, expires_at)`. `Allocations.emergency_id` must match the Emergency reached through its Requirement Unit and Requirement Group. A resource/Requirement Unit pair may appear only once in `Allocations`, including terminal history, because any recorded attempt permanently excludes that resource for that unit; a failed reservation race that creates no Allocation row is not recorded as an attempt. `ML_Feature_Snapshots` uses `requirement_unit_id` and permits at most one snapshot per unit. Dispatch/completion/return timestamps live only in `Allocations`, not duplicated in `Response_History`. State-service tests must call `assert_invariants(db)` after every transition, including rejection, timeout, cancellation, failure, completion, and organization deactivation. The helper checks that each Requirement Group's `quantity_required` equals its non-`CANCELLED` unit count; cross-table consistency between active Allocations and corresponding Resource/Requirement Unit statuses, checks that each `FAILED` or `COMPLETED` Allocation has exactly one matching `Allocation_Decision_Events` row and one `Response_History` row with the same final status, and validates each Emergency's ordered severity-audit chain plus its final severity. Same-second audit rows use SQLite insertion `rowid` as the tie-breaker; all severity changes for one emergency must therefore be written serially inside the same state-service transaction.



`APIContracts.md` must define these as actual SQLite constraints/indexes and test them:

- Foreign keys enabled on every database connection (`PRAGMA foreign_keys = ON`).
- `Resources.organization_id` references `Organizations`; resource base/last-reported location IDs reference `Locations` when non-null.
- `Emergencies.location_id` references `Locations`; `Requirement Groups.emergency_id` references `Emergencies`; `Requirement Units.requirement_group_id` references `Requirement Groups`.
- `Allocations.requirement_unit_id` and `Allocations.resource_id` reference their parent rows; `Allocations.emergency_id` references `Emergencies`.
- `Response History.allocation_id` references `Allocations` and is unique so one Allocation cannot create duplicate response-history rows.
- `Requirement Units` has `UNIQUE(requirement_group_id, unit_number)`.
- `Emergencies.idempotency_key` is `UNIQUE NOT NULL`.
- Enforce `UNIQUE(Allocations.requirement_unit_id, Allocations.resource_id)` across all rows: any recorded attempt permanently excludes that resource for that requirement unit. A failed reservation race that creates no Allocation row is unaffected.
- Index active allocation lookups by `resource_id` and operational `status`; index `Requirement Units(status, resource_type)` for pending-unit retrieval; index `Allocations(status, deadline_at)` for timeout scanning; index `Emergencies(reported_at, status)` for analytics; and index `Allocation Decision Events(requirement_unit_id, resource_id, event_type)` for route-failure deduplication/audit.
- Use `CHECK` constraints for enumerated states, nonnegative `episode_count`, positive requirement quantities/unit numbers, and nonnegative distance values where applicable.
- `Allocations` must have a table-level `CHECK` constraint permitting exactly these `(status, response_status)` pairs and no others: `('REQUESTED','PENDING')`, `('DISPATCHED','ACCEPTED')`, `('COMPLETED','ACCEPTED')`, `('FAILED','ACCEPTED')`, `('CLOSED','REJECTED')`, `('CLOSED','TIMEOUT')`, and `('CLOSED','CANCELLED')`.
- Enforce at most one active assignment per resource with a partial unique index on `Allocations(resource_id)` whose predicate is `WHERE status IN ('REQUESTED', 'DISPATCHED')`. This predicate is authoritative because only those operational statuses hold a resource assignment; terminal `COMPLETED`, `FAILED`, and `CLOSED` rows do not. `APIContracts.md` must contain the exact SQL definition and migration, and tests must prove that a second active assignment is rejected while historical terminal rows remain permitted.

---

# 18. Atomic Reservation and Concurrency

Resource reservation must be atomic.

Preferred SQLite approach:

**BEGIN IMMEDIATE**

Inside the short authoritative transaction, re-check:

- organization is ACTIVE;
- Requirement Unit is still eligible/PENDING;
- resource is still AVAILABLE;
- resource has no active assignment;
- candidate/resource relationship remains valid.

Then:

1. create Allocation;
2. set Resource → `REQUESTED`;
3. set Requirement Unit → `REQUESTED` while preserving `pending_since`, `expires_at`, and `episode_count` exactly as they were before reservation;
4. create `ALLOCATION_REQUESTED` event;
5. recompute/materialize the affected Requirement Group status and Emergency status;
6. commit.

If any condition fails, the transaction is rolled back and **no Allocation row is created**. A failed reservation race is not an attempt and does not permanently exclude that resource for the Requirement Unit. The coordinator records the resource only in its transient per-pass race set, continues to the next ranked candidate, and schedules/retries another coordinator pass if no candidate can be reserved. It must not spin indefinitely on the same stale candidate list.

On a successful commit, SQLite is authoritative. Reconcile the C heap/state from the committed SQLite state; never undo or pretend to roll back the committed reservation if a post-commit C update fails. The recovery rule in §19 applies.

The reservation transaction must recompute/materialize both Requirement Group and Emergency statuses, not only the Emergency status. After commit, update/rebuild derived C state; a failure in that post-commit update is logged and recovered by rebuilding from SQLite, never by reversing a committed reservation.

A normal read-then-write sequence is insufficient because two simultaneous emergencies could otherwise select the same resource.

Recommended SQLite configuration:

- WAL mode;
- 5000 ms busy timeout;
- short transactions;
- per-request/thread connections.

SQLite remains authoritative.

---

# 19. Lock Ordering

Python/C memory locking and SQLite transaction locking must not be mixed carelessly.

The coordinator `threading.RLock` is acquired **first, before validation**.

The lock sequence is:

1. Acquire coordinator RLock.
2. Validate authoritative state.
3. If candidate ranking is required, briefly acquire the C-state lock, read C-derived heap/graph/state and produce candidate ordering, then release the C-state lock.
4. Start `BEGIN IMMEDIATE`, revalidate the candidate against SQLite, reserve atomically, and commit.
5. After commit, update derived C state under the C-state lock if needed.

Lock hierarchy: coordinator RLock → C-state lock. Never reverse this order. Do not hold the C-state lock while waiting for SQLite.

SQLite is the persistent source of truth.

C data structures are derived working structures.

After restart, C structures are rebuilt from SQLite. If a post-commit update to derived C state fails, log the error with enough context to diagnose it, keep SQLite authoritative, mark/rebuild the derived C state from SQLite before relying on it again, and do not attempt to roll back an already-committed SQLite transaction.

---

# 20. Failure, Reassignment and Decision Events

If a dispatched resource fails:

**DISPATCHED → UNAVAILABLE**

The corresponding Requirement Unit **always returns to `PENDING`**. The PENDING rules then decide whether to select a candidate, continue/start a pending episode, or mark the unit `UNFULFILLED`.

Replacement search begins immediately.

No unlimited new pending-episode windows are created.

Every real candidate attempt is traceable through its Allocation record.

Meaningful decision events include:

- `ALLOCATION_REQUESTED`
- `ACCEPTED`
- `REJECTED`
- `TIMEOUT`
- `CANCELLED`
- `NO_ROUTE`
- `NO_SUITABLE_RESOURCE`
- `FAILED`
- `COMPLETED`
- `PENDING_STARTED`
- `UNFULFILLED`

Event logging is deliberately not excessive.

`NO_ROUTE` is tracked/deduplicated per `(requirement_unit_id, resource_id)`. Do not repeatedly log it for the same pair while the relevant route conditions remain unchanged; if the underlying route/node data changes and a new evaluation is justified, the pair may be evaluated again.

`NO_SUITABLE_RESOURCE` is recorded once for a completed candidate-evaluation cycle rather than once for every polling/re-evaluation.

The system therefore preserves meaningful decision history without producing unnecessary event noise.

---

# 21. Completion and Return Workflow

v1 uses one clear organization action:

**Complete Response & Return Resource**

Completion is allowed only for a currently `DISPATCHED` allocation.

The organization confirms:

1. work is complete;
2. resource has returned;
3. resource is ready again.

The server records the completion/return timestamps.

Then:

- Allocation → `COMPLETED`
- Requirement Unit → `FULFILLED`
- Resource → `AVAILABLE` if the organization remains ACTIVE
- Emergency status is recomputed

`completed_at` represents work completion.

`returned_at` represents return/readiness confirmation.

For the v1 UI, these occur as one controlled completion action and may therefore be recorded using the same server-side operation time.

There are no:

- `ON ROUTE`
- `ARRIVED`

states.

---

# 22. Central State-Transition Service

One authoritative backend state-transition service is owned by **Drishti**.

It handles critical transitions including:

- accept;
- reject;
- timeout;
- cancellation;
- failure;
- completion;
- resource state changes;
- Requirement Unit transitions;
- organization deactivation;
- reassignment;
- pending expiry;
- emergency-status recomputation.

The general flow is:

**UI/Endpoint → Authentication/Authorization → Central State Service → Current-State Validation → State Transition → SQLite → Follow-up Workflow**

Endpoint wrappers may perform early validation, but they do not replace the central business rules.

The central service prevents different endpoints from implementing contradictory state transitions.

---

## 22.1 Implementation Status at the v12 Documentation Revision

This status distinguishes the v12 schema/bootstrap additions from authentication and operational application features that remain specified but unimplemented. A schema table or contract is not evidence that the corresponding runtime workflow exists.

**Implemented and covered by the v12 package:**

- Canonical SQLite schema, including lifecycle constraints/triggers, normalized organization-email uniqueness, and the server-side `Sessions` table with token-digest, principal-shape, timestamp, expiry, and revocation constraints.
- `scripts/bootstrap_admin.py`, which validates local Admin inputs and generates the documented PBKDF2-HMAC-SHA256 password-hash configuration without writing credentials to a file or creating an Admin database row.
- Schema tests, including the new Sessions constraint/index tests, and Admin bootstrap utility unit tests.
- `services/requirement_reconciliation.py` as a transaction-safe requirement-quantity reconciliation primitive.
- Shared canonical UTC helpers in `timeutil.py` and the existing reconciliation tests.

**Specified but not yet implemented in the v12 package:**

- Flask Admin configuration loading/startup validation and Admin-versus-Organization credential verification.
- Flask login/logout handlers, session creation/lookup/revocation middleware, cookie handling, CSRF validation, Origin validation, and authentication/rate-limit tests.
- The central state-transition service, reporter submission idempotency handler, and public status lookup handler.
- The allocation coordinator, candidate selection integration, timeout processing, reassignment, and dispatch lifecycle.
- The React frontend and role-specific pages, plus full C/Python/Flask/SQLite runtime integration and end-to-end tests.

The Sessions table is a persistence foundation only. Do not claim authenticated sessions or secure login are operational until the application layer enforces the complete contract in §Administrator account provisioning and `APIContracts.md`.

**Next implementation stage:** implement and test Admin configuration validation and the shared Flask authentication/session middleware (including CSRF and logout revocation), then continue with the central state-transition service and remaining API workflows.

# Document Hierarchy and Contract Authority

The planning and implementation documents follow this hierarchy:

1. `30PointsPlanning.md` — architecture, scope, frozen rules and system-wide planning source of truth.
2. `APIContracts.md` — definitive endpoint inventory, methods, request/response schemas, validation, errors, authorization and endpoint ownership.
3. `Drishti.md` — Drishti's individual technical responsibilities.
4. `Shubhangi.md` — Shubhangi's individual technical responsibilities.
5. `Vidhi.md` — Vidhi's individual technical responsibilities.
6. `TaskOwnership.md` — cross-team ownership summary and task boundaries.

`APIContracts.md` is authoritative for exact API contracts, JSON examples, canonical enum strings, admin-list pagination/filters, idempotency normalization, and required tests. The master provides the endpoint and ownership summary; individual responsibility documents must align with both.

---

# 23. Flask API Design and Ownership

React communicates only with Flask.

React does not communicate directly with C or SQLite.

### Public / Reporter

**POST `/emergency`** — Drishti owns the backend/API; Vidhi owns the Reporter form UI and client-side integration.
Create an emergency, protect against duplicate submission, generate requirement groups/units.

**POST `/emergency/status`** — Drishti owns the backend/API; Vidhi owns the Reporter UI, frontend behavior and related frontend tests.
Verify Emergency ID + phone and return permitted reporter-facing status.

**GET `/locations`** — Drishti owns the backend/API; Vidhi owns its Reporter-form integration.
Return predefined locations for reporting.

**GET `/public/organizations`** — Shubhangi owns the backend endpoint; Vidhi owns the Registered Organizations page integration.
Return permitted registered-organization information: organization name, organization type and ownership only.

### Authentication

**POST `/auth/login`** — Drishti owns the backend/API, shared authentication/session contract, role-based post-login redirect, and frontend route guards. Shubhangi integrates the contract into the Organization Login UI; Drishti integrates it into the Admin UI.
Organization/admin authentication.

**POST `/auth/logout`** — Drishti owns the backend/API and shared authentication/session contract. Shubhangi integrates it into the Organization UI; Drishti integrates it into the Admin UI.
Session/logout handling.

### Organization — Shubhangi

**POST `/organization`**
Register organization.

**GET `/organization/profile`**

**PUT `/organization/status`**
Requests organization status change through the central state service.

**GET `/organization/requests`**

**GET `/organization/history`**

**POST `/resource`**

**GET `/resources`**

**PUT `/resource/{id}`**

**PUT `/resource/{id}/status`**
Calls the central state-transition service.

**PUT `/resource/{id}/location`**

### Allocation actions

**POST `/allocation/accept`** — Shubhangi owns the organization-facing endpoint integration; Drishti owns the central transition/coordinator logic. A late accept must follow the idempotent timeout branch specified in §12.

**POST `/allocation/reject`** — Shubhangi owns the organization-facing endpoint integration; Drishti owns the central transition/coordinator logic.

**POST `/allocation/complete`** — Shubhangi owns the organization-facing endpoint integration; Drishti owns the central transition logic.

**POST `/allocation/failure`** — Shubhangi owns the organization-facing endpoint integration; Drishti owns the central transition and reassignment logic.

### Internal Drishti workflow

Core allocation and response coordination are implemented as internal Python functions/services rather than unnecessary public HTTP endpoints.

Examples:

- `allocate_resource`
- `resource_response`
- `run_coordinator_pass`
- `start_pending_episode`
- `expire_pending_episode`
- `process_allocation_timeout`
- `transition_resource_state`
- `recompute_requirement_group_status`
- `recompute_emergency_status`
- `rebuild_c_derived_state`

### Routing — Drishti

**GET `/route`** — Drishti owns the route API and C-routing integration.

Authenticated/internal route information.

Organizations may access only routes they are authorized to see.

Reporters receive only permitted public route information if the final UI includes it.

### Admin — Drishti

Drishti owns the monitoring-only Admin endpoints and Admin frontend, including the Leaflet Map page.

**GET `/admin/emergencies`**

**GET `/admin/emergencies/{id}`**

**GET `/admin/organizations`**

**GET `/admin/resources`**

**GET `/admin/active-responses`**

**GET `/admin/history`**

**GET `/admin/analytics`**

**GET `/admin/map`**

**GET `/admin/ml`**

**POST `/admin/ml/train`**

Admin is **monitoring-only for allocation and resource operations**. Admin may inspect emergencies, organizations, resources, active responses, history, maps, analytics and ML results. An explicitly authorized emergency operator/admin may override severity only with a reason and an audit record (old severity, new severity, reason, actor, timestamp). A severity override grants no allocation-control permissions. After an emergency is completed, a severity correction is historical only: it must not reopen the emergency or trigger resource allocation/dispatch. Admin ML training is limited to the explicit model-training action.

---

# 24. Timestamps, Deadlines and Background Processing

The backend/server is authoritative for time.

All persisted timestamp columns are constrained in SQLite to canonical whole-second UTC `YYYY-MM-DDTHH:MM:SSZ` shape using `CHECK`/`GLOB` plus component-range checks (year 0001–9999, month 01–12, day 01–31, hour 00–23, minute/second 00–59). Nullable timestamp columns allow `NULL` or a value passing the same checks. Reject fractional seconds, offsets, space-separated timestamps, and arbitrary strings because lexical timestamp comparisons drive deadlines and pending episodes. SQLite component checks do not validate month-specific calendar lengths or leap days; `parse_utc()` must validate the real calendar date before application writes. All application-generated timestamps MUST be created with `utc_now()` and serialized with `format_utc()` from `timeutil.py`; incoming or externally supplied timestamp strings MUST pass `parse_utc(value)` before any database write. `utc_now()` returns timezone-aware UTC at whole-second precision, `format_utc()` converts an aware datetime to canonical UTC whole-second text and rejects naive datetimes, and `parse_utc()` strictly validates the calendar date. `GLOB` checks shape only and cannot reject impossible dates such as `2026-02-30T10:00:00Z`. No endpoint, state service, or background sweeper may hand-build timestamp strings. During development, `CREATE TRIGGER IF NOT EXISTS` does not replace an existing trigger body: delete and rebuild the disposable local SQLite database when trigger definitions change, or use a versioned migration that explicitly drops and recreates the trigger.

## Frozen timing and verification settings

Select exactly one named timing profile at startup: `NORMAL` or `DEMO`. Do not define the same constant name more than once with different values; read the applicable value from the selected profile configuration.

| Setting | `NORMAL` profile | `DEMO` profile | Scope / value |
|---|---:|---:|---|
| `ALLOCATION_RESPONSE_TIMEOUT_SECONDS` | 30 | 20 | Selected profile |
| `PENDING_EPISODE_SECONDS` | 300 | 60 | Selected profile |
| `SWEEPER_TICK_SECONDS` | — | — | Profile-independent: 1 |
| `ORG_REQUEST_POLL_SECONDS` | — | — | Profile-independent: 2 |
| `DASHBOARD_POLL_SECONDS` | — | — | Profile-independent: 5 |
| `PENDING_REEVALUATION_TICKS` | — | — | Profile-independent: 5 (safety-net reevaluation approximately every 5 seconds) |
| `MAX_PENDING_EPISODES` | — | — | Profile-independent: 2 |
| `STATUS_VERIFY_MAX_FAILURES` | — | — | Profile-independent: 10 |
| `STATUS_VERIFY_WINDOW_SECONDS` | — | — | Profile-independent: 300 |

Status-verification throttling uses the profile-independent `STATUS_VERIFY_MAX_FAILURES` and `STATUS_VERIFY_WINDOW_SECONDS` names consistently in all sections. The selected profile must be explicit at startup; the demo profile changes only the documented demonstration timings and does not silently redefine the normal profile.

The UI displays IST / Asia-Kolkata.

Definitions:

- `reported_at` = server time emergency is received
- `requested_at` = allocation request creation time
- `deadline_at` = `requested_at + ALLOCATION_RESPONSE_TIMEOUT_SECONDS`, using the selected profile's value (30 seconds in `NORMAL`; 20 seconds in `DEMO`)
- `response_at` = accept/reject/timeout time
- `dispatched_at` = accepted dispatch time
- `pending_since` = beginning of current pending episode
- `expires_at` = `pending_since + PENDING_EPISODE_SECONDS`, using the selected profile's value (300 seconds in `NORMAL`; 60 seconds in `DEMO`)
- `completed_at` = work completion time
- `returned_at` = return/readiness confirmation
- `last_updated` = resource-record update time

Allocation timeout ordering:

1. earliest `deadline_at`;
2. earlier `requested_at`;
3. lower `allocation_id`.

Pending heap ordering:

1. higher severity;
2. earlier `reported_at`;
3. lower `requirement_unit_id`.

The browser is **not authoritative** for timeout.

Exactly one sweeper loop may be active for a running application instance. Start it through a guarded application-startup function, protect startup with a process-local singleton/lock, and stop/join it during orderly shutdown. Flask's development reloader remains disabled so it cannot accidentally create a second sweeper. The documented architecture is one controlled local Flask process; multi-worker deployment is out of scope unless a cross-process scheduler/lease is added.

A standard Python threading-based sweeper runs inside the controlled local Flask process.

The sweeper:

- checks expired allocation requests;
- checks expired pending episodes;
- processes overdue deadlines after restart;
- every fifth tick (approximately every 5 seconds), re-evaluates `PENDING` units with active, unexpired episodes as a safety net when event-driven resource/candidate triggers have not resolved them;
- invokes the same central state-transition and unified pending-resolution procedure defined in §§11–12 for every such path; it must not implement a separate timeout/episode policy.

Flask's reloader is disabled.

The sweeper is for **time-driven events**, not for replacing normal state consistency.

The organization request interface uses `ORG_REQUEST_POLL_SECONDS`; operational dashboards use `DASHBOARD_POLL_SECONDS`. Their values are defined only in the Frozen timing and verification settings table above. Polling does not control timeout or state correctness.

---

# 25. Allocation Delay Metrics

The project deliberately does not use the term generic **response time**, because there is no reliable `ARRIVED` timestamp.

The primary metric is:

**Initial Allocation Delay = first dispatched_at − emergency reported_at**

for a Requirement Unit's initial allocation episode.

A separate replacement metric is:

**Replacement Allocation Delay = replacement dispatched_at − replacement episode/failure start**

These metrics must not be mixed.

The ML target is the **Requirement Unit initial allocation delay**.

Units that are never dispatched are excluded from the Random Forest target dataset.

---

# 26. AI/ML

AI/ML provides decision support and historical analysis.

It does not:

- detect emergencies;
- predict individual emergency occurrence;
- automatically dispatch resources.

## K-Means

K-Means is used for historical spatial demand analysis.

Inputs can include:

- latitude;
- longitude.

The resulting clusters are summarized using:

- emergency counts;
- emergency types;
- severity;
- resource demand.

K is presented as a configurable analysis parameter, with the UI supporting approximately `K = 3–6`.

## Random Forest Regressor

Random Forest analyzes/predicts **Requirement Unit initial allocation delay**.

Target:

**first dispatched_at − parent emergency reported_at**

Candidate features:

- emergency type;
- severity;
- locality;
- required resource type;
- available resource count;
- active emergency count;
- higher-priority pending count;
- `nearest_eligible_distance_km`;
- time of day;
- day of week.

Features that contain future/outcome information are excluded from the initial model, including:

- rejection count;
- timeout count;
- reassignment attempts;
- post-decision response timestamps;
- final allocation outcome;
- other information unavailable at the relevant decision time.

Training is enabled only after at least **100 valid target rows** are available for the initial-allocation-delay target. Below that threshold, show an insufficient-data message and do not claim model evaluation.

Evaluation:

- 80/20 train/test split where the dataset supports it;
- MAE;
- R²;
- actual-vs-predicted comparison;
- feature importance.

The 100-row threshold is a minimum eligibility gate, not a guarantee of reliable generalization. If the target has too little variation, the split is unsuitable, metrics are undefined/unstable, or the test set is too small, display that limitation and omit or clearly qualify the affected metric rather than forcing a misleading score. Report the sample count, split method, target definition, and whether rows are real, simulated, or project-generated.

Feature importance is interpreted as model association/importance, **not causation**.

For `higher_priority_pending_count`, exclude sibling Requirement Units belonging to the same parent emergency so the feature measures competing work rather than counting the same emergency's own sibling units as higher-priority external work.

Model training occurs only through the explicit Admin train action/endpoint; there is **no automatic retraining** on every new emergency, completion, or application restart. Store/report the training time and dataset/profile used for a model result.

If there is insufficient data, the system displays an **insufficient-data message** instead of fabricating metrics.

---

# 27. ML Data and Synthetic History

The project will initially lack enough real operational history.

Therefore, implement a **bounded Python synthetic-data generator** for the ML demonstration. This is a required, explicitly bounded development utility, owned by **Drishti** and due **15 October 2026**.

This utility is:

- a development/demo support tool;
- not part of the operational runtime;
- not an emergency simulator;
- not intended to model real-world emergency behavior;
- fixed/seeded where practical;
- internally consistent with the project schema.

Generated records are clearly marked, for example:

- `SIMULATED`
- `PROJECT_GENERATED`

Every analytics and ML view that can include generated records must show the selected data source and source counts (real/operational, simulated, and project-generated as applicable). Model result details must identify the training population and must not silently mix generated and operational records. Synthetic data must never be presented as real-world emergency-response evidence.

A generated formula may cause a model to learn that formula. Such results must explicitly be labeled simulated and must not be used to claim real-world validity.

Drishti owns implementation and validation of the synthetic generator, including schema consistency, fixed/seeded generation where practical, and source labeling. The generator is not part of normal request handling; generated records must remain marked `SIMULATED` or `PROJECT_GENERATED`.

---

# 28. Analytics

Analytics are owned by **Drishti**.

## KPI cards

- Total Emergencies
- Allocation Attempts
- Completed Emergencies
- Completed Responses
- Average Initial Allocation Delay
- Average Replacement Allocation Delay
- Unfulfilled Requirements

## Charts

- Emergency Trend
- Emergencies by Type
- Severity Distribution
- Emergency Status
- Resource Demand
- Allocation Outcomes
- Allocation Failures
- Initial Allocation Delay Trend
- Replacement Allocation Delay Trend
- Allocation Delay by Emergency Type

Resource Demand means resource units required by emergencies, not resources owned by organizations.

Allocation outcomes distinguish:

### Organization response

- Accepted
- Rejected
- Timeout

### Selection/availability

- No Route
- No Suitable Resource

### Operational

- Failed after dispatch

Organization activity is shown as a table, not as a ranking.

## Filters

- Today
- Last 7 Days
- Last 30 Days
- Last 90 Days
- All Time
- Custom
- Emergency Type
- Severity
- Resource Type
- Organization
- Data Source

Data Source values:

- All
- Simulated
- Project Generated
- Public, only if genuinely introduced later

Analytics must use historical state appropriate to the selected period and must not introduce future leakage.

---

# 29. User Interface

The frontend uses **one shared public website and one authentication entry point**, followed by role-based protected dashboards. It is not three unrelated websites. The common public pages share the same branding, navigation, layout rules and visual language; the dashboard content changes according to the authenticated role.

The first page opened by a visitor is the **public landing page**. Reporting an emergency and checking an existing report must remain available without login.

## 29.1 Common Public Website

The shared public navigation should provide:

- **Home** — the ResQTech landing page and primary actions.
- **About ResQTech** — purpose, project overview and a clear explanation of what the prototype does and does not do.
- **Report an Emergency** — opens the public reporter form; no account or login is required.
- **Check Emergency Status** — opens the public status-verification form requiring Emergency ID and reporter phone.
- **Emergency Guidelines** — concise guidance and limitations relevant to the prototype.
- **Registered Organizations** — public directory containing only active organizations and the approved public fields.
- **Organization Registration** — public registration form; a successful registration creates an `ACTIVE` organization under §5.
- **Login** — the single login entry for registered organization users and authorized administrators.

The landing page should make the two primary actions — **Report an Emergency** and **Check Status** — easy to find. About/project information is available from the same page without making visitors navigate through a dashboard.

The public site includes an **Organization Registration** page at `/organization/register`. Organization registration is open for the academic prototype and does not require a separate approval queue: a successfully validated registration creates the organization with `ACTIVE` status, as defined in §5. The organization can then use the shared Login page. The site must never expose administrator self-registration. This immediate activation is a controlled academic-demonstration assumption, not evidence that the organization or its ownership/contact details have been independently verified. It must not be represented as safe for a real emergency-response deployment; a production system would require an authorized verification/activation process before an organization could receive requests.

Public frontend routes (not additional API endpoints): `/`, `/about`, `/report`, `/report/confirmation`, `/status`, `/guidelines`, `/organizations`, `/organization/register`, and `/login`.

## 29.2 Reporter Flow — No Login

The reporter is a public user, not a protected dashboard role. The flow is:

**Landing Page → Report Emergency → Confirmation → Check Status (when needed)**

Reporter pages:

- Home / Landing
- Report Emergency
- Submission Confirmation
- Check Status
- Emergency Guidelines
- Registered Organizations

The reporter form submits to `POST /emergency`; it must not request or accept a client-selected severity or resource quantity. Confirmation displays the generated Emergency ID and the next steps. Status verification uses `POST /emergency/status` and requires both Emergency ID and reporter phone.

Before acceptance, reporter sees:

- Emergency ID;
- emergency status;
- requirement status;
- permitted general information.

Reporter does not see:

- candidate ranking;
- internal resource IDs;
- internal routes;
- private organization information;
- reporter contact details repeated in operational views.

The status endpoint returns only the emergency's public status, a general message, and aggregate requirement counts/statuses as defined in `APIContracts.md`. It does **not** return the handling organization's identity/contact details, assigned resource identities, internal resource IDs, or candidate information. Reporter name/phone are **not exposed to organizations through operational allocation**.

## 29.3 Shared Login and Role-Based Redirect

Organization users and authorized administrators use the same Login page and `POST /auth/login` contract. The server-authenticated role determines the destination after successful login:

- `ORGANIZATION` → that user's own Organization Dashboard;
- `ADMIN` → Admin Dashboard, subject to the specific permissions granted to that account. An emergency-operator permission, where needed, is an authorization within the admin account; it is not a third dashboard role.

The exact role/permission value returned by authentication must match the backend authorization model. Do not trust a role supplied or modified by the browser. Frontend route guards improve navigation and user experience, but **Flask must independently authorize every protected API request**.

Suggested protected frontend route families (not API endpoints): `/organization/*` and `/admin/*`. An organization user attempting to open an admin route, or an admin attempting an organization-only operational route, must not gain access merely by changing the URL. Unauthenticated users are redirected to Login for protected pages. After logout, protected pages and cached private data must no longer be accessible.

## 29.4 Organization Dashboard — Organization-Specific View

After organization login, the user sees only information belonging to that authenticated organization.

Pages / sections:

- Dashboard — incoming requests and a concise view of the organization's resource readiness.
- Requests — incoming allocation requests with the information needed to decide.
- Resources — the organization's own resources.
- Add / Edit Resource.
- Update Resource Status.
- Update Resource Location (manual reporting only; no live GPS).
- History — the organization's own past responses and allocations.
- Profile — the organization's permitted profile information.

Organization actions are limited to its own resources and requests: accept/reject requests, maintain permitted resource details/status/location, and complete or report failure for an accepted allocation according to the API contract. The central backend state-transition service validates every action.

Organizations do not see:

- reporter private information;
- other organizations' records or resources;
- candidate rankings or internal priority queues;
- administrative severity-override controls;
- system-wide allocation controls.

## 29.5 Admin Dashboard — Central Monitoring View

After authorized admin login, the user sees the system-wide command-center view. The Admin interface is primarily **monitoring and oversight**, not a manual dispatch console.

Pages / sections:

- Dashboard
- Emergencies
- Emergency Detail
- Organizations
- Resources
- Active Responses
- History
- Analytics
- Map (Leaflet; frontend and route integration owned by Drishti)
- ML

Admin can inspect system-wide operational information, active responses, history, maps, analytics and ML results. Admin does not manually select, rank, assign, accept, reject or dispatch resources. The only operational exception is a narrowly authorized and audited severity override. That permission does not grant allocation-control permissions. Only an explicitly authorized emergency operator/admin may perform the override, with a mandatory reason and audit record. A completed emergency can receive a historical correction only; it must not reopen or trigger dispatch.

## 29.6 Frontend Ownership

- **Vidhi:** Reporter-facing public pages and Reporter form/status integration; Registered Organizations page integration.
- **Shubhangi:** Organization Login integration, Organization Dashboard, resource/request/history/profile screens, organization-facing API integration, and Admin organization/resource views.
- **Drishti:** shared authentication/session and role-routing contract, Admin Dashboard and Admin emergency/active-response/history/analytics/map/ML views, and overall frontend/backend integration.

The shared landing page and common navigation must use one consistent component/layout system. Role-specific dashboards may have different information density, but they should remain part of the same ResQTech product.

## 29.7 UI Principles

The interface should be:

- modern, polished and professional;
- clear and trustworthy, especially around emergency reporting;
- consistent across the public website and protected dashboards;
- responsive, with desktop-first layouts and usable smaller-screen behavior;
- visually distinct from a generic CRUD college project;
- accessible, with readable contrast, clear labels, keyboard-usable forms and visible focus states.

Use where useful:

- cards and summary panels;
- tables and filters for operational lists;
- charts for analytics;
- Leaflet map for the Admin operational view;
- timelines and status indicators;
- confirmation dialogs for consequential actions;
- loading, error, empty and success states;
- restrained transitions that do not delay emergency-reporting actions.

The frontend must not imply live GPS, live traffic, live ETA, automatic emergency detection or real-world dispatch guarantees. No dedicated mobile application is required. The detailed colour palette, typography and visual tokens will be decided separately before visual implementation; this document intentionally does not freeze colours yet.

# 30. Technology Stack, Development, Team Responsibilities, Testing, Demo and Final Guardrails

## 30.1 Frozen Technology Stack

### Backend

- Python
- Flask
- SQLite

### C integration

- C
- GCC
- ctypes

### Frontend

- React
- TypeScript
- Vite
- plain CSS

### Data/ML

- pandas
- NumPy
- scikit-learn
- K-Means
- Random Forest Regressor

### Visualization/maps

- Recharts
- Leaflet
- OpenStreetMap

### Development

- Git
- GitHub Free
- VS Code

Explicitly excluded:

- TensorFlow
- PyTorch
- paid APIs
- paid cloud services
- paid databases
- paid ML services
- live routing APIs
- live traffic APIs
- Google Maps dependency
- SMS/email/push infrastructure
- Celery
- Redis
- production queues
- unnecessary technologies

No new technology should be introduced unless the frozen stack genuinely cannot perform a required function.

---

## 30.2 Development Phases

### Phase 1 — Core operational foundation

Build:

- database schema;
- API/data contracts;
- C heaps;
- C graph;
- Dijkstra/reverse-Dijkstra;
- Flask;
- ctypes integration;
- emergency reporting;
- Requirement Groups/Units;
- priority processing;
- candidate selection;
- atomic reservation;
- organization requests;
- accept/reject/timeout;
- reassignment;
- completion/failure;
- central state-transition service;
- core routing.

### Phase 2 — Operational robustness

Build/test:

- pending episodes;
- pending-episode deadlines;
- failure/reassignment edge cases;
- decision events;
- response history;
- operational map;
- concurrency;
- restart/rebuild;
- organization/resource edge cases;
- complete UI integration.

### Phase 3 — Analytics and ML

Build:

- KPI analytics;
- charts;
- historical analysis;
- K-Means;
- Random Forest;
- evaluation;
- ML dashboard;
- the bounded Python synthetic-data generator (Drishti; due 15 October 2026).

### Phase 4 — Final polish

Complete:

- UI refinement;
- measured performance testing;
- edge-case testing;
- demonstration;
- report;
- PPT;
- screenshots;
- viva preparation.

Core functionality must be protected from being sacrificed for visual polish.

### Dated schedule and freeze points

These are the original agreed planning dates. The status wording below is a historical snapshot recorded on 10 October 2026, not a current progress report. As of the v12 revision (8 November 2026), the team must verify actual completion and rebaseline remaining work; this document does not assume any milestone is complete or still upcoming.

| Target date | Milestone | Original status note recorded on 10 October 2026 (historical snapshot) |
|---|---|---|
| 7 October 2026 | Master planning document frozen | Target date passed; use the currently audited/patched master as the working copy and record remaining scope changes explicitly. |
| 8 October 2026 | `APIContracts.md` frozen | Target date passed without a located Library copy. Initial contract drafted on 10 October; treat the freeze as overdue until the team validates it against §17 and freezes it. |
| 10 October 2026 | Core database/C/API foundation checkpoint | Due on the snapshot date; completion was not verified in this historical note. |
| 15 October 2026 | Bounded synthetic-data generator complete (Drishti) | Upcoming at the snapshot date; schema stabilization was a prerequisite. |
| 20 October 2026 | Phase 1 core workflow checkpoint | Upcoming at the snapshot date. |
| 31 October 2026 | Phase 2 robustness and integration checkpoint | Upcoming at the snapshot date. |
| 1–10 November 2026 | Phase 3 analytics and ML checkpoint | Upcoming at the snapshot date. |
| After 10 November 2026 | Final polish, regression testing, report/PPT, demo and viva preparation | Upcoming at the snapshot date. |

The dates are checkpoints, not permission to bypass required tests or frozen contracts. If a checkpoint has passed without completion, mark it delayed and update the remaining work plan explicitly. Do not silently roll overdue work forward or describe a target as completed without evidence.

### Cut order if time is short

Protect correctness and the core end-to-end workflow first. Cut or reduce work in this order:

1. UI animation and visual polish beyond basic usability.
2. Secondary analytics charts that are not needed to explain core outcomes.
3. Nonessential Admin Map extras beyond the required route/resource/emergency display.
4. Advanced ML presentation beyond honest metrics, source labels and the required model workflow.
5. Advanced synthetic-generator options beyond a bounded, seeded, schema-consistent dataset.

Do **not** cut the synthetic-data generator itself, core database constraints, C data structures/routing, atomic reservation, central state transitions, reassignment, completion/return, privacy rules, or regression tests.

---

## 30.3 Core Logical Dependencies

Primary dependency:

**Database Schema → API/State Contracts → C/Python Integration → Central State Service → Allocation Coordinator → Core Workflow → Analytics → ML**

Routing dependency:

**OSM Data → Location/Node Mapping → C Graph → Dijkstra/Reverse-Dijkstra → Route API → Leaflet**

Frontend may begin in parallel once API/data contracts are stable.

---

## 30.4 Team Responsibilities

### Drishti — Core Decision Engine, Backend, Routing, AI/ML, Analytics and System Integration

Drishti owns:

- C priority heaps;
- type-specific pending heaps;
- graph;
- adjacency list;
- Dijkstra;
- reverse-Dijkstra;
- candidate ranking;
- tried-candidate tracking;
- reassignment;
- database schema;
- Flask core;
- authentication backend;
- authorization;
- frontend role-based post-login redirect and route guards;
- emergency backend;
- Requirement Groups/Units;
- allocation workflow;
- central state-transition service;
- coordinator;
- timeout/pending sweeper;
- failure/reassignment;
- completion workflow;
- C↔Python integration;
- SQLite concurrency;
- OSM data preparation;
- node mapping;
- route API;
- technical Leaflet integration;
- analytics;
- decision events;
- ML feature snapshots;
- bounded Python synthetic-data generator (due 15 October 2026);
- K-Means;
- Random Forest;
- ML APIs;
- Admin frontend;
- integration;
- system correctness.

### Shubhangi — Organization and Resource Management

Shubhangi owns:

- organization login;
- organization profile;
- organization dashboard;
- resource registration;
- resource editing;
- resource status;
- resource location;
- organization requests;
- accept/reject UI;
- rejection reasons;
- completion/failure UI;
- organization history;
- in-app request/status alerts;
- organization/resource APIs;
- public registered-organization backend;
- admin organization/resource views.

For critical transitions, Shubhangi's endpoints/UI call **Drishti's central state-transition service**.

Shubhangi does not need a custom C data structure unless a genuine runtime requirement is demonstrated.

### Vidhi — Public Interface and UI Support

Vidhi owns:

- public home;
- guidelines;
- Report Emergency;
- confirmation;
- Check Status;
- form validation;
- loading/error/empty states;
- reporter status display;
- public UI polish;
- frontend integration of the emergency-status endpoint;
- optional visual map assistance.

Vidhi does not own:

- core allocation backend;
- priority processing;
- coordinator;
- C allocation logic;
- Dijkstra;
- ML;
- analytics;
- Admin backend;
- OSM/location dataset;
- critical state-transition logic.

No custom C data structure is forced onto Vidhi.

### Shared

All members participate in:

- common setup;
- Git;
- API/schema discussion;
- integration;
- testing;
- debugging across module boundaries;
- documentation;
- report;
- PPT;
- demo;
- viva preparation.

Evaluator-facing documentation describes responsibilities without emphasizing internal workload hierarchy.

---

## 30.5 Integration Checkpoints

### A

**React → Flask → SQLite**

### B

**Emergency → Flask → C Priority**

### C

**Eligibility → C Ranking → Atomic Reservation → Request**

### D

**Dijkstra → Route API → Leaflet**

### E

**Reject/Timeout → Central State Service → Next Candidate**

### F

**Report → Allocation → Accept → Dispatch → Completion**

### G

**History/Events/ML Snapshots → Analytics/ML**

### H

**Dispatched Failure → Pending → Replacement**

### I

**Available Resource → Matching Type-Specific Pending Heap → Canonical Priority Comparator within that type → Request**

Core correctness must not depend on optional frontend features.

---

## 30.6 Testing and Validation

The regression suite must explicitly cover:

- all allowed Allocation response/operational status combinations and rejection of every invalid combination;
- emergency status precedence when all Requirement Units are fulfilled, when at least one is dispatched, and when one becomes terminally unfulfilled;
- rejection of an Emergency with zero Requirement Units;
- one sweeper only per process startup, including reload-disabled startup/shutdown behavior;
- foreign-key, unique, CHECK, and lookup-index constraints in the SQLite schema, including the exact seven-pair Allocation CHECK and the partial unique active-assignment index on `resource_id` for `REQUESTED`/`DISPATCHED`;
- a failed reservation race creating no Allocation row and continuing safely to another candidate/pass;
- honest ML metric handling when 100 rows exist but evaluation is unstable or undefined;
- analytics/ML source labels and source counts when generated records are included.

Testing should be broad enough to establish correctness without becoming an unmanageable test suite.

### Emergency

- valid/invalid forms;
- all emergency types;
- all severities;
- location hierarchy;
- simultaneous emergencies;
- unique IDs;
- duplicate submission/idempotency; one UUID per form instance reused for retries; integrity-error re-read returns the matching existing emergency or conflicts on payload mismatch.

### Priority

- severity ordering;
- timestamp tie-break;
- Requirement Unit tie-break;
- no incorrect interruption;
- type-specific heap behavior;
- Canonical Priority Comparator within each resource-type heap; no cross-type competition.
- every transition into PENDING enqueues exactly once, using the C `in_heap` flag for deduplication; set-aside pending units are reinserted after the pass.
- a top unit whose candidates all return `NO_ROUTE` does not block lower-priority units.

### Eligibility

- correct resource type;
- ACTIVE organization;
- AVAILABLE resource;
- valid base location;
- no active assignment;
- government/private equality;
- candidate is neither INACTIVE nor UNAVAILABLE;
- inactive organization excluded;
- correct base location and valid route required;
- no active assignment;
- permanent exclusion based on any Allocation row for the same Requirement Unit;
- shortest-distance ordering and deterministic tie-break;
- `resource_id` final tie-break.

### Allocation

- atomic duplicate-allocation protection;
- deterministic candidate ranking;
- accept;
- reject;
- timeout;
- no repeated candidate;
- accept-vs-timeout race;
- no Allocation record when reservation fails;
- idempotency race: concurrent identical submissions create one emergency, while same key with changed payload conflicts;
- late accept before sweeper completes timeout exactly once;
- late accept after sweeper returns `expired` without duplicate event, resource/unit updates or reassignment;
- duplicate submission integrity-error re-read;
- organization deactivation checks for DISPATCHED allocations before any mutation and performs all cancellation/deactivation changes in one `BEGIN IMMEDIATE` transaction;
- reservation recomputes Requirement Group and Emergency statuses atomically;
- post-commit C-state update failure logs and rebuilds derived state from SQLite without pretending the committed transaction was rolled back;
- already-closed allocation cannot be reopened or have its terminal result overwritten.

### Pending

- new pending episode;
- pending-episode expiry;
- no reset after rejection;
- no reset after timeout;
- stale heap entry handling;
- later resource availability;
- overdue episode after restart.

### Failure

- DISPATCHED → UNAVAILABLE;
- replacement;
- second dispatched failure;
- no unlimited pending windows.

### Routing

- valid route;
- no route;
- invalid node;
- one-way roads;
- reverse-Dijkstra ranking;
- route reconstruction;
- replacement route.

### Completion

- duplicate completion rejection;
- return/readiness confirmation;
- FULFILLED transition;
- resource AVAILABLE transition;
- emergency status recomputation.

### Organization

- activation;
- deactivation with only REQUESTED allocations;
- deactivation blocked by DISPATCHED allocation;
- resource cascade to INACTIVE;
- inactive organization behavior;
- inactive resource behavior.

### State management

Test every allowed and blocked transition.

### Security/access

- wrong organization cannot act on another organization's allocation;
- wrong Emergency ID, wrong phone, and mismatched ID/phone return the same generic verification error;
- status-verification throttle after 10 failures within 300 seconds per client address;
- reporter privacy;
- role boundaries;
- route access protection.

### Backend authority

- browser closed during request timeout;
- browser closed during pending episode;
- sweeper processing;
- server timestamps;
- overdue deadlines at startup;
- no dependence on client timers.

### C/Python

- C state rebuild after restart;
- ctypes memory handling/freeing;
- lock behavior;
- SQLite/C state consistency.

### Events

- meaningful event creation;
- `NO_ROUTE` deduplication;
- `NO_SUITABLE_RESOURCE` cycle behavior;
- no duplicate event spam.

### ML

- historical state correctness;
- feature leakage checks;
- sufficient/insufficient data;
- `higher_priority_pending_count` excludes sibling Requirement Units from the same emergency;
- training is blocked below 100 valid target rows;
- no automatic retraining;
- exact feature name `nearest_eligible_distance_km`;
- synthetic-data validation if generator is implemented;
- no fabricated metrics.

### UI

- loading states;
- error states;
- empty states;
- polling freshness;
- request alerts;
- status display;
- responsive behavior.

---

## 30.7 Demonstration Scenario

The final demonstration should show one coherent end-to-end scenario.

1. Seed multiple Dehradun organizations.
2. Seed government and private resources.
3. Seed predefined locations.
4. Open separate browser profiles for Reporter, Organization A, Organization B and Admin.
5. Submit multiple emergencies.
6. Show priority handling.
7. Show requirement-unit creation.
8. Show candidate filtering.
9. Show shortest road-distance ranking.
10. Show route on Leaflet.
11. Show organization request.
12. Demonstrate rejection or timeout.
13. Show next-candidate reassignment.
14. Demonstrate acceptance.
15. Show resource becoming `DISPATCHED`.
16. Demonstrate a multi-resource emergency with partial fulfillment.
17. Make another resource available.
18. Show the appropriate pending-resource heap being evaluated.
19. Show the Canonical Priority Comparator selecting the correct pending unit within the matching resource-type heap.
20. Demonstrate dispatched-resource failure.
21. Show replacement search.
22. Demonstrate completion/return/readiness.
23. Show resource becoming `AVAILABLE`.
24. Show Requirement Unit becoming `FULFILLED`.
25. Show emergency-status changes.
26. Show reporter status.
27. Show Admin active responses/history.
28. Show analytics.
29. Show ML screens if sufficient data exists.
30. Finish with architecture, limitations, and the statement that this is a **controlled academic prototype, not a production emergency-service system**.

---

## 30.8 Limitations

The project is explicitly limited by:

- selected Dehradun demonstration geography;
- predefined locations;
- offline OSM data;
- possible staleness of road data;
- manually maintained organization/resource information;
- no live GPS;
- no live traffic;
- no live ETA;
- no real organization integration;
- no real emergency-service guarantee;
- project-defined resource quantities;
- project-defined organization response deadline (30 seconds normal profile; 20 seconds demo profile);
- project-defined pending-episode window;
- initial simulated/project-generated ML history;
- limited local SQLite/single-process architecture;
- absence of production-scale infrastructure.

No real-world operational performance claim should be made.

Performance results in the final report must be **measured after implementation**, not assumed beforehand.

---

## 30.9 Final Guardrails

The following are frozen exclusions unless the project is formally reopened:

- emergency-occurrence prediction;
- automatic emergency detection;
- automatic dispatch without organization acceptance;
- live GPS;
- live movement;
- live traffic;
- live ETA;
- ON ROUTE;
- ARRIVED;
- Google Maps dependency;
- live routing APIs;
- SMS;
- email;
- push infrastructure;
- production queues;
- Celery;
- Redis;
- paid services;
- unnecessary data structures;
- unnecessary technologies;
- complex capability matching;
- real-world operational claims.

The following principles are also frozen:

**C = computational algorithms and data structures**

**SQLite = authoritative persistent state**

**Python/Flask = validation, workflow, coordination, state transitions, timers, analytics and ML**

**React = presentation and user interaction**

**C never writes directly to SQLite.**

**React never communicates directly with C or SQLite.**

**Critical state transitions use the central state-transition service.**

**The coordinator RLock is acquired before validation; candidate ranking briefly holds the C-state lock and releases it before BEGIN IMMEDIATE.**

**Admin is monitoring-only for resource allocation and dispatch.** The only operational exception is an authorized, audited severity override; it does not grant allocation-control permissions.

**Browser timers/polling are never authoritative for timeout or expiry. A late accept after an already-completed timeout is idempotent and does not repeat events or state updates.**

**Derived C state can be rebuilt from SQLite.**

**Government/private ownership does not influence candidate ranking once eligibility is satisfied.**

**FULLY_ALLOCATED does not mean COMPLETED.**

**Every actual candidate attempt must be traceable through an Allocation record. A resource with any Allocation row for the same Requirement Unit is permanently excluded for that unit; allocation history is authoritative and survives restart.**

**The configured organization-response deadline (30 seconds normal profile; 20 seconds demo profile) applies only to an allocation request; it is not a promised emergency-resolution time.**

**The pending-episode window belongs to a pending episode and is not restarted after every rejection or timeout. Rejection, timeout, and cancellation return the Requirement Unit to PENDING with the episode timestamps preserved; dispatch clears the timestamps, and a later dispatched-resource failure returns the unit to PENDING so the unified bounded episode rule applies.**

**Timestamp rule: preserve pending-episode timestamps through REQUESTED and rejection/timeout/cancellation return to PENDING; clear them on DISPATCHED, FULFILLED, and UNFULFILLED. A dispatched failure returns to PENDING and the unified episode rule applies, allowing another episode only when `episode_count < MAX_PENDING_EPISODES`.**

**Terminal Episode Rule: an expired current episode with no eligible candidate becomes UNFULFILLED, with timestamps cleared in the same transaction.**

**Pending-episode start and UNFULFILLED transitions are atomic, including event writing and status recomputation.**

**Synthetic ML data is never presented as real-world evidence.**

**Any future addition that conflicts with these rules is a scope change and must be explicitly reviewed before implementation.**

---

## Cross-section consistency rules (apply throughout this document)

- The Canonical Priority Comparator applies only within a matching resource-type heap; there is no cross-resource-type global heap or competition.
- Requirement Units start in `PENDING`; every successful transition into `PENDING` must cause deduplicated heap insertion using the C `in_heap` flag.
- Pending-episode timestamps are preserved through `REQUESTED` and rejection/timeout/cancellation returns to `PENDING`; clear them on `DISPATCHED`, `FULFILLED`, and `UNFULFILLED`. A dispatched failure returns the unit to `PENDING`, where the unified rule can start another episode only if the configured episode limit allows.
- The reservation transaction recomputes/materializes both Requirement Group and Emergency statuses.
- The Allocation table CHECK permits exactly the seven documented operational/response status pairs; a partial unique index on `Allocations(resource_id)` covers only `REQUESTED` and `DISPATCHED`.
- Requirement Group status is derived from its own Requirement Units using the same explicit precedence as the Emergency status model; `COMPLETED`/fulfilled groups are not labelled `FULLY_ALLOCATED`.
- Organization deactivation must first reject without mutations if any `DISPATCHED` allocation exists; only otherwise may one atomic transaction cancel requested allocations and deactivate the organization/resources.
- `NO_ROUTE` deduplication is keyed by `(requirement_unit_id, resource_id)`.
- SQLite remains authoritative after commit; a failed derived C-state update is logged and repaired by rebuilding C state, not by pretending to undo the committed database transaction.

---

# Final System Flow

**Reporter submits emergency**

↓

**Backend creates Emergency + Requirement Groups + Requirement Units**

↓

**Priority processing**

↓

**C type-specific pending heaps + Canonical Priority Comparator within each resource type**

↓

**Eligible resources filtered**

↓

**C calculates/ranks shortest road distances**

↓

**Python performs atomic SQLite reservation**

↓

**Allocation REQUESTED + Resource REQUESTED + Unit REQUESTED**

↓

**Organization receives request**

↙︎　　　　　　　　　↘︎
**Reject/Timeout**　　　 **Accept**
↓　　　　　　　　　　　↓
**Reassignment**　　　 **DISPATCHED**

↓　　　　　　　　　　　↓

**Next candidate**　　　 **Work completed**

　　　　　　　　　　　 ↓

　　　　　　　 **Return/readiness confirmed**

　　　　　　　　　　　 ↓

　　　　　　 **Resource AVAILABLE**

　　　　　　　　　　　 ↓

　　　　　　　 **Unit FULFILLED**

　　　　　　　　　　　 ↓

　　　　　　 **Emergency status recomputed**

　　　　　　　　　　　 ↓

　　　　　 **History + Analytics + ML data**

---

# Final Architecture Principle

The project is intentionally divided into four clear layers:

**C** performs the computationally meaningful data-structure and algorithm work.

**SQLite** is the authoritative persistent state.

**Python/Flask** coordinates the system and owns business rules, workflow, authorization, state transitions, timers, analytics and AI/ML.

**React** provides the user interface and presentation.

Whenever two modules appear to overlap, this principle determines ownership.

**This document is the implementation baseline. The planning phase is considered complete unless implementation/testing exposes a genuine contradiction or a formally requested scope change.**