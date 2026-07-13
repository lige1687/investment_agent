from app.agents.prompt_registry import PromptRegistry


def test_prompt_registry_loads_versioned_template():
    registry = PromptRegistry()

    template = registry.get("sector_detail")

    assert template.name == "sector_detail"
    assert template.version
    assert "版块详情解释 Agent" in template.content
    assert "{{context_json}}" in template.content
