import copy
import unittest

from knowledge.caption_retrieval import source_citation
from knowledge.evidence_answers import answer_from_evidence, READ_PROMPT, SELECT_PROMPT, question_language, language_matches
from knowledge.supermemory_captions import caption_source


class Reader:
    supports_schema = True

    def __init__(self):
        self.calls = []
        self.readings = {
            'P0': {'statements': [{'text': 'During launch, your chest is compressed.', 'support_ids': ['U0']}], 'limitations': ''},
            'P1': {'statements': [{'text': 'In orbit, fluid shifts toward the head.', 'support_ids': ['U0']}], 'limitations': ''},
        }
        self.selections = [{'coverage': 'full', 'selected_ids': ['P0F0', 'P1F0']}]
        self.reject = set()

    def complete(self, system, data, *, schema):
        self.calls.append((system, data, schema))
        if system == READ_PROMPT:
            return copy.deepcopy(self.readings[data['passage']['id']])
        if system == SELECT_PROMPT:
            result = self.selections.pop(0)
            result.setdefault('requested_parts', [{'part': 'Explain the phases', 'covered': True}])
            return result
        supported = data['excerpts'][0]['title'] not in self.reject
        return {'checks': {str(item['id']): {'supported': supported, 'reason': 'Source support check',
                    'unsupported_claims': [] if supported else ['Wrong phase'], 'evidence_ids': ['E0:S0']}
                    for item in data['items']}}


class EvidenceAnswerTests(unittest.TestCase):
    def setUp(self):
        self.sources = {}
        self.citations = []
        for vid, title, text in [('abcdefghijk', 'Launch', 'During launch, your chest is compressed.'),
                                 ('lmnopqrstuv', 'Orbit', 'In orbit, fluid shifts toward the head.')]:
            source = caption_source({'id': vid, 'title': title}, {'events': [
                {'tStartMs': 10000, 'dDurationMs': 5000, 'segs': [{'utf8': text}]}]}, 'en')
            self.sources[vid] = source
            self.citations.append(source_citation(source, 0, 0))
        self.llm = Reader()

    def test_final_prose_is_selected_verified_text_and_summaries_stay_with_their_source(self):
        self.llm.selections[0]['invented_answer'] = 'Going to space guarantees perfect health.'
        answer = answer_from_evidence('What happens during launch and in orbit?', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'answered')
        point = answer['points'][0]
        self.assertEqual(point['text'], 'During launch, your chest is compressed. In orbit, fluid shifts toward the head.')
        for cite, original in zip(point['citations'], self.citations):
            self.assertEqual(cite['summary'], original['quote'])
            self.assertEqual(cite['url'], original['url'])
        for system, data, _ in self.llm.calls:
            if system == READ_PROMPT:
                self.assertIn('passage', data)
                self.assertNotIn('passages', data)
                self.assertNotIn('question', data)
            elif 'items' in data:
                self.assertEqual(len(data['excerpts']), 1)
                self.assertEqual(len(data['items']), 1)

    def test_failed_statement_is_excluded_and_repair_cannot_reuse_it(self):
        self.llm.reject = {'Launch'}
        self.llm.selections.append({'coverage': 'partial', 'selected_ids': ['P1F0']})
        audit = {}
        answer = answer_from_evidence('Explain the phases.', self.citations, self.sources, self.llm, audit)
        self.assertEqual(answer['status'], 'answered')
        self.assertEqual(answer['coverage'], 'partial')
        self.assertNotIn('chest', answer['points'][0]['text'])
        self.assertTrue(audit['repaired'])
        selections = [data for system, data, _ in self.llm.calls if system == SELECT_PROMPT]
        self.assertEqual([f['id'] for f in selections[1]['statements']], ['P1F0'])
        self.assertEqual(len([c for c in self.llm.calls if 'items' in c[1]]), 2)  # Identical passed text need not be rewritten or rechecked.

    def test_unknown_selection_never_creates_a_citation_or_answer(self):
        self.llm.selections = [{'coverage': 'full', 'selected_ids': ['P999F0']}] * 2
        answer = answer_from_evidence('Explain.', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'invalid_evidence')
        self.assertEqual(answer['points'], [])

    def test_missing_requested_part_overrides_full_coverage(self):
        self.llm.selections[0]['requested_parts'] = [
            {'part': 'Explain launch', 'covered': True}, {'part': 'Explain return', 'covered': False}]
        answer = answer_from_evidence('Explain launch and return.', self.citations, self.sources, self.llm)
        self.assertEqual(answer['coverage'], 'partial')
        self.assertIn('only part of your question', answer['points'][0]['text'])

    def test_corrupt_originals_are_rejected_before_reading(self):
        self.citations[0]['quote'] = 'Altered source claim'
        answer = answer_from_evidence('Explain.', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'invalid_evidence')
        self.assertEqual(self.llm.calls, [])

    def test_citation_metadata_cannot_override_original_provenance(self):
        for key, value in [('url', 'https://example.com/fake'), ('source_id', 'other'),
                           ('title', 'Invented title'), ('human_verified', True),
                           ('time_range', '00:00–99:00'), ('video_url', 'https://example.com/')]:
            with self.subTest(key=key):
                citations = copy.deepcopy(self.citations)
                citations[0][key] = value
                answer = answer_from_evidence('Explain.', citations, self.sources, self.llm)
                self.assertEqual(answer['status'], 'invalid_evidence')
                self.assertEqual(self.llm.calls, [])

    def test_no_usable_statements_abstains_without_selection_or_verification(self):
        for reading in self.llm.readings.values():
            reading['statements'] = []
        answer = answer_from_evidence('What is my bank balance?', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'insufficient_evidence')
        self.assertEqual(len(self.llm.calls), 2)

    def test_wrong_language_and_unknown_units_fail_closed(self):
        answer = answer_from_evidence('விண்வெளியில் என்ன நடக்கும்?', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'invalid_evidence')
        self.llm = Reader()
        for reading in self.llm.readings.values():
            reading['statements'][0]['support_ids'] = ['OTHER_SOURCE']
        answer = answer_from_evidence('Explain.', self.citations, self.sources, self.llm)
        self.assertEqual(answer['status'], 'invalid_evidence')

    def test_language_detection_and_script_checks(self):
        self.assertEqual(question_language('RACI mein difference kya hai?'), 'Hinglish')
        self.assertEqual(question_language('GDP क्यों बढ़ती है?'), 'Hindi')
        self.assertEqual(question_language('தரம் பற்றி விளக்குங்கள்'), 'Tamil')
        self.assertFalse(language_matches('This is an English reply.', 'Tamil'))
        self.assertTrue(language_matches('தரம் முக்கியம்.', 'Tamil'))


if __name__ == '__main__':
    unittest.main()
