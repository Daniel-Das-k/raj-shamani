import copy
import unittest

from knowledge.guide_reply import REPLY_PROMPT, SCOPE_PROMPT, compose_reply


class ReplyLLM:
    supports_schema = True

    def __init__(self):
        self.calls = []
        self.approve = True
        self.scope_accurate = True
        self.reject_item = None
        self.draft = {'requested_parts': [{'part': 'How to build a business', 'covered': True},
                                         {'part': 'Guaranteed outcome by 22', 'covered': False}],
                      'sentences': [{'text': 'Build a product customers need.', 'moment_ids': ['M2']},
                                    {'text': 'Keep a substantial ownership stake.', 'moment_ids': ['M1']}],
                      'limitation': 'These excerpts do not establish that you will become a billionaire by 22.'}

    def complete(self, prompt, data, *, schema):
        self.calls.append((prompt, data))
        if prompt == REPLY_PROMPT:
            return copy.deepcopy(self.draft)
        if prompt == SCOPE_PROMPT:
            return {'accurate': self.scope_accurate, 'reason': 'Checked what the originals do not establish.'}
        return {'checks': {key: {'supported': self.approve and key != self.reject_item,
                    'evidence_ids': props['properties']['evidence_ids']['items']['enum'][:1],
                    'unsupported_claims': [] if self.approve and key != self.reject_item else ['Invented outcome.'],
                    'reason': 'Original evidence checked.'}
                for key, props in schema['properties']['checks']['properties'].items()}}


class GuideReplyTests(unittest.TestCase):
    def setUp(self):
        self.llm = ReplyLLM()
        self.recommendations = [
            {'summary': text, 'limitation': 'No guaranteed deadline.', 'citation': {
                'source_id': vid, 'title': 'Business discussion', 'start': 10, 'end': 20,
                'url': f'https://www.youtube.com/watch?v={vid}&t=10s', 'quote': text}}
            for vid, text in [('abcdefghijk', 'Keep a substantial ownership stake.'),
                              ('0123456789a', 'Build a product customers need.')]]

    def run_reply(self):
        return compose_reply('How can I become a billionaire by 22?', self.recommendations, self.llm)

    def test_combines_actions_and_explicit_limit_into_one_checked_paragraph(self):
        result = self.run_reply()
        self.assertEqual(result['reply_status'], 'ready')
        self.assertEqual(result['reply_coverage'], 'partial')
        self.assertEqual(len(result['points']), 1)
        self.assertEqual(result['points'][0]['text'], 'Build a product customers need. Keep a substantial ownership stake. '
                         'These excerpts do not establish that you will become a billionaire by 22.')
        self.assertEqual([c['source_id'] for c in result['points'][0]['citations']], ['0123456789a', 'abcdefghijk'])
        checked = self.llm.calls[1][1]
        self.assertEqual(len(checked['items']), 2)
        scope = self.llm.calls[2]
        self.assertEqual(scope[0], SCOPE_PROMPT)
        self.assertEqual(scope[1]['limitation'], self.llm.draft['limitation'])
        self.assertEqual(len(scope[1]['original_excerpts']), 2)
        self.assertEqual(checked['items'][0]['excerpt_ids'], ['E0'])
        self.assertEqual(checked['items'][1]['excerpt_ids'], ['E1'])
        self.assertEqual(checked['excerpts'][0]['support_spans'][0]['text'], 'Build a product customers need.')

    def test_unsupported_reply_is_withheld_after_one_bounded_repair(self):
        self.llm.approve = False
        result = self.run_reply()
        self.assertEqual(result, {'points': [], 'reply_status': 'invalid_evidence'})
        self.assertEqual(len(self.llm.calls), 4)

    def test_failed_sentence_is_removed_without_losing_independently_checked_advice(self):
        self.llm.reject_item = '1'
        result = self.run_reply()
        self.assertEqual(result['reply_status'], 'ready')
        self.assertEqual(result['points'][0]['text'], 'Build a product customers need. '
                         'These excerpts do not establish that you will become a billionaire by 22.')
        self.assertEqual(len(result['points'][0]['citations']), 1)
        self.assertEqual(result['points'][0]['citations'][0]['source_id'], '0123456789a')
        self.assertEqual(len(self.llm.calls), 3)

    def test_unknown_model_citation_cannot_create_a_reference(self):
        self.llm.draft['sentences'][0]['moment_ids'] = ['M999']
        self.assertEqual(self.run_reply()['reply_status'], 'invalid_evidence')
        self.assertEqual(len(self.llm.calls), 2)  # Neither draft reaches verification.

    def test_partial_reply_requires_an_explicit_limit(self):
        self.llm.draft['limitation'] = ''
        self.assertEqual(self.run_reply()['reply_status'], 'invalid_evidence')

    def test_inaccurate_limitation_is_withheld_not_appended_unchecked(self):
        self.llm.scope_accurate = False
        self.assertEqual(self.run_reply()['reply_status'], 'invalid_evidence')
        self.assertEqual(len(self.llm.calls), 6)

    def test_related_advice_can_be_checked_even_without_an_exact_personal_answer(self):
        for part in self.llm.draft['requested_parts']:
            part['covered'] = False
        self.assertEqual(self.run_reply()['reply_status'], 'ready')

    def test_provider_failure_does_not_expose_exception_text(self):
        def fail(*args, **kwargs):
            raise RuntimeError('private provider detail')
        self.llm.complete = fail
        audit = {}
        result = compose_reply('Explain.', self.recommendations, self.llm, audit)
        self.assertEqual(result['reply_status'], 'provider_error')
        self.assertNotIn('private provider detail', str(result) + str(audit))

    def test_no_useful_clips_requires_no_extra_generation(self):
        result = compose_reply('Explain.', [], self.llm)
        self.assertEqual(result['points'], [])
        self.assertEqual(self.llm.calls, [])

    def test_unrelated_clips_can_abstain_from_a_combined_answer(self):
        self.llm.draft['sentences'] = []
        self.assertEqual(self.run_reply()['reply_status'], 'insufficient_evidence')
        self.assertEqual(len(self.llm.calls), 1)

    def test_wrong_language_or_fragment_is_withheld(self):
        self.llm.draft['sentences'][0]['text'] = 'Build a product that'
        self.assertEqual(self.run_reply()['reply_status'], 'invalid_evidence')
        self.llm = ReplyLLM()
        self.assertEqual(compose_reply('என்ன செய்ய வேண்டும்?', self.recommendations, self.llm)['reply_status'], 'invalid_evidence')
