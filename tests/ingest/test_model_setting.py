import json
import httpx
from ingest import sources


def test_groq_model_setting_environment_and_request_precedence(monkeypatch, tmp_path):
    configuration = tmp_path / "settings.json"
    configuration.write_text(json.dumps({"groq_model": "configured-model"}), encoding="utf-8")
    monkeypatch.setenv("SMART_CITY_SETTINGS", str(configuration))
    monkeypatch.setenv("SMART_CITY_ADAPTER_CACHE", str(tmp_path / "adapter.sqlite"))
    monkeypatch.setenv("SMART_CITY_ENABLE_GROQ", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-only-provider-key")
    monkeypatch.delenv("SMART_CITY_GROQ_MODEL", raising=False)
    seen = []
    candidate = {field: None for field in sources.FIELDS}

    class ProviderClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            seen.append(kwargs["json"]["model"])
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(candidate)}}]})

    monkeypatch.setattr(httpx, "Client", ProviderClient)
    text = "Komunikat techniczny bez danych o zmianie organizacji."
    assert sources.extract_candidate(text, use_ai=True)["model"] == "configured-model"
    monkeypatch.setenv("SMART_CITY_GROQ_MODEL", "environment-model")
    assert sources.extract_candidate(text, use_ai=True)["model"] == "environment-model"
    assert sources.extract_candidate(text, use_ai=True, model="request-model")["model"] == "request-model"
    assert seen == ["configured-model", "environment-model", "request-model"]
