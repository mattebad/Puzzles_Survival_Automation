"""Persistent network-disconnect recovery episodes in the canonical state DB."""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from automation_service.contracts import FlowSpec
from automation_service.state import (
    NETWORK_RECOVERY_MAX_TIMEOUT_SECONDS,
    BotStateManager,
    NetworkRecoveryEpisode,
    NetworkRecoveryStatus,
    NetworkRecoveryStep,
    NetworkRecoveryTransportStatus,
    StateError,
    StateTransitionError,
)


SCOPE = "device:emulator-5554:com.example.game"
SOURCE_HASH = "2c20c29f9da5c0f803b2f655903e9239da5148d53e28df44503a7aaa7d48690b"
NOW = 1_794_000_000.0
DAY = 86_400.0
GAMEPLAY_TABLES = (
    "service_control", "service_lease", "clock_state", "flow_state", "runs", "actions",
)


def frame(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def history(manager: BotStateManager, scope: str = SCOPE) -> list[sqlite3.Row]:
    return manager._db.execute(
        "SELECT * FROM runtime_recovery_episodes WHERE scope_key = ? ORDER BY rowid",
        (scope,),
    ).fetchall()


def gameplay_snapshot(manager: BotStateManager) -> dict[str, list[tuple]]:
    return {
        table: [tuple(row) for row in manager._db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in GAMEPLAY_TABLES
    }


class NetworkRecoveryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.path = Path(self._folder.name) / "state.sqlite3"
        self.manager = BotStateManager(
            self.path, owner_instance_id="owner-a", process_start_token="process-a", process_id=101,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self._folder.cleanup()

    def begin(self, manager: BotStateManager | None = None, **overrides) -> NetworkRecoveryEpisode:
        arguments = {"scope_key": SCOPE, "source_frame_hash": SOURCE_HASH, "now_utc_epoch": NOW}
        arguments.update(overrides)
        return (manager or self.manager).begin_network_recovery(**arguments)

    def update(self, episode: NetworkRecoveryEpisode, status, *, now: float, **extra):
        return self.manager.update_network_recovery(
            episode.episode_id,
            expected_row_version=episode.row_version,
            status=status,
            last_frame_hash=extra.pop("last_frame_hash", SOURCE_HASH),
            reason=extra.pop("reason", "observed"),
            now_utc_epoch=now,
            **extra,
        )

    def confirm_returned(self) -> NetworkRecoveryEpisode:
        episode = self.begin()
        reserved = self.manager.reserve_network_recovery_step(
            episode.episode_id, "confirm", expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
        )
        assert reserved is not None
        returned = self.update(
            reserved, "OPEN", now=NOW + 2, step="confirm", transport_status="returned",
        )
        assert returned is not None
        return returned

    def test_begin_opens_one_scope_keyed_episode_with_fixed_deadline(self) -> None:
        episode = self.begin()
        self.assertTrue(episode.episode_id)
        self.assertEqual(episode.scope_key, SCOPE)
        self.assertIs(episode.status, NetworkRecoveryStatus.OPEN)
        self.assertEqual(episode.source_frame_hash, SOURCE_HASH)
        self.assertEqual(episode.last_frame_hash, SOURCE_HASH)
        self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (0, 0))
        self.assertIs(episode.confirm_transport_status, NetworkRecoveryTransportStatus.NOT_ATTEMPTED)
        self.assertIs(episode.relaunch_transport_status, NetworkRecoveryTransportStatus.NOT_ATTEMPTED)
        self.assertEqual(episode.started_at_utc, NOW)
        self.assertEqual(episode.deadline_at_utc, NOW + 90.0)
        self.assertIsNone(episode.next_observe_at_utc)
        self.assertEqual(episode.row_version, 0)
        self.assertEqual(self.manager.get_network_recovery(SCOPE), episode)
        self.assertIsNone(self.manager.get_network_recovery("other-scope"))

    def test_begin_validates_scope_hash_and_bounded_timeout(self) -> None:
        for bad_hash in (SOURCE_HASH.upper(), SOURCE_HASH[:-1], "g" * 64, "", None):
            with self.subTest(bad_hash=bad_hash), self.assertRaises(ValueError):
                self.begin(source_frame_hash=bad_hash)
        for bad_scope in ("", "   ", None):
            with self.subTest(bad_scope=bad_scope), self.assertRaises(ValueError):
                self.begin(scope_key=bad_scope)
        for bad_timeout in (
            0, -1.0, float("nan"), float("inf"), True,
            NETWORK_RECOVERY_MAX_TIMEOUT_SECONDS + 1, "90",
        ):
            with self.subTest(bad_timeout=bad_timeout), self.assertRaises(ValueError):
                self.begin(timeout_seconds=bad_timeout)
        for bad_now in (float("nan"), float("inf"), -1.0, None):
            with self.subTest(bad_now=bad_now), self.assertRaises(ValueError):
                self.begin(now_utc_epoch=bad_now)
        self.assertEqual(history(self.manager), [])

    def test_frame_date_and_process_changes_reuse_episode_without_fresh_budget(self) -> None:
        episode = self.begin()
        reserved = self.manager.reserve_network_recovery_step(
            episode.episode_id, NetworkRecoveryStep.CONFIRM,
            expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
        )
        assert reserved is not None
        self.assertEqual(reserved.confirm_attempts, 1)
        self.assertIs(reserved.confirm_transport_status, NetworkRecoveryTransportStatus.ATTEMPTED)
        self.assertEqual(reserved.row_version, episode.row_version + 1)

        again = self.begin(source_frame_hash=frame("new-frame"), now_utc_epoch=NOW + 2 * DAY)
        self.assertEqual(again, reserved)
        with BotStateManager(
            self.path, owner_instance_id="owner-b", process_start_token="process-b", process_id=202,
        ) as restarted:
            reopened = self.begin(
                restarted, source_frame_hash=frame("restart"), now_utc_epoch=NOW + 3 * DAY,
                timeout_seconds=NETWORK_RECOVERY_MAX_TIMEOUT_SECONDS,
            )
            self.assertEqual(reopened, reserved)
            self.assertIsNone(restarted.reserve_network_recovery_step(
                reopened.episode_id, "confirm",
                expected_row_version=reopened.row_version, now_utc_epoch=NOW + 3,
            ))
        self.assertEqual(len(history(self.manager)), 1)
        self.assertEqual(self.manager.get_network_recovery(SCOPE), reserved)

    def test_confirm_budget_is_exhausted_after_one_reservation(self) -> None:
        episode = self.confirm_returned()
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            episode.episode_id, "confirm", expected_row_version=episode.row_version, now_utc_epoch=NOW + 3,
        ))
        self.assertEqual(self.manager.get_network_recovery(SCOPE), episode)
        with self.assertRaises(StateTransitionError):
            self.manager.reserve_network_recovery_step(
                episode.episode_id, "tap", expected_row_version=episode.row_version, now_utc_epoch=NOW + 3,
            )

    def test_competing_cas_has_one_winner(self) -> None:
        episode = self.begin()
        with BotStateManager(
            self.path, owner_instance_id="owner-b", process_start_token="process-b", process_id=202,
        ) as competitor:
            stale = competitor.get_network_recovery(SCOPE)
            self.assertEqual(stale, episode)
            winner = self.manager.reserve_network_recovery_step(
                episode.episode_id, "confirm", expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
            )
            self.assertIsNotNone(winner)
            self.assertIsNone(competitor.reserve_network_recovery_step(
                stale.episode_id, "confirm", expected_row_version=stale.row_version, now_utc_epoch=NOW + 1,
            ))
            self.assertIsNone(competitor.update_network_recovery(
                stale.episode_id, expected_row_version=stale.row_version, status="RECOVERED",
                last_frame_hash=frame("connected"), reason="connected", now_utc_epoch=NOW + 1,
            ))
            self.assertEqual(competitor.get_network_recovery(SCOPE), winner)
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            "netrec-missing", "confirm", expected_row_version=0, now_utc_epoch=NOW + 1,
        ))

    def test_deferral_is_finite_and_never_renews_the_original_deadline(self) -> None:
        episode = self.begin(timeout_seconds=60.0)
        with self.assertRaises(ValueError):
            self.update(episode, "DEFERRED", now=NOW + 1)
        for bad in (NOW + 1, NOW, float("inf"), float("nan")):
            with self.subTest(next_observe=bad), self.assertRaises(ValueError):
                self.update(episode, "DEFERRED", now=NOW + 1, next_observe_at_utc=bad)
        with self.assertRaises(ValueError):
            self.update(episode, "MANUAL_REQUIRED", now=NOW + 1, next_observe_at_utc=NOW + 5)
        self.assertIsNone(
            self.update(episode, "DEFERRED", now=NOW + 1, next_observe_at_utc=NOW + 61)
        )

        deferred = self.update(
            episode, NetworkRecoveryStatus.DEFERRED, now=NOW + 1,
            next_observe_at_utc=NOW + 10, last_frame_hash=frame("still-disconnected"),
        )
        assert deferred is not None
        self.assertIs(deferred.status, NetworkRecoveryStatus.DEFERRED)
        self.assertEqual(deferred.deadline_at_utc, episode.deadline_at_utc)
        self.assertEqual(deferred.source_frame_hash, SOURCE_HASH)
        self.assertEqual(deferred.last_frame_hash, frame("still-disconnected"))
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            deferred.episode_id, "confirm", expected_row_version=deferred.row_version, now_utc_epoch=NOW + 9,
        ))
        reserved = self.manager.reserve_network_recovery_step(
            deferred.episode_id, "confirm", expected_row_version=deferred.row_version, now_utc_epoch=NOW + 10,
        )
        assert reserved is not None
        self.assertIs(reserved.status, NetworkRecoveryStatus.OPEN)
        self.assertEqual(reserved.deadline_at_utc, episode.deadline_at_utc)

        returned = self.update(
            reserved, "DEFERRED", now=NOW + 11, next_observe_at_utc=NOW + 59,
            step="confirm", transport_status="returned",
        )
        assert returned is not None
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            returned.episode_id, "relaunch", expected_row_version=returned.row_version, now_utc_epoch=NOW + 60,
        ))
        self.assertIsNone(self.update(returned, "DEFERRED", now=NOW + 60, next_observe_at_utc=NOW + 61))
        self.assertEqual(self.begin(now_utc_epoch=NOW + 120), returned)

    def test_reservation_rejects_clock_rollback(self) -> None:
        episode = self.begin()
        observed = self.update(episode, "OPEN", now=NOW + 5)
        assert observed is not None
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            observed.episode_id, "confirm", expected_row_version=observed.row_version, now_utc_epoch=NOW + 4,
        ))
        self.assertIsNone(self.update(observed, "OPEN", now=NOW + 4))

    def test_uncertain_confirm_forbids_relaunch(self) -> None:
        episode = self.begin()
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            episode.episode_id, "relaunch", expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
        ))
        reserved = self.manager.reserve_network_recovery_step(
            episode.episode_id, "confirm", expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
        )
        assert reserved is not None
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            reserved.episode_id, "relaunch", expected_row_version=reserved.row_version, now_utc_epoch=NOW + 2,
        ))
        unknown = self.update(reserved, "OPEN", now=NOW + 2, step="confirm", transport_status="unknown")
        assert unknown is not None
        self.assertIs(unknown.confirm_transport_status, NetworkRecoveryTransportStatus.UNKNOWN)
        self.assertEqual(unknown.confirm_attempts, 1)
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            unknown.episode_id, "relaunch", expected_row_version=unknown.row_version, now_utc_epoch=NOW + 3,
        ))
        self.assertIsNone(
            self.update(unknown, "OPEN", now=NOW + 3, step="confirm", transport_status="returned")
        )
        self.assertEqual(self.manager.get_network_recovery(SCOPE), unknown)
        with self.assertRaises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(self.path)) as raw:
                raw.execute(
                    """UPDATE runtime_recovery_episodes
                       SET relaunch_attempts = 1, relaunch_transport_status = 'attempted'
                       WHERE episode_id = ?""",
                    (unknown.episode_id,),
                )

    def test_returned_confirm_permits_exactly_one_relaunch(self) -> None:
        returned = self.confirm_returned()
        relaunch = self.manager.reserve_network_recovery_step(
            returned.episode_id, NetworkRecoveryStep.RELAUNCH,
            expected_row_version=returned.row_version, now_utc_epoch=NOW + 3,
        )
        assert relaunch is not None
        self.assertEqual((relaunch.confirm_attempts, relaunch.relaunch_attempts), (1, 1))
        self.assertIs(relaunch.relaunch_transport_status, NetworkRecoveryTransportStatus.ATTEMPTED)
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            relaunch.episode_id, "relaunch", expected_row_version=relaunch.row_version, now_utc_epoch=NOW + 4,
        ))
        finished = self.update(relaunch, "OPEN", now=NOW + 4, step="relaunch", transport_status="returned")
        assert finished is not None
        self.assertEqual((finished.confirm_attempts, finished.relaunch_attempts), (1, 1))
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            finished.episode_id, "relaunch", expected_row_version=finished.row_version, now_utc_epoch=NOW + 5,
        ))

    def test_transport_status_moves_only_from_attempted(self) -> None:
        returned = self.confirm_returned()
        with self.assertRaises(ValueError):
            self.update(returned, "OPEN", now=NOW + 3, step="confirm")
        with self.assertRaises(ValueError):
            self.update(returned, "OPEN", now=NOW + 3, transport_status="returned")
        with self.assertRaises(StateTransitionError):
            self.update(returned, "OPEN", now=NOW + 3, step="confirm", transport_status="lost")
        with self.assertRaises(StateTransitionError):
            self.update(returned, "CONNECTED", now=NOW + 3)
        self.assertIsNone(
            self.update(returned, "OPEN", now=NOW + 3, step="confirm", transport_status="attempted")
        )
        self.assertIsNone(
            self.update(returned, "OPEN", now=NOW + 3, step="confirm", transport_status="not_attempted")
        )
        self.assertIsNone(
            self.update(returned, "OPEN", now=NOW + 3, step="confirm", transport_status="unknown")
        )
        self.assertIsNone(
            self.update(returned, "OPEN", now=NOW + 3, step="relaunch", transport_status="returned")
        )
        self.assertEqual(self.manager.get_network_recovery(SCOPE), returned)

    def test_manual_required_blocks_reservation_until_recovered(self) -> None:
        episode = self.begin()
        manual = self.update(episode, "MANUAL_REQUIRED", now=NOW + 1, reason="unknown_dialog")
        assert manual is not None
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            manual.episode_id, "confirm", expected_row_version=manual.row_version, now_utc_epoch=NOW + 2,
        ))
        self.assertIsNone(self.update(manual, "OPEN", now=NOW + 2))
        self.assertIsNone(self.update(manual, "DEFERRED", now=NOW + 2, next_observe_at_utc=NOW + 5))
        self.assertEqual(self.begin(now_utc_epoch=NOW + DAY), manual)
        still_manual = self.update(manual, "MANUAL_REQUIRED", now=NOW + 3, reason="account_dialog")
        assert still_manual is not None
        self.assertEqual(still_manual.reason, "account_dialog")
        self.assertEqual(still_manual.confirm_attempts, 0)
        recovered = self.update(still_manual, "RECOVERED", now=NOW + 4, reason="operator_resolved")
        assert recovered is not None
        self.assertIs(recovered.status, NetworkRecoveryStatus.RECOVERED)

    def test_recovered_is_terminal_and_new_episode_keeps_history(self) -> None:
        episode = self.begin()
        reserved = self.manager.reserve_network_recovery_step(
            episode.episode_id, "confirm", expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
        )
        assert reserved is not None
        recovered = self.update(
            reserved, "RECOVERED", now=NOW + 2,
            last_frame_hash=frame("connected"), reason="connected_observed",
        )
        assert recovered is not None
        self.assertIs(recovered.status, NetworkRecoveryStatus.RECOVERED)
        self.assertIs(recovered.confirm_transport_status, NetworkRecoveryTransportStatus.ATTEMPTED)
        self.assertIs(recovered.relaunch_transport_status, NetworkRecoveryTransportStatus.NOT_ATTEMPTED)
        self.assertIsNone(recovered.next_observe_at_utc)
        self.assertEqual(self.manager.get_network_recovery(SCOPE), recovered)
        self.assertIsNone(
            self.update(recovered, "RECOVERED", now=NOW + 3, step="confirm", transport_status="returned")
        )
        self.assertIsNone(self.update(recovered, "OPEN", now=NOW + 3))
        self.assertIsNone(self.manager.reserve_network_recovery_step(
            recovered.episode_id, "relaunch", expected_row_version=recovered.row_version, now_utc_epoch=NOW + 3,
        ))

        fresh = self.begin(source_frame_hash=frame("second-disconnect"), now_utc_epoch=NOW + 10)
        self.assertNotEqual(fresh.episode_id, recovered.episode_id)
        self.assertIs(fresh.status, NetworkRecoveryStatus.OPEN)
        self.assertEqual((fresh.confirm_attempts, fresh.relaunch_attempts), (0, 0))
        self.assertEqual(fresh.deadline_at_utc, NOW + 100)
        self.assertEqual(self.manager.get_network_recovery(SCOPE), fresh)
        rows = history(self.manager)
        self.assertEqual([row["episode_id"] for row in rows], [recovered.episode_id, fresh.episode_id])
        self.assertEqual(rows[0]["status"], "RECOVERED")
        self.assertEqual(rows[0]["confirm_attempts"], 1)
        self.assertEqual(rows[0]["row_version"], recovered.row_version)
        self.assertEqual(self.begin(now_utc_epoch=NOW + 11), fresh)
        with self.assertRaises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(self.path)) as raw:
                raw.execute(
                    """INSERT INTO runtime_recovery_episodes
                       SELECT 'netrec-duplicate', scope_key, status, source_frame_hash,
                              confirm_attempts, relaunch_attempts, confirm_transport_status,
                              relaunch_transport_status, started_at_utc, deadline_at_utc,
                              next_observe_at_utc, updated_at_utc, last_frame_hash, reason,
                              row_version
                       FROM runtime_recovery_episodes WHERE episode_id = ?""",
                    (fresh.episode_id,),
                )

    def test_scopes_are_independent(self) -> None:
        first = self.begin()
        second = self.begin(scope_key="device:other")
        self.assertNotEqual(first.episode_id, second.episode_id)
        self.assertEqual(self.manager.get_network_recovery("device:other"), second)

    def test_episode_lifecycle_leaves_gameplay_controls_and_counters_unchanged(self) -> None:
        self.manager.initialize_flows([
            FlowSpec("FLOW-TEST", default_enabled=False, priority=1, cadence="manual",
                     max_wait_seconds=90.0, max_attempts=2),
        ])
        before = gameplay_snapshot(self.manager)
        returned = self.confirm_returned()
        relaunch = self.manager.reserve_network_recovery_step(
            returned.episode_id, "relaunch", expected_row_version=returned.row_version, now_utc_epoch=NOW + 3,
        )
        assert relaunch is not None
        unknown = self.update(relaunch, "MANUAL_REQUIRED", now=NOW + 4, step="relaunch", transport_status="unknown")
        assert unknown is not None
        self.assertIsNotNone(self.update(unknown, "RECOVERED", now=NOW + 5))
        self.assertEqual(gameplay_snapshot(self.manager), before)
        self.assertFalse(self.manager.get_service_enabled())
        self.assertFalse(self.manager.get_flow_enabled("FLOW-TEST"))

    def test_read_only_prior_schema_returns_none_without_mutation(self) -> None:
        self.manager.close()
        with closing(sqlite3.connect(self.path)) as raw:
            raw.execute("DROP TABLE runtime_recovery_episodes")
            raw.execute("PRAGMA journal_mode = DELETE")
            raw.commit()
        before = self.path.read_bytes()
        with BotStateManager(self.path, owner_instance_id="readonly", read_only=True) as readonly:
            self.assertIsNone(readonly.get_network_recovery(SCOPE))
            with self.assertRaises(StateError):
                self.begin(readonly)
            with self.assertRaises(StateError):
                readonly.reserve_network_recovery_step(
                    "netrec-x", "confirm", expected_row_version=0, now_utc_epoch=NOW,
                )
            with self.assertRaises(StateError):
                readonly.update_network_recovery(
                    "netrec-x", expected_row_version=0, status="RECOVERED",
                    last_frame_hash=SOURCE_HASH, reason="connected", now_utc_epoch=NOW,
                )
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as raw:
            self.assertIsNone(raw.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'runtime_recovery_episodes'"
            ).fetchone())
        self.manager = BotStateManager(self.path, owner_instance_id="writer")
        self.assertIsNone(self.manager.get_network_recovery(SCOPE))
        self.assertIs(self.begin().status, NetworkRecoveryStatus.OPEN)

    def test_read_only_current_schema_reads_but_cannot_mutate(self) -> None:
        episode = self.begin()
        with BotStateManager(self.path, owner_instance_id="readonly", read_only=True) as readonly:
            self.assertEqual(readonly.get_network_recovery(SCOPE), episode)
            with self.assertRaises(StateError):
                readonly.reserve_network_recovery_step(
                    episode.episode_id, "confirm",
                    expected_row_version=episode.row_version, now_utc_epoch=NOW + 1,
                )
        self.assertEqual(self.manager.get_network_recovery(SCOPE), episode)


if __name__ == "__main__":
    unittest.main()
