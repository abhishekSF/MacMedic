from macmedic import trends


def test_record_and_summary(tmp_path):
    trends.configure_for_tests(str(tmp_path / "trends.db"))
    trends.record(60.0, 80.0, 650, 31.0, 62.0, 3000.0)
    trends.record(55.0, 80.0, 650, 32.0, 63.0, 3100.0)
    summary = trends.summary(days=30)
    assert summary.samples == 2
    assert summary.percent_min == 55.0
    assert summary.percent_max == 60.0
    assert summary.temp_min_c == 31.0
    assert summary.temp_max_c == 32.0


def test_ignore_none_percent(tmp_path):
    trends.configure_for_tests(str(tmp_path / "trends.db"))
    trends.record(None, None, None, None, None, None)
    assert trends.summary(days=30).samples == 0


def test_report_no_data(tmp_path):
    trends.configure_for_tests(str(tmp_path / "trends.db"))
    report = trends.trend_report()
    assert "No trend data yet" in report
