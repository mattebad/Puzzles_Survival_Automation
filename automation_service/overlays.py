"""Centralized, recognition-only overlay recovery planning.

Overlay recovery returns a semantic intent plus an explicit successor contract.  It never
owns or invokes a transport; callers pass the intent to :class:`ActionExecutor`, which
performs the fresh capture, generation fencing, reservation, and single dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import SemanticActionIntent
from .screens import OverlayId, ScreenId, ScreenObservation, TargetBinding


@dataclass(frozen=True)
class OverlayPolicy:
    overlay: OverlayId | str
    semantic_action: str
    target_identity: str
    successor_screens: tuple[ScreenId | str, ...] = (ScreenId.HOME,)
    successor_overlays_absent: tuple[OverlayId | str, ...] = ()
    allowed_base_screens: tuple[ScreenId | str, ...] = ()
    action_class: str = "overlay_dismissal"

    def __post_init__(self) -> None:
        try:
            overlay = self.overlay if isinstance(self.overlay, OverlayId) else OverlayId(str(self.overlay))
        except Exception:
            overlay = OverlayId.UNKNOWN
        object.__setattr__(self, "overlay", overlay)
        if (
            not isinstance(self.semantic_action, str)
            or not self.semantic_action.strip()
            or not isinstance(self.target_identity, str)
            or not self.target_identity.strip()
        ):
            raise ValueError("overlay policy requires semantic and target identities")
        object.__setattr__(self, "successor_screens", tuple(self._screen(item) for item in self.successor_screens))
        object.__setattr__(self, "successor_overlays_absent", tuple(self._overlay(item) for item in self.successor_overlays_absent))
        object.__setattr__(self, "allowed_base_screens", tuple(self._screen(item) for item in self.allowed_base_screens))

    @staticmethod
    def _screen(value: ScreenId | str) -> ScreenId:
        try:
            return value if isinstance(value, ScreenId) else ScreenId(str(value))
        except Exception:
            return ScreenId.UNKNOWN

    @staticmethod
    def _overlay(value: OverlayId | str) -> OverlayId:
        try:
            return value if isinstance(value, OverlayId) else OverlayId(str(value))
        except Exception:
            return OverlayId.UNKNOWN


@dataclass(frozen=True)
class OverlayRecoveryPlan:
    """Semantic intent and the only acceptable successor for one overlay close."""

    intent: SemanticActionIntent
    policy: OverlayPolicy
    source: ScreenObservation
    source_target: TargetBinding

    @property
    def semantic_action(self) -> str:
        return self.intent.semantic_action

    @property
    def target_identity(self) -> str:
        return self.intent.target_identity or ""

    @property
    def action_key(self) -> str:
        return self.intent.action_key

    @property
    def successor_screens(self) -> tuple[ScreenId, ...]:
        return self.policy.successor_screens

    def accepts_successor(self, observation: ScreenObservation) -> bool:
        try:
            if not isinstance(observation, ScreenObservation) or observation.is_unknown:
                return False
            if self.policy.successor_screens and observation.screen not in self.policy.successor_screens:
                return False
            if any(observation.has_overlay(item) for item in self.policy.successor_overlays_absent):
                return False
            # The planned overlay itself must be absent.  A different recognized
            # overlay remains a blocker unless separately planned.
            if observation.has_overlay(self.policy.overlay):
                return False
            return True
        except Exception:
            # Overlay state is perception-only authority.  Any malformed policy or
            # observation must fail closed rather than authorize dismissal.
            return False


class OverlayRecoveryManager:
    """One registry for known popup/modal recovery; no dispatch method by design."""

    DEFAULT_POLICIES = (
        OverlayPolicy(
            OverlayId.VIP_RESET,
            "dismiss_vip_reset",
            "overlay:vip-reset:close",
            successor_screens=(ScreenId.HOME, ScreenId.HOME_ATLAS, ScreenId.DAILY),
            successor_overlays_absent=(OverlayId.VIP_RESET,),
        ),
        OverlayPolicy(
            OverlayId.EXIT_CONFIRMATION,
            "dismiss_exit_confirmation",
            "overlay:exit-confirmation:cancel",
            successor_screens=(ScreenId.HOME, ScreenId.HOME_ATLAS),
            successor_overlays_absent=(OverlayId.EXIT_CONFIRMATION,),
        ),
        OverlayPolicy(
            OverlayId.INFORMATION_MODAL,
            "dismiss_information_modal",
            "overlay:information:close",
            successor_screens=(ScreenId.HOME, ScreenId.HOME_ATLAS, ScreenId.DAILY),
            successor_overlays_absent=(OverlayId.INFORMATION_MODAL,),
        ),
    )

    def __init__(self, policies: Iterable[OverlayPolicy] | None = None) -> None:
        self._policies: dict[OverlayId, OverlayPolicy] = {}
        try:
            selected = tuple(policies) if policies is not None else self.DEFAULT_POLICIES
        except Exception:
            selected = ()
        for policy in selected:
            self.register(policy)

    @property
    def policies(self) -> tuple[OverlayPolicy, ...]:
        return tuple(self._policies.values())

    def register(self, policy: OverlayPolicy) -> None:
        try:
            overlay = policy.overlay
        except Exception:
            return
        self._policies[overlay] = policy
    def plan(
        self,
        observation: ScreenObservation,
        *,
        flow_id: str | None = None,
        task_id: str = "overlay-recovery",
    ) -> OverlayRecoveryPlan | None:
        """Create a semantic close intent only for a recognized current overlay."""

        try:
            if not isinstance(observation, ScreenObservation) or observation.is_unknown:
                return None
            for overlay in observation.overlays:
                policy = self._policies.get(overlay)
                if policy is None:
                    continue
                if policy.allowed_base_screens and observation.screen not in policy.allowed_base_screens:
                    continue
                target = observation.target(policy.target_identity)
                if target is None:
                    continue
                intent = SemanticActionIntent(
                    semantic_action=policy.semantic_action,
                    task_id=task_id,
                    source_state=observation.screen.value,
                    expected_postcondition=f"overlay {policy.overlay.value} absent",
                    target_identity=policy.target_identity,
                    flow_id=flow_id,
                )
                return OverlayRecoveryPlan(intent, policy, observation, target)
        except Exception:
            # Policy access, target lookup, and intent construction are all
            # untrusted recognition data; no plan means no possible dispatch.
            return None
        return None

    recover = plan

    def semantic_intent(
        self,
        observation: ScreenObservation,
        *,
        flow_id: str | None = None,
        task_id: str = "overlay-recovery",
    ) -> SemanticActionIntent | None:
        plan = self.plan(observation, flow_id=flow_id, task_id=task_id)
        return None if plan is None else plan.intent

    def plans(self, observation: ScreenObservation, *, flow_id: str | None = None, task_id: str = "overlay-recovery") -> tuple[OverlayRecoveryPlan, ...]:
        plan = self.plan(observation, flow_id=flow_id, task_id=task_id)
        return () if plan is None else (plan,)


__all__ = ["OverlayPolicy", "OverlayRecoveryManager", "OverlayRecoveryPlan"]
