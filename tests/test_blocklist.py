from macmedic.blocklist import match_blocklist


def test_adobe_helper_matches():
    entry = match_blocklist("com.adobe.AdobeCreativeCloud")
    assert entry is not None
    assert entry.category == "Adobe"


def test_macromedia_matches():
    assert match_blocklist("com.macromedia.installer") is not None


def test_apple_agents_are_never_flagged():
    assert match_blocklist("com.apple.SoftwareUpdate") is None
    assert match_blocklist("com.apple.helpd") is None


def test_apple_can_be_flagged_when_requested():
    entry = match_blocklist("com.apple.AdobeUpdateHelper", apple_is_ok=False)
    assert entry is not None


def test_google_updater_matches():
    entry = match_blocklist("com.google.keystone.agent")
    assert entry is not None
    assert entry.category == "Update"


def test_backup_agent_matches():
    entry = match_blocklist("Backup and Sync")
    assert entry is not None
    assert entry.category == "Backup"


def test_telemetry_matches():
    assert match_blocklist("com.example.TelemetryAgent") is not None


def test_benign_agent_returns_none():
    assert match_blocklist("com.example.myapp.helper") is None


def test_empty_string_returns_none():
    assert match_blocklist("") is None
    assert match_blocklist(None) is None


def test_case_insensitive():
    entry = match_blocklist("COM.ADOBE.CREATIVECLOUD")
    assert entry is not None
