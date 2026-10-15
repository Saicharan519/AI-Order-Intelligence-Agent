from scripts.check_secrets import forbidden_path, load_known_secrets, scan_text

FAKE_KEY = "sk-" + "a1B2" * 8  # built at runtime so this file holds no key-shaped literal


def rules(path, text, known=None):
    return [f.rule for f in scan_text(path, text, known or {})]


def test_env_file_is_forbidden():
    assert forbidden_path(".env") == "env-file"
    assert forbidden_path("config/.env.local") == "env-file"


def test_env_example_and_code_are_allowed():
    assert forbidden_path(".env.example") is None
    assert forbidden_path("src/orderintel/config.py") is None


def test_raw_dataset_is_forbidden_but_gitkeep_allowed():
    assert forbidden_path("data/raw/olist_orders_dataset.csv") == "raw-dataset"
    assert forbidden_path("data/raw/.gitkeep") is None


def test_detects_api_key_shape():
    assert "api-key-sk" in rules("notes.md", f"key is {FAKE_KEY}")


def test_detects_env_assignment_with_value():
    assert "env-assignment" in rules("x.sh", "OI_AGENT_PASSWORD=hunter2hunter2")
    assert "env-assignment" in rules("x.sh", "export DEEPSEEK_API_KEY='abc12345xyz'")


def test_ignores_empty_and_placeholder_values():
    assert rules(".env.example", "OI_AGENT_PASSWORD=") == []
    assert rules("README.md", "DEEPSEEK_API_KEY=<your-key>") == []
    assert rules("README.md", "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}") == []


def test_ignores_code_reading_env():
    assert rules("a.py", 'password = os.environ["OI_AGENT_PASSWORD"]') == []


def test_token_counts_are_not_secrets_but_tokens_are():
    # regression: a quota setting was flagged because its name contains TOKEN
    assert rules(".env.example", "LLM_MAX_TOKENS_PER_DAY=1000000") == []
    assert "env-assignment" in rules("x.sh", "GITHUB_TOKEN=abcdef123456")
    assert "env-assignment" in rules("x.sh", "GEMINI_API_KEY=abcdef123456")


def test_ignores_python_constants_with_secret_like_names():
    # regression: the scanner flagged its own constants
    assert rules("a.py", "MIN_KNOWN_SECRET_LEN = 8") == []
    assert rules("a.py", 'SECRET_NAME = r"[A-Z]*"') == []


def test_detects_known_local_secret_anywhere():
    known = {"OI_AGENT_PASSWORD": "Zq9-local-only-value"}
    found = scan_text("trace.json", '{"dsn": "...Zq9-local-only-value..."}', known)
    assert [f.rule for f in found] == ["value-of-OI_AGENT_PASSWORD"]
    assert "Zq9" not in str(found[0])  # reports never contain the value


def test_load_known_secrets_skips_short_and_non_secret(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "POSTGRES_DB=orderintel\nOI_AGENT_PASSWORD=long-enough-value\nACCESS_CODE=short\n# X=y\n",
        encoding="utf-8",
    )
    assert load_known_secrets(env) == {"OI_AGENT_PASSWORD": "long-enough-value"}
