import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import bangkok_pipeline as b
import update_bangkok as updater

NOW = datetime(2026, 10, 9, 9, tzinfo=b.BKK)
URL = 'https://example.com/events/show'
RAW = dict(title='A show', event_name='A show', venue='Gallery', loc='Gallery, Bangkok',
           desc='An exhibition.', city='Bangkok', kind='exhibition', start_date='2026-10-01',
           end_date='2026-10-11', detail_url=URL, free=False, cat='art')
VENUES = {'gallery': dict(name='Gallery', aliases=['The Gallery'], lat=13.73, lng=100.52,
                         verified=True, evidence_url='https://example.com/map')}


class PipelineTests(unittest.TestCase):
    def test_extraction_uses_surplus_and_blocks_openrouter(self):
        with patch.object(updater, 'surplus_api_key', return_value='test-key'), patch.object(updater.requests, 'post') as post:
            chunk = {'choices': [{'delta': {'content': '[{"title":"Example","cat":"art"}]'}, 'finish_reason':'stop'}]}
            post.return_value.iter_lines.return_value = [b': keepalive', b'data: '+json.dumps(chunk).encode(), b'data: [DONE]']
            events = updater.extract_activities('Public source text', 'bangkok')
            self.assertEqual(events[0]['title'], 'Example')
            self.assertEqual(post.call_args.args[0], 'https://api.surplusintelligence.ai/v1/chat/completions')
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-key')
            self.assertEqual(post.call_args.kwargs['json']['providers_blocked'], ['openrouter'])
            self.assertEqual(post.call_args.kwargs['json']['provider'], 'deepseek')
            self.assertEqual(post.call_args.kwargs['json']['model'], 'deepseek-v4-flash')
            self.assertTrue(post.call_args.kwargs['stream'])

    def test_interrupted_surplus_stream_is_not_accepted(self):
        with patch.object(updater, 'surplus_api_key', return_value='test-key'), patch.object(updater.requests, 'post') as post, patch.object(updater.time, 'sleep'):
            chunk = {'choices':[{'delta':{'content':'[]'}, 'finish_reason':'length'}]}
            post.return_value.iter_lines.return_value = [b'data: '+json.dumps(chunk).encode(), b'data: [DONE]']
            with self.assertRaisesRegex(RuntimeError, 'interrupted or exceeded'):
                updater.extract_activities('Public source text', 'bangkok')
            self.assertEqual(post.return_value.close.call_count, 3)

    def test_surplus_key_does_not_fall_back_to_openrouter(self):
        with patch.dict(updater.os.environ, {'OPENROUTER_API_KEY':'old-key'}, clear=True), patch.object(updater.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, 'SURPLUS_API_KEY'):
                updater.surplus_api_key()

    def clean(self, raw=None, venues=None):
        return b.clean_event(raw or RAW, 'Source', 'https://example.com', {URL}, venues or {}, NOW)

    def test_discards_model_coordinates(self):
        event = self.clean(dict(RAW, lat=13.75, lng=100.5))
        self.assertIsNone(event['lat'])
        self.assertEqual(event['location_status'], 'unconfirmed')

    def test_verified_venue_overrides_model_and_alias_matches(self):
        event = self.clean(dict(RAW, venue='The Gallery', lat=1, lng=2), VENUES)
        self.assertEqual((event['lat'], event['lng']), (13.73, 100.52))

    def test_unverified_or_outside_city_never_gets_pin(self):
        for change in ({'verified': False}, {'lat': 1}, {'evidence_url': ''}):
            venues = copy.deepcopy(VENUES)
            venues['gallery'].update(change)
            self.assertIsNone(self.clean(venues=venues)['lat'])

    def test_requires_observed_detail_link(self):
        with self.assertRaises(ValueError):
            self.clean(dict(RAW, detail_url='https://invented.example/event'))
        event = self.clean(dict(RAW, ticket_url='javascript:alert(1)'))
        self.assertEqual(event['ticket_url'], '')

    def test_rejects_wrong_city_and_outside_weekend(self):
        for change in ({'city': 'Phuket'}, {'end_date': '2026-10-05'}, {'start_date': '2026-10-12'}, {'end_date': 'tomorrow'}):
            with self.assertRaises(ValueError):
                self.clean(dict(RAW, **change))

    def test_friday_and_sunday_share_weekend(self):
        self.assertEqual(b.weekend_window(NOW), b.weekend_window(datetime(2026, 10, 11, tzinfo=b.BKK)))

    def test_accepts_explicit_overnight_end(self):
        event = self.clean(dict(RAW, end_at='2026-10-12T01:00:00+07:00'))
        self.assertEqual(event['end_at'], '2026-10-12T01:00:00+07:00')
        with self.assertRaises(ValueError):
            self.clean(dict(RAW, end_at='2026-10-11T01:00:00'))

    def test_merge_preserves_links_and_stable_id(self):
        first = self.clean(venues=VENUES)
        second = copy.deepcopy(first)
        second.update(venue='The Gallery', start_date='2026-10-09')
        second['sources'] = [{'name':'Another', 'url':'https://example.com/another'}]
        second['ticket_url'] = 'https://example.com/tickets'
        old = dict(first, id='stable', first_seen='2026-10-02T09:00:00+07:00')
        result = b.merge_events([first,second], [old])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['sources']), 2)
        self.assertEqual(result[0]['id'], 'stable')
        self.assertEqual(result[0]['ticket_url'], second['ticket_url'])

    def test_all_failed_sources_keep_previous(self):
        def fail(url):
            raise RuntimeError('offline')
        with self.assertRaisesRegex(RuntimeError, 'keeping previous'):
            b.collect(fail, lambda *a, **k: [], [self.clean()], NOW)

    def test_serialization_cannot_close_script_or_expand_regex_escapes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'index.html'
            path.write_text('var A_BANGKOK = [];\nvar LABEL_BANGKOK = "old";\n', encoding='utf-8')
            event = self.clean(dict(RAW, title='</script>\\new', event_name='</script>\\new'))
            with patch.object(updater, 'HTML_FILE', path):
                updater.update_html_city('bangkok', [event], 'new', {'updated_at':'today'})
                self.assertEqual(b.read_previous(path)[0]['title'], '</script>\\new')
                self.assertNotIn('</script>', path.read_text())
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    updater.update_html_city('bangkok', [], 'bad')
                self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
