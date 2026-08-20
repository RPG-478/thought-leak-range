from types import SimpleNamespace

from thought_leak_range.arena import _is_probable_monster, _select_locked_target


def test_category_marks_custom_freedoom_monster_as_target() -> None:
    assert _is_probable_monster("MarineChainsawVzd", "Monster")


def test_custom_freedoom_name_is_kept_as_compatibility_fallback() -> None:
    assert _is_probable_monster("MarineChainsawVzd")


def test_player_category_does_not_become_a_monster() -> None:
    assert not _is_probable_monster("DoomPlayer", "Player")


def _label(object_id: int, area: float):
    return SimpleNamespace(object_id=object_id, width=area, height=1.0)


def test_target_lock_keeps_visible_enemy_even_if_another_is_much_larger() -> None:
    current = _label(3, 100.0)
    newcomer = _label(6, 400.0)

    selected, lock_id = _select_locked_target(
        [current, newcomer],
        locked_target_id=3,
    )

    assert selected is current
    assert lock_id == 3


def test_target_lock_switches_immediately_when_current_enemy_disappears() -> None:
    remaining = _label(6, 40.0)

    selected, lock_id = _select_locked_target(
        [remaining],
        locked_target_id=3,
    )

    assert selected is remaining
    assert lock_id == 6
