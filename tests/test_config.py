from pacs import config


def test_every_stored_value_has_a_korean_label():
    stored = (
        config.ROLES
        + config.URGENCIES
        + config.STATUSES
        + config.ALGORITHMS
        + config.VERDICTS
        + config.EXAM_TYPES
    )
    assert set(stored) <= set(config.LABELS)


def test_every_urgency_has_a_target_time():
    assert set(config.TARGET_TIME) == set(config.URGENCIES)
