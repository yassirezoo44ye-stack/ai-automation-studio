"""Contract tests for the Business Creator planning catalog."""
import pytest

from app.business_creator import CAPABILITIES, get_capability, list_capabilities, plan_request


def test_all_video_business_types_have_unique_ids():
    assert len(CAPABILITIES) == 9
    assert len({item.id for item in CAPABILITIES}) == len(CAPABILITIES)


def test_catalog_never_claims_unverified_capabilities_are_live():
    for capability in list_capabilities():
        assert capability["status"] == "requires_runtime_verification"
        assert capability["approval_required"] is True


def test_plan_does_not_claim_execution():
    plan = plan_request("store", "Build a storefront for handmade products")
    assert plan["engine"] == "app_builder"
    assert plan["status"] == "planned_not_executed"
    assert plan["runtime_verified"] is False
    assert plan["requires_approval_before_external_actions"] is True


@pytest.mark.parametrize("description", ["", "short", "x" * 3001])
def test_description_validation(description):
    with pytest.raises(ValueError):
        plan_request("app", description)


def test_unknown_capability_is_rejected():
    with pytest.raises(ValueError):
        get_capability("not_real")
