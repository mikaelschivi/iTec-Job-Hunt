import json

import pytest

from watcher import state


def sample():
    s = state.empty()
    s["listings"]["12"] = state.entry("Título – ç", "open", "2026-10-22T00:00:00+00:00", None, "silent")
    return s


def test_round_trip_no_tmp_left(tmp_path):
    p = str(tmp_path / "state.json")
    state.save(p, sample())
    assert state.load(p) == sample()
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


def test_save_overwrites(tmp_path):
    p = str(tmp_path / "state.json")
    state.save(p, sample())
    s = sample()
    s["listings"]["13"] = state.entry("x", "done", "t", "t", "full")
    state.save(p, s)
    assert set(state.load(p)["listings"]) == {"12", "13"}


def test_missing_is_none(tmp_path):
    assert state.load(str(tmp_path / "nope.json")) is None


def test_empty_listings_valid(tmp_path):
    p = str(tmp_path / "s.json")
    state.save(p, state.empty())
    assert state.load(p) == state.empty()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "",
        "[]",
        json.dumps({"version": 2, "listings": {}}),
        json.dumps({"listings": {}}),
        json.dumps({"version": 1, "listings": []}),
        json.dumps({"version": 1, "listings": {"x": {}}}),
        json.dumps({"version": 1, "listings": {"1": {"title": "t", "status": "bogus",
                    "first_seen": "t", "notified_at": None, "detail": "full"}}}),
    ],
)
def test_corrupt_raises(tmp_path, content):
    p = tmp_path / "s.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(state.StateError):
        state.load(str(p))
