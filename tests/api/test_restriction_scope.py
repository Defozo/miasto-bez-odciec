from tests.api.test_flow import client, login, post


def test_restriction_invalidation_scope_is_validated_and_persisted(client):
    login(client)
    payload = {"asset_id": "crossing-x", "source_id": "source-fixture", "start": "2026-10-03T08:00:00+02:00",
               "end": "2026-10-03T14:00:00+02:00", "pedestrian_impact": True, "geometry_reviewed": True,
               "reason": "Sprawdzony zakres zmiany organizacji robót"}
    targeted = post(client, "/restrictions", {**payload, "invalidated_features": ["width_m", "open"]}, expected=201)
    assert targeted["invalidated_features"] == ["open", "width_m"]
    published = next(item for item in client.get("/api/v1/restrictions").json() if item["id"] == targeted["id"])
    assert published["invalidated_features"] == targeted["invalidated_features"]
    unknown = post(client, "/restrictions", payload, expected=201)
    assert unknown["invalidated_features"] is None
    unchanged_geometry = post(client, "/restrictions", {**payload, "invalidated_features": []}, expected=201)
    assert unchanged_geometry["invalidated_features"] == []
    post(client, "/restrictions", {**payload, "invalidated_features": ["not-a-feature"]}, expected=422)
    post(client, "/restrictions", {**payload, "invalidated_features": "width_m"}, expected=422)
