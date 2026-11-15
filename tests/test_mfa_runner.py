import json
from types import SimpleNamespace

import pytest

from podcast_practice.errors import PracticeError
from podcast_practice.mfa_runner import trace_alignment
from podcast_practice.pipeline import mfa_align


def test_diagnostics_record_failed_utterance_without_changing_alignment(tmp_path, capsys):
    calls = []
    failure = tmp_path / "failure.json"
    original_error = RuntimeError("Could not align the file with the current beam size (60)")

    def align(self, utterance, **kwargs):
        calls.append((utterance, kwargs))
        if utterance.transcript == "bad":
            raise original_error
        return "unaltered alignment"

    tracked = trace_alignment(align, failure)
    valid = SimpleNamespace(transcript="good", segment=SimpleNamespace(begin=1, end=2))
    invalid = SimpleNamespace(transcript="bad", segment=SimpleNamespace(begin=3, end=3.06))
    assert tracked(None, valid, dictionary_id=7) == "unaltered alignment"
    assert not failure.exists()
    with pytest.raises(RuntimeError) as caught:
        tracked(None, invalid, dictionary_id=7)
    assert caught.value is original_error
    assert calls == [(valid, {"dictionary_id": 7}), (invalid, {"dictionary_id": 7})]
    record = json.loads(failure.read_text())
    assert record["utterance"] == 1 and record["begin"] == 3 and record["end"] == 3.06
    assert record["transcript"] == "bad" and "beam size (60)" in record["error"]
    assert "第 2 段，3.000–3.060 秒" in capsys.readouterr().out


@pytest.mark.parametrize("fresh", [True, False])
def test_pipeline_reports_current_failure_and_does_not_reuse_stale_diagnostics(tmp_path, fresh):
    failure = tmp_path / "alignment-failure.json"
    record = {"utterance": 2, "begin": 4.2, "end": 4.26, "transcript": "yes they do"}
    if not fresh:
        failure.write_text(json.dumps(record))

    def fail(command, **kwargs):
        assert command[command.index("--beam") + 1] == "60"
        assert command[command.index("--retry_beam") + 1] == "200"
        if fresh:
            failure.write_text(json.dumps(record))
        raise PracticeError("Runtime failed")

    runtime = SimpleNamespace(python=tmp_path / "python", run=fail)
    with pytest.raises(PracticeError) as error:
        mfa_align(
            runtime,
            tmp_path / "audio.wav",
            tmp_path / "text.TextGrid",
            tmp_path / "lexicon.dict",
            tmp_path / "result.json",
            tmp_path,
            clean=True,
        )
    if fresh:
        assert "第 3 段（4.200–4.260 秒）" in str(error.value)
        assert "yes they do" in str(error.value)
    else:
        assert str(error.value) == "Runtime failed"
