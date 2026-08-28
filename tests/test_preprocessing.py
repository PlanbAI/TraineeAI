import unittest

from analysis.models import UnifiedEvent
from analysis.normalize import normalize_browser, normalize_desktop
from analysis.pipeline import build_candidate_episodes, enrich_timeline, reduce_noise


class NormalizeTests(unittest.TestCase):
    def test_normalizes_collector_formats_and_extracts_shared_entity(self):
        desktop = normalize_desktop(
            {
                "timestamp": "2026-08-28T12:00:00.100+00:00",
                "type": "window.focused",
                "application": {"name": "chromium", "pid": 42},
                "window": {"title": "Jira - ABC-123"},
            }
        )
        browser = normalize_browser(
            {
                "timestamp": "2026-08-28T12:00:00.230Z",
                "type": "click",
                "page": {"url": "https://jira.example/browse/ABC-123", "title": "ABC-123"},
                "element": {"role": "button", "text": "Search"},
                "_tab": {"targetId": "tab-1"},
            }
        )

        enriched = enrich_timeline([desktop, browser])

        self.assertEqual(enriched[1].app_name, "chromium")
        self.assertEqual(enriched[1].window_title, "Jira - ABC-123")
        self.assertIn({"type": "jira_issue_id", "value": "ABC-123"}, enriched[1].entities)

    def test_redacts_sensitive_browser_field_in_analysis_output(self):
        event = normalize_browser(
            {
                "timestamp": "2026-08-28T12:00:00Z",
                "type": "input",
                "page": {"url": "https://example.test/login"},
                "element": {
                    "tag": "input",
                    "name": "api_token",
                    "type": "text",
                    "value": "secret-value",
                },
            }
        )

        self.assertEqual(event.target["value"], "<REDACTED>")
        self.assertTrue(event.data["value_redacted"])


class EpisodeBuilderTests(unittest.TestCase):
    def test_keeps_cross_application_events_with_shared_entity_in_one_episode(self):
        events = [
            UnifiedEvent(
                timestamp="2026-08-28T12:00:00Z",
                ts_epoch=0,
                source="browser",
                event_type="click",
                app_name="browser",
                entities=[{"type": "jira_issue_id", "value": "ABC-123"}],
            ),
            UnifiedEvent(
                timestamp="2026-08-28T12:00:30Z",
                ts_epoch=30,
                source="desktop",
                event_type="ui.focus",
                app_name="terminal",
                window_title="Terminal",
                entities=[{"type": "jira_issue_id", "value": "ABC-123"}],
            ),
        ]

        episodes = build_candidate_episodes(events)

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].applications, ["browser", "terminal"])

    def test_aggregates_repeated_input_into_fill_action(self):
        events = [
            UnifiedEvent(
                timestamp="2026-08-28T12:00:00Z",
                ts_epoch=0,
                source="browser",
                event_type="input",
                target={"id": "issue-id", "tag": "input"},
            ),
            UnifiedEvent(
                timestamp="2026-08-28T12:00:01Z",
                ts_epoch=1,
                source="browser",
                event_type="input",
                target={"id": "issue-id", "tag": "input"},
            ),
        ]

        reduced = reduce_noise(events)

        self.assertEqual([event.event_type for event in reduced], ["fill"])

    def test_keeps_same_origin_navigation_in_one_episode_after_context_gap(self):
        events = [
            UnifiedEvent(
                timestamp="2026-08-28T12:00:00Z",
                ts_epoch=0,
                source="browser",
                event_type="click",
                app_name="browser",
                url="https://jira.example/browse/ABC-123",
            ),
            UnifiedEvent(
                timestamp="2026-08-28T12:00:30Z",
                ts_epoch=30,
                source="browser",
                event_type="navigate",
                app_name="browser",
                url="https://jira.example/browse/ABC-123?focusedCommentId=1",
            ),
        ]

        episodes = build_candidate_episodes(events)

        self.assertEqual(len(episodes), 1)


if __name__ == "__main__":
    unittest.main()
