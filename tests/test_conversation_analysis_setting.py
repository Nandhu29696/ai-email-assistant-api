from app.services import gmail_sync


def test_analysis_queue_is_skipped_when_mailbox_analysis_is_disabled(monkeypatch):
    queued = []
    monkeypatch.setattr(gmail_sync, "_schedule_analysis", queued.append)

    gmail_sync._queue_analysis_if_enabled([1, 2], False)

    assert queued == []


def test_analysis_queue_runs_when_mailbox_analysis_is_enabled(monkeypatch):
    queued = []
    monkeypatch.setattr(gmail_sync, "_schedule_analysis", queued.append)

    gmail_sync._queue_analysis_if_enabled([1, 2], True)

    assert queued == [1, 2]


def test_analysis_queue_preserves_legacy_null_as_enabled(monkeypatch):
    queued = []
    monkeypatch.setattr(gmail_sync, "_schedule_analysis", queued.append)

    gmail_sync._queue_analysis_if_enabled([1], None)

    assert queued == [1]