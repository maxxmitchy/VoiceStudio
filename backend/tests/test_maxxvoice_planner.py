from maxxvoice.orchestration import MaxxVoicePlanner


def test_plans_transcription_without_side_effects():
    plan = MaxxVoicePlanner().plan("Transcribe this interview with timestamps")

    assert [step.capability for step in plan.steps] == ["transcribe"]
    assert plan.steps[0].id == "transcribe"


def test_plans_dubbing_as_composition():
    plan = MaxxVoicePlanner().plan("Dub this video into French")

    assert [step.capability for step in plan.steps] == ["transcribe", "synthesize"]
    assert plan.warnings


def test_plans_voice_generation():
    plan = MaxxVoicePlanner().plan("Create a warm professional narrator voice")

    assert [step.capability for step in plan.steps] == ["synthesize"]


def test_unknown_intent_is_explicitly_safe():
    plan = MaxxVoicePlanner().plan("Make me something amazing")

    assert plan.steps == []
    assert plan.warnings


def test_empty_goal_is_rejected():
    try:
        MaxxVoicePlanner().plan("  ")
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("empty goals must be rejected")
