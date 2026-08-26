from macmedic.monitors import eol_fitness_score, sensors_report


def test_eol_fitness_score_bounds():
    score, verdict = eol_fitness_score()
    assert 0 <= score <= 100
    assert isinstance(verdict, str) and verdict


def test_sensors_report_runs():
    report = sensors_report()
    assert isinstance(report, str)
    assert report
