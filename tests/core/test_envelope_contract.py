"""Envelope wire contract: serializer shape, committed schema, budgets."""
import json

from commonwealth.core.envelope import (Coverage, Envelope, ExecutionCoverage,
                                        ExecutionProvenance,
                                        PaginationCoverage, RegistryCoverage,
                                        ResultCoverage)


def _minimal(**overrides) -> Envelope:
    fields = dict(
        data={"x": 1},
        coverage=Coverage(registry=RegistryCoverage.covered,
                          execution=ExecutionCoverage.complete,
                          pagination=PaginationCoverage.complete,
                          result=ResultCoverage.hit),
        execution=ExecutionProvenance(
            server="t", server_version="0", tool="t.t",
            tool_contract_version="1", registry_revision="r",
            request_id="rid"))
    fields.update(overrides)
    return Envelope(**fields)


def test_wire_shape_renames_execution_and_drops_empties():
    wire = _minimal().model_dump(mode="json")
    assert "_execution" in wire and "execution" not in wire
    assert "requires_user_choice" not in wire, "absent means false"
    assert "next_actions" not in wire and "resources" not in wire
    assert wire["warnings"] == [], "warnings stays present even when empty"
    cov = wire["coverage"]
    for k in ("time_range", "source_failures", "known_limitations",
              "jurisdictions_searched", "jurisdictions_unavailable"):
        assert k not in cov, f"empty coverage optional {k} must be dropped"
    for k in ("registry", "execution", "pagination", "source_claim", "result"):
        assert k in cov, f"coverage dimension {k} must always be present"


def test_requires_user_choice_survives_when_true():
    wire = _minimal(requires_user_choice=True).model_dump(mode="json")
    assert wire["requires_user_choice"] is True


def test_committed_schema_matches_models(project_root):
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    assert committed == Envelope.wire_schema(), (
        "schemas/envelope.schema.json is stale — regenerate it from "
        "Envelope.wire_schema() and review the diff as a contract change")


def test_schema_describes_the_wire_not_the_model(project_root):
    schema = Envelope.wire_schema()
    props = schema["properties"]
    assert "_execution" in props and "execution" not in props
    assert schema.get("additionalProperties") is False


def test_wire_validates_against_committed_schema(project_root):
    import jsonschema
    committed = json.loads(
        (project_root / "schemas" / "envelope.schema.json").read_text())
    jsonschema.validate(_minimal().model_dump(mode="json"), committed)


def test_data_token_estimate_counts_something():
    env = _minimal(data={"rows": ["abcd" * 100] * 10})
    estimate = env.data_token_estimate()
    assert 900 < estimate < 1300, f"~4 chars/token heuristic broke: {estimate}"
