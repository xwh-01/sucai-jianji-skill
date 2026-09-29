"""Synthetic coverage regressions; no source-video review is implied."""

import copy
import json
from pathlib import Path
import unittest

from validate_edit_plan import validate_entry_search, validate_plan


def fixture():
    events = []
    candidates = []
    for index, layer in enumerate(("relationship_setup", "conflict_origin", "direct_trigger")):
        event_id = f"event-{index}"
        events.append({
            "id": event_id, "anchor": f"Synthetic scene {index}",
            "layers": [layer], "connection": "Changes the trust behind the confrontation.",
            "viewer_evidence": "Synthetic visible confrontation, not reviewed footage.",
            "disposition": "compare",
        })
        candidates.append({
            "start_event_id": event_id, "entry": f"Synthetic scene {index}",
            "boundary_type": "latest_complete" if index == 2 else "natural_story",
            "causal_chain_complete": True, "story_arc": "Trust, betrayal, confrontation.",
            "information_gained": "The betrayal explains the confrontation.",
            "retention_beats": ["A promise is publicly broken."],
            "dead_zone_risk": "low", "emotional_build": True,
            "return_effect": "The confrontation pays off the betrayal.", "selected": index == 0,
        })
    return {
        "entry_search": {
            "scope_start": "Authorized synthetic scene 0",
            "scope_end": "Immediately before synthetic cold open",
            "source_evidence": "Synthetic test fixture only",
            "events": events, "absent_layers": {},
        },
        "compared_entries": candidates, "earlier_prefix_review": [],
        "selected_entry": candidates[0]["entry"],
    }


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.decision = fixture()

    def errors(self):
        errors = []
        validate_entry_search(self.decision, "context", errors)
        return errors

    def test_earliest_can_win(self):
        self.assertEqual(self.errors(), [])

    def test_local_candidates_without_search_fail(self):
        del self.decision["entry_search"]
        self.assertTrue(self.errors())

    def test_omitted_earlier_candidate_fails(self):
        self.decision["compared_entries"].pop(0)
        self.assertTrue(any("cover exactly all compare" in e for e in self.errors()))

    def test_neighboring_cuts_cannot_duplicate_event(self):
        self.decision["compared_entries"].append(copy.deepcopy(self.decision["compared_entries"][0]))
        self.assertTrue(any("distinct events" in e for e in self.errors()))

    def test_later_selection_requires_prefix_reviews(self):
        for candidate in self.decision["compared_entries"]:
            candidate["selected"] = candidate["start_event_id"] == "event-2"
        self.assertTrue(any("earlier_prefix_review" in e for e in self.errors()))
        self.decision["earlier_prefix_review"] = [{
            "event_id": f"event-{index}", "added_information": "Earlier public promise.",
            "retention_value": "Public betrayal changes the relationship.",
            "connection": "Explains distrust at the confrontation.",
            "cost": "Intervening scenes repeat the same allegation without change.",
            "rejection_reason": "Later dialogue retains the betrayal; repeated scenes stall escalation.",
        } for index in (0, 1)]
        self.assertEqual(self.errors(), [])

    def test_single_real_entry_with_merged_layers_passes(self):
        self.decision["entry_search"]["events"] = self.decision["entry_search"]["events"][:1]
        self.decision["entry_search"]["events"][0]["layers"] = [
            "relationship_setup", "conflict_origin", "direct_trigger"]
        self.decision["compared_entries"] = self.decision["compared_entries"][:1]
        self.assertEqual(self.errors(), [])

    def test_absent_layers_require_reasons(self):
        self.decision["entry_search"]["events"][0]["layers"] = ["conflict_origin"]
        self.assertTrue(self.errors())
        self.decision["entry_search"]["absent_layers"] = {
            "relationship_setup": "No separate relationship setup within the authorized source."}
        self.assertEqual(self.errors(), [])

    def test_excluded_event_requires_reason(self):
        self.decision["entry_search"]["events"][0]["disposition"] = "exclude"
        self.decision["compared_entries"].pop(0)
        self.assertTrue(any("exclusion_reason" in e for e in self.errors()))
        self.decision["entry_search"]["events"][0]["exclusion_reason"] = "No natural boundary before this action within the authorized source."
        self.assertEqual(self.errors(), [])

    def test_malformed_coverage_returns_errors(self):
        self.decision["entry_search"]["events"] = [None, {"id": [], "layers": [{}]}]
        self.decision["compared_entries"] = [{"start_event_id": {}}]
        self.decision["earlier_prefix_review"] = [None]
        self.assertTrue(self.errors())

    def test_full_plan_integration(self):
        path = Path(__file__).resolve().parents[1] / "references" / "validated-example.json"
        plan = json.loads(path.read_text())
        cold = next(v for v in plan["variants"] if v["id"] == "cold_open")
        cold["context_entry_decision"].update(self.decision)
        self.assertEqual(validate_plan(plan), [])
        del cold["context_entry_decision"]["entry_search"]
        self.assertTrue(any("entry_search" in e for e in validate_plan(plan)))


if __name__ == "__main__":
    unittest.main()
