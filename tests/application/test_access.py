from tgbotdocs.application.access import AccessGuard


def test_user_lockout_expiry_unicode_and_global_surge_without_global_pause():
    now = [0.0]
    password = "достаточно-длинный-пароль"
    guard = AccessGuard(password, clock=lambda: now[0])
    alerts = 0
    for owner in range(1, 7):
        for _ in range(5):
            result = guard.attempt(owner, "wrong")
            alerts += result.operator_alert
        assert result.locked and result.retry_after_s == 900
    assert alerts == 1
    assert guard.attempt(7, password).success
    assert not guard.attempt(1, password).success
    now[0] = 900
    assert guard.attempt(1, password).success
    guard.prune()
    assert not guard._failures


def test_success_and_new_process_have_no_persistent_password_or_attempt_record():
    guard = AccessGuard("synthetic-password")
    assert not guard.attempt(1, "wrong").success
    assert guard.attempt(1, "synthetic-password").success
    assert 1 not in guard._failures
    new = AccessGuard("changed-on-restart-password")
    assert not new.attempt(1, "synthetic-password").success
    assert new.attempt(1, "changed-on-restart-password").success
