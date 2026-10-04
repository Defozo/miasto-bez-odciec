import io
import uuid

import pytest
from PIL import Image

from tests.api.test_flow import client, login, post


def image_bytes():
    data = io.BytesIO()
    metadata = Image.Exif()
    metadata[315] = "Private photographer metadata"
    Image.new("RGB", (24, 24), (15, 60, 90)).save(data, format="JPEG", exif=metadata)
    return data.getvalue()


def task(client, report_id=None):
    return post(client, "/tasks", {"title": "Pomiar ze zdjęciem terenowym", "asset_id": "crossing-y",
        "property": "width_m", "unit": "m", "method": "Pomiar taśmą", "report_id": report_id}, expected=201)


def upload(client, path, raw=None, key=None):
    return client.post("/api/v1"+path, files={"file": ("measurement.jpg", raw if raw is not None else image_bytes(), "image/jpeg")},
        headers={"Idempotency-Key": key or str(uuid.uuid4()), **({"X-CSRF-Token": client.csrf} if client.csrf else {})})


def observation(photo_id):
    return {"expected_version": 1, "value": 1.8, "unit": "m", "method": "Pomiar taśmą",
        "observed_at": "2026-10-03T09:00:00+02:00", "valid_until": "2026-10-03T13:00:00+02:00", "photo_id": photo_id}


@pytest.mark.parametrize("role", ["operator", "verifier", "admin"])
def test_staff_task_photo_is_private_sanitized_idempotent_and_attached(client, role):
    login(client)
    field_task = task(client)
    login(client, role)
    key = str(uuid.uuid4())
    raw = image_bytes()
    first = upload(client, f"/tasks/{field_task['id']}/photos", raw, key)
    assert first.status_code == 201, first.text
    photo = first.json()
    assert photo["task_id"] == field_task["id"] and photo["layer"] == "fixture"
    assert photo["metadata_removed"] and photo["status"] == "private"
    assert upload(client, f"/tasks/{field_task['id']}/photos", raw, key).json()["id"] == photo["id"]
    current = next(item for item in client.get("/api/v1/tasks").json() if item["id"] == field_task["id"])
    assert current["version"] == field_task["version"] == 1
    downloaded = client.get(f"/api/v1/photos/{photo['id']}")
    assert downloaded.status_code == 200
    assert not Image.open(io.BytesIO(downloaded.content)).getexif()
    assert b"Private photographer metadata" not in downloaded.content
    result = post(client, f"/tasks/{field_task['id']}/observe", observation(photo["id"]))
    assert result["evidence"]["photo_id"] == photo["id"]
    assert result["evidence"]["status"] == "pending_review"
    assert upload(client, f"/tasks/{field_task['id']}/photos").status_code == 409
    assert upload(client, f"/tasks/{field_task['id']}/photos", raw, key).status_code == 201
    client.cookies.clear()
    client.csrf = None
    assert client.get(f"/api/v1/photos/{photo['id']}").status_code == 401


def test_observation_rejects_missing_foreign_task_and_other_layer_photo(client):
    from services.api.db import Entity
    login(client)
    original, target = task(client), task(client)
    original_photo = upload(client, f"/tasks/{original['id']}/photos").json()
    post(client, f"/tasks/{target['id']}/observe", observation(original_photo["id"]), expected=422)
    post(client, f"/tasks/{target['id']}/observe", observation("photo-does-not-exist"), expected=422)
    post(client, f"/tasks/{target['id']}/observe", observation(original["id"]), expected=422)
    with client.test_db.begin() as db:
        db.add(Entity(id="photo-other-layer", kind="photo", layer="observed", data={"task_id": target["id"], "status": "private"}))
    wrong_layer = post(client, f"/tasks/{target['id']}/observe", observation("photo-other-layer"), expected=422)
    assert "warstwy" in wrong_layer["detail"]
    current = next(item for item in client.get("/api/v1/tasks").json() if item["id"] == target["id"])
    assert current["version"] == 1 and current["status"] == "assigned"


def test_task_can_use_only_photo_from_its_linked_report(client):
    login(client)
    report = post(client, "/reports", {"asset_id": "crossing-y", "description": "Pomiar powiązany z tym zgłoszeniem"}, expected=201)
    foreign = post(client, "/reports", {"asset_id": "crossing-y", "description": "Zdjęcie pochodzi z innego zgłoszenia"}, expected=201)
    own_photo = upload(client, f"/reports/{report['id']}/photos").json()
    foreign_photo = upload(client, f"/reports/{foreign['id']}/photos").json()
    field_task = task(client, report["id"])
    post(client, f"/tasks/{field_task['id']}/observe", observation(foreign_photo["id"]), expected=422)
    result = post(client, f"/tasks/{field_task['id']}/observe", observation(own_photo["id"]))
    assert result["evidence"]["photo_id"] == own_photo["id"]


def test_task_photo_requires_staff_role_and_enforces_upload_policy(client, monkeypatch):
    from services.api.db import User
    from services.api.security import hasher
    login(client)
    field_task = task(client)
    assert upload(client, f"/tasks/{field_task['id']}/photos", b"not-an-image").status_code == 422
    monkeypatch.setenv("SMART_CITY_UPLOAD_MAX_BYTES", "8")
    assert upload(client, f"/tasks/{field_task['id']}/photos", b"ninebytes").status_code == 413
    monkeypatch.delenv("SMART_CITY_UPLOAD_MAX_BYTES")
    client.cookies.clear()
    client.csrf = None
    assert upload(client, f"/tasks/{field_task['id']}/photos").status_code == 401
    with client.test_db.begin() as db:
        db.add(User(id="resident-test", username="resident-test", role="resident", password_hash=hasher.hash("test-only-password")))
    authenticated = client.post("/api/v1/auth/login", json={"username": "resident-test", "password": "test-only-password"})
    assert authenticated.status_code == 200
    client.csrf = authenticated.json()["csrf_token"]
    assert upload(client, f"/tasks/{field_task['id']}/photos").status_code == 403
