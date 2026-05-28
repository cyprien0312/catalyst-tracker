from unittest.mock import patch

import pytest
from catalysts.base import Alert, CatalystBase, run_cli


def test_alert_dataclass_fields():
    a = Alert(catalyst="C1", severity="HIGH", subject="s", body="b")
    assert a.catalyst == "C1" and a.severity == "HIGH"
    assert a.subject == "s" and a.body == "b"


def test_alert_severity_validated():
    with pytest.raises(ValueError):
        Alert(catalyst="C1", severity="WHATEVER", subject="s", body="b")


def test_catalystbase_subclass_must_implement_run():
    class Empty(CatalystBase):
        name = "Empty"
    with pytest.raises(TypeError):
        Empty()


def test_catalystbase_subclass_runs():
    class Mine(CatalystBase):
        name = "Mine"

        def run(self):
            return [Alert("CX", "MED", "subj", "body")]
    out = Mine().run()
    assert len(out) == 1 and out[0].subject == "subj"


def test_run_cli_passes_catalyst_tag_to_send_alert():
    class Fake(CatalystBase):
        def run(self):
            return [Alert(catalyst="c3", severity="HIGH", subject="s", body="b")]

    with patch("lib.notify.send_alert") as m:
        run_cli(lambda args: Fake(), description="Catalyst 3: openai", argv=[])
        assert m.called
        kwargs = m.call_args.kwargs
        assert kwargs.get("catalyst") == "c3" or m.call_args.args[-1] == "c3"
