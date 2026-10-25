from app.redact import redact


def test_url_credentials():
    assert "hunter2" not in redact("connecting to postgres://admin:hunter2@db:5432/app")


def test_key_value_secrets():
    out = redact("DB_PASSWORD=supersecret api_key: abc123 token='xyz'")
    assert "supersecret" not in out and "abc123" not in out and "xyz" not in out


def test_bearer_and_jwt():
    out = redact("Authorization: Bearer abc.def.ghi eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    assert "abc.def.ghi" not in out and "eyJhbGci" not in out


def test_cloud_keys_and_email():
    out = redact("AKIAIOSFODNN7EXAMPLE sk-or-v1-abcdefghijklmnop1234 bob@example.com")
    assert "AKIAIOSFODNN7EXAMPLE" not in out and "abcdefghijklmnop1234" not in out and "bob@example.com" not in out


def test_normal_text_untouched():
    s = "Back-off restarting failed container app in pod payments-7d9f"
    assert redact(s) == s
