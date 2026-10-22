import pytest

from watcher.config import ConfigError, load_secrets

TOKEN = "123456789:" + "A" * 35


def env(**kw):
    base = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-1001234567890"}
    base.update(kw)
    return base


def test_valid():
    s = load_secrets(env())
    assert s.token == TOKEN
    assert s.chat_id == "-1001234567890"
    assert s.admin_chat_id is None


def test_valid_username_and_admin():
    s = load_secrets(env(TELEGRAM_CHAT_ID="@mychannel", TELEGRAM_ADMIN_CHAT_ID="-42"))
    assert s.chat_id == "@mychannel"
    assert s.admin_chat_id == "-42"


@pytest.mark.parametrize("bad", ["", "abc", "123:short", "x" * 40])
def test_bad_token_not_echoed(bad):
    with pytest.raises(ConfigError) as e:
        load_secrets(env(TELEGRAM_BOT_TOKEN=bad))
    if bad:
        assert bad not in str(e.value)


@pytest.mark.parametrize("bad", ["", "-", "@ab", "channel", "-12 3"])
def test_bad_chat(bad):
    with pytest.raises(ConfigError):
        load_secrets(env(TELEGRAM_CHAT_ID=bad))


def test_bad_admin():
    with pytest.raises(ConfigError):
        load_secrets(env(TELEGRAM_ADMIN_CHAT_ID="abc"))


def test_missing_token():
    with pytest.raises(ConfigError):
        load_secrets({"TELEGRAM_CHAT_ID": "-1001234567890"})


@pytest.mark.parametrize("good", ["-1234567890", "123456789", "-1001234567890"])
def test_numeric_chat_ids_accepted(good):
    assert load_secrets(env(TELEGRAM_CHAT_ID=good)).chat_id == good
