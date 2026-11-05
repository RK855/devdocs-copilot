"""自定义模型注册表：校验、连通性门、持久化与密钥不外泄"""
import json

import pytest

from app.config import settings
from app.services import model_registry


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    monkeypatch.setattr(settings, "MODELS_STORE", path)
    return path


BASE_PAYLOAD = {
    "api_format": "openai",
    "base_url": "https://api.example.com/v1",
    "model_id": "gpt-4o-mini",
    "display_name": "",
    "api_key": "sk-test",
    "full_url": False,
}


def test_builtin_model_is_public_and_key_never_leaks(store):
    models = model_registry.public_models()

    builtin = models[0]
    assert builtin["id"] == settings.CHAT_MODEL
    assert builtin["builtin"] is True
    assert "api_key" not in json.dumps(models)


def test_validate_rejects_missing_scheme_and_trailing_endpoint():
    with pytest.raises(model_registry.ModelRegistryError, match="http"):
        model_registry.validate_payload({**BASE_PAYLOAD, "base_url": "api.example.com"})

    with pytest.raises(model_registry.ModelRegistryError, match="/chat/completions"):
        model_registry.validate_payload({
            **BASE_PAYLOAD,
            "base_url": "https://api.example.com/v1/chat/completions",
        })


def test_full_url_strips_chat_completions_suffix(store):
    record = model_registry.validate_payload({
        **BASE_PAYLOAD,
        "base_url": "https://api.example.com/v1/chat/completions/",
        "full_url": True,
    })

    assert model_registry._base_url(record) == "https://api.example.com/v1"


def test_add_model_tests_connection_then_persists(store, monkeypatch):
    monkeypatch.setattr(model_registry, "test_connection", lambda record: 42)

    added = model_registry.add_model(BASE_PAYLOAD)

    assert added["id"].startswith("custom_")
    assert added["name"] == "gpt-4o-mini"       # 未填展示名回落到模型 ID
    saved = json.loads(store.read_text(encoding="utf-8"))["models"]
    assert saved[0]["api_key"] == "sk-test"
    assert any(m["id"] == added["id"] for m in model_registry.public_models())
    assert model_registry.is_supported(added["id"])


def test_failed_connection_does_not_write(store, monkeypatch):
    def boom(record):
        raise model_registry.ModelRegistryError("API 密钥无效")

    monkeypatch.setattr(model_registry, "test_connection", boom)

    with pytest.raises(model_registry.ModelRegistryError):
        model_registry.add_model(BASE_PAYLOAD)
    assert not store.exists()


def test_resolve_custom_returns_provider_config(store, monkeypatch):
    monkeypatch.setattr(model_registry, "test_connection", lambda record: 1)
    added = model_registry.add_model({**BASE_PAYLOAD, "display_name": "我的模型"})

    provider = model_registry.resolve(added["id"])

    assert provider == {
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "model": "gpt-4o-mini",
    }


def test_delete_custom_model_but_not_builtin(store, monkeypatch):
    monkeypatch.setattr(model_registry, "test_connection", lambda record: 1)
    added = model_registry.add_model(BASE_PAYLOAD)

    assert model_registry.delete_model(added["id"]) is True
    assert model_registry.delete_model(added["id"]) is False
    with pytest.raises(model_registry.ModelRegistryError, match="内置模型"):
        model_registry.delete_model(settings.CHAT_MODEL)


# ============ 首次使用引导 ============

SILICONFLOW_PAYLOAD = {
    **BASE_PAYLOAD,
    "base_url": "https://api.siliconflow.cn/v1",
    "model_id": "Qwen/Qwen3-8B",
    "api_key": "sk-siliconflow",
}


def test_presets_expose_two_free_models():
    keys = [p["key"] for p in model_registry.PRESET_MODELS]
    assert keys == ["siliconflow", "zhipu"]
    for preset in model_registry.PRESET_MODELS:
        assert preset["base_url"].startswith("https://")
        assert preset["model_id"]
        assert preset["display_name"]


def test_needs_setup_when_builtin_key_is_placeholder(store, monkeypatch):
    monkeypatch.setattr(settings, "AGNES_API_KEY", "your-agnes-key")
    assert model_registry.needs_setup() is True

    monkeypatch.setattr(settings, "AGNES_API_KEY", "sk-builtin")
    assert model_registry.needs_setup() is False


def test_custom_model_suppresses_setup_prompt(store, monkeypatch):
    monkeypatch.setattr(settings, "AGNES_API_KEY", "")
    monkeypatch.setattr(model_registry, "test_connection", lambda record: 1)

    model_registry.add_model(BASE_PAYLOAD)

    assert model_registry.needs_setup() is False


def test_add_siliconflow_model_reuses_key_for_embedding(store, monkeypatch):
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "")
    monkeypatch.setattr(model_registry, "test_connection", lambda record: 1)

    model_registry.add_model(SILICONFLOW_PAYLOAD)

    keys_file = store.parent / "provider_keys.json"
    keys = json.loads(keys_file.read_text(encoding="utf-8"))
    assert keys["siliconflow_api_key"] == "sk-siliconflow"
    assert settings.SILICONFLOW_API_KEY == "sk-siliconflow"
    assert model_registry.embedding_ready() is True


def test_apply_provider_keys_fills_blank_settings(store, monkeypatch):
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "your-siliconflow-key")
    (store.parent / "provider_keys.json").write_text(
        json.dumps({"siliconflow_api_key": "sk-saved"}), encoding="utf-8"
    )

    model_registry.apply_provider_keys()

    assert settings.SILICONFLOW_API_KEY == "sk-saved"
    assert model_registry.embedding_ready() is True


def test_apply_provider_keys_reuses_legacy_model_key(store, monkeypatch):
    """老安装没有 provider_keys.json：从 models.json 里回填硅基流动 Key"""
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "your-siliconflow-key")
    store.write_text(json.dumps({"models": [{
        "id": "custom_legacy",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_id": "Qwen/Qwen3-8B",
        "api_key": "sk-legacy",
        "display_name": "旧模型",
        "full_url": False,
        "api_format": "openai",
    }]}, ensure_ascii=False), encoding="utf-8")

    model_registry.apply_provider_keys()

    assert settings.SILICONFLOW_API_KEY == "sk-legacy"
    assert model_registry.embedding_ready() is True
    keys = json.loads(
        (store.parent / "provider_keys.json").read_text(encoding="utf-8")
    )
    assert keys["siliconflow_api_key"] == "sk-legacy"


def test_embedding_info_reports_read_only_models(store, monkeypatch):
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "sk-real")

    info = model_registry.embedding_info()

    assert info["model"] == settings.EMBEDDING_MODEL
    assert info["dim"] == settings.EMBEDDING_DIM
    assert info["provider"] == "硅基流动"
    assert info["rerank"] == settings.RERANK_MODEL
    assert info["vision"] == settings.VISION_MODEL
    assert info["ready"] is True
