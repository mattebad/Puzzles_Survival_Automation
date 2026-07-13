from __future__ import annotations
import json, tempfile, unittest
from dataclasses import replace
from pathlib import Path
import cv2
from safe_action_core import ActionClass, CentralPolicy, Observation, PolicyRequest, SafetyStore, TransportResult
from safe_action_core.navigation import NavigationRunner, NavigationStatus, NavigationStep
from scripts.navigation_recognition import DAILY_SELECTED_TAB_ROI, H_QUEST_ROI, recognize_daily_selected, recognize_home_quest
ROOT=Path(__file__).resolve().parents[1]
E=ROOT/"evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape"
SOURCE=E/"live-nav-home-quest-promo-001-source.png"
IMMEDIATE=E/"live-nav-home-quest-promo-001-immediate-before-1.png"
REFERENCE=ROOT/"evidence/sessions/20260712-m6-dq-bootstrap/assets/home-base-settled.png"
DAILY_REFERENCE=ROOT/"evidence/sessions/20260712-m6-dq-bootstrap/assets/daily-quest-settled.png"
MAIN_REFERENCE=ROOT/"evidence/sessions/20260712-m6-dq-bootstrap/assets/quest-main-settled.png"
LIVE_MAIN=ROOT/"evidence/sessions/20260712-mvp-quest-to-claim/daily-postreset-observation-20260713.png"
PROFILE=json.loads((ROOT/"runtime-profile/manifest.json").read_text())["profile_id"]
def obs(**changes):
    base=Observation(frame_sha256="a"*64,capture_completed_monotonic=1000.0,runtime_profile_id=PROFILE,width=800,height=1280,valid_png=True,corrupt=False,black=False,source_state="HOME_BASE",overlay_state="none_observed",target_identity="home-quest-entry",target_roi=H_QUEST_ROI,recognized=True,consequence="navigate_zero_cost",cost_type="none",cost_amount=0,quantity=1,expected_postcondition="QUEST")
    return replace(base,**changes)
def req(o):
    return PolicyRequest(action_id="nav-1",action_key="nav:home-quest",task_id="MVP-QUEST-TO-CLAIM",task_mode="supervised_validation",semantic_action="HOME_TO_QUEST",expected_runtime_profile_id=PROFILE,observation=o,monotonic_now=1000.1,observation_max_age_seconds=3,dispatch_max_age_seconds=2,lease_owner="nav",lease_valid=True,unresolved_action=False,duplicate_action_key=False,action_class=ActionClass.NAVIGATION_ONLY)
class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=cv2.imread(str(REFERENCE)); cls.a=cv2.imread(str(SOURCE)); cls.b=cv2.imread(str(IMMEDIATE))
    def test_retained_frames_are_same_home_and_target(self):
        for frame in (self.a,self.b):
            r=recognize_home_quest(frame,self.ref)
            self.assertTrue(r.recognized); self.assertEqual(r.state,"HOME_BASE"); self.assertEqual(r.target_identity,"home-quest-entry")
        self.assertGreaterEqual(recognize_home_quest(self.b,self.ref).target_score,.99)
    def test_unrelated_animation_is_ignored(self):
        changed=self.a.copy(); changed[200:1000,420:780]=0
        self.assertTrue(recognize_home_quest(changed,self.ref).recognized)
    def test_overlay_danger_and_missing_target_deny(self):
        self.assertFalse(recognize_home_quest(self.a,self.ref,overlay_intersects=True).recognized)
        self.assertFalse(recognize_home_quest(self.a,self.ref,dangerous_intersects=True).recognized)
        changed=self.a.copy(); changed[1130:1280,250:410]=0
        self.assertFalse(recognize_home_quest(changed,self.ref).recognized)
class DailyTabRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily=cv2.imread(str(DAILY_REFERENCE)); cls.main=cv2.imread(str(MAIN_REFERENCE)); cls.live_main=cv2.imread(str(LIVE_MAIN))
    def test_selected_daily_fixture_is_positive(self):
        result=recognize_daily_selected(self.daily,self.daily,self.main)
        self.assertTrue(result.recognized); self.assertEqual(result.state,"DAILY_QUEST")
        self.assertEqual(result.target_roi,DAILY_SELECTED_TAB_ROI)
    def test_main_fixture_and_retained_live_frame_are_negative(self):
        for frame in (self.main,self.live_main):
            result=recognize_daily_selected(frame,self.daily,self.main)
            self.assertFalse(result.recognized); self.assertEqual(result.state,"UNKNOWN")
    def test_unrelated_animation_outside_selected_roi_is_ignored(self):
        changed=self.daily.copy(); changed[300:1000,0:800]=0
        self.assertTrue(recognize_daily_selected(changed,self.daily,self.main).recognized)
    def test_changed_selected_roi_denies_daily(self):
        changed=self.daily.copy(); changed[80:200,260:540]=self.main[80:200,260:540]
        self.assertFalse(recognize_daily_selected(changed,self.daily,self.main).recognized)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=SafetyStore(Path(self.tmp.name)/"n.sqlite3"); self.store.acquire_lease("nav",1000,30); self.clock=[1000.1]
    def tearDown(self): self.store.close(); self.tmp.cleanup()
    def runner(self): return NavigationRunner(self.store,CentralPolicy(),"nav",lambda:self.clock[0])
    def test_exactly_one_dispatch(self):
        calls=[]; successor=obs(frame_sha256="c"*64,capture_completed_monotonic=1000.3,source_state="QUEST",target_identity=None,target_roi=None)
        result=self.runner().run(NavigationStep("home-quest","HOME_BASE","HOME_TO_QUEST",("QUEST",)),req(obs()),lambda:obs(frame_sha256="b"*64,capture_completed_monotonic=1000.05),lambda roi:(calls.append(roi) or TransportResult(True,"OK")),lambda:[successor])
        self.assertEqual(result.status,NavigationStatus.REACHED_SUCCESSOR); self.assertEqual(len(calls),1); self.assertFalse(self.store.has_action_block())
    def test_safe_no_effect_allows_one_retry(self):
        calls=[]; posts=iter([[obs(capture_completed_monotonic=1000.3)],[obs(capture_completed_monotonic=1000.4,source_state="QUEST",target_identity=None,target_roi=None)]])
        result=self.runner().run(NavigationStep("home-quest","HOME_BASE","HOME_TO_QUEST",("QUEST",)),req(obs()),lambda:obs(frame_sha256="b"*64,capture_completed_monotonic=1000.05),lambda roi:(calls.append(roi) or TransportResult(True,"OK")),lambda:next(posts))
        self.assertEqual(result.status,NavigationStatus.REACHED_SUCCESSOR); self.assertEqual(len(calls),2)
    def test_unknown_successor_needs_recovery_not_global_block(self):
        result=self.runner().run(NavigationStep("home-quest","HOME_BASE","HOME_TO_QUEST",("QUEST",),allow_one_safe_retry=False),req(obs()),lambda:obs(frame_sha256="b"*64,capture_completed_monotonic=1000.05),lambda roi:TransportResult(True,"OK"),lambda:[obs(source_state="UNKNOWN",recognized=False,target_identity=None,target_roi=None)])
        self.assertTrue(result.recovery_required); self.assertFalse(self.store.has_action_block())
    def test_local_change_and_spend_deny(self):
        result=self.runner().run(NavigationStep("home-quest","HOME_BASE","HOME_TO_QUEST",("QUEST",)),req(obs()),lambda:obs(frame_sha256="b"*64,capture_completed_monotonic=1000.05,target_roi=(0,0,1,1)),lambda roi:TransportResult(True,"OK"),lambda:[])
        self.assertEqual(result.transport_calls,0)
        self.assertEqual(CentralPolicy().evaluate(replace(req(obs()),action_class=ActionClass.SPEND_OR_STRATEGIC)).reason_code,"SPEND_OR_STRATEGIC_DISABLED")
