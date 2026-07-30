"""播放状态机.

IDLE → LOADING → PLAYING ⇄ PAUSED → STOPPING → IDLE
                ↘ ERROR
"""
from __future__ import annotations

from ..constants import PlayerState
from ..logger import get_logger

log = get_logger(__name__)

# 合法迁移
_TRANSITIONS: dict[PlayerState, set[PlayerState]] = {
    PlayerState.IDLE: {PlayerState.LOADING, PlayerState.ERROR},
    PlayerState.LOADING: {PlayerState.PLAYING, PlayerState.ERROR, PlayerState.IDLE},
    PlayerState.PLAYING: {PlayerState.PAUSED, PlayerState.STOPPING, PlayerState.LOADING, PlayerState.ERROR},
    PlayerState.PAUSED: {PlayerState.PLAYING, PlayerState.STOPPING, PlayerState.ERROR},
    PlayerState.STOPPING: {PlayerState.IDLE, PlayerState.ERROR},
    PlayerState.ERROR: {PlayerState.IDLE, PlayerState.LOADING},
}


class StateMachine:
    """播放状态机."""

    def __init__(self) -> None:
        self._state: PlayerState = PlayerState.IDLE
        self._listeners: list = []

    @property
    def state(self) -> PlayerState:
        return self._state

    def can(self, target: PlayerState) -> bool:
        return target in _TRANSITIONS.get(self._state, set())

    def transition(self, target: PlayerState) -> bool:
        if not self.can(target):
            log.warning("invalid state transition: %s -> %s", self._state, target)
            return False
        old = self._state
        self._state = target
        for cb in list(self._listeners):
            try:
                cb(old, target)
            except Exception as exc:  # noqa: BLE001
                log.warning("state listener error: %s", exc)
        return True

    def on_change(self, cb) -> None:
        self._listeners.append(cb)

    def reset(self) -> None:
        self._state = PlayerState.IDLE
