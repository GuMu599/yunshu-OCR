import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_oom_policy_retries_with_one_page_and_lower_working_dpi():
    from resource_limits import ResourcePolicy

    retry = ResourcePolicy().after_oom(batch_pages=2, working_dpi=300)

    assert retry.batch_pages == 1
    assert retry.working_dpi == 220
    assert retry.final_asset_dpi == 300


def test_default_policy_stays_bounded_by_configured_hard_limits(monkeypatch):
    from resource_limits import ResourcePolicy

    monkeypatch.setattr("resource_limits.physical_memory_bytes", lambda: 32 * 1024**3)
    policy = ResourcePolicy.from_system()

    assert policy.soft_ram_bytes == 8 * 1024**3
    assert policy.hard_ram_bytes == 10 * 1024**3
    assert policy.batch_pages == 2
