"""Fake-candidate regressions for unified search; no personal index is read."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'local-file-kit' / 'scripts'))
from lfkit import quick, serve, cli


class QuickTests(unittest.TestCase):
    def test_combined_evidence_requires_leading_content_and_semantic_support(self):
        filename = dict(name_words=.3, path_words=0, _evidence=dict(rank=0,z=2.2,cosine=.77))
        self.assertFalse(quick._weak([filename]))
        self.assertTrue(quick._weak([dict(filename,_evidence=dict(rank=1,z=2.2,cosine=.77))]))
        folder = dict(name_words=0, path_words=.3, _evidence=dict(rank=0,z=4.6,cosine=.76))
        self.assertFalse(quick._weak([folder]))
        self.assertTrue(quick._weak([dict(folder,_evidence=dict(rank=0,z=2.2,cosine=.77))]))
        self.assertTrue(quick._weak([dict(filename,_type_mismatch=True)]))

    def test_expansion_reuses_slow_content_but_still_expands_the_other_index(self):
        def reply(request, **kwargs):
            return {'hits':[{'path':f'item-{i}.md'} for i in range(request['limit'])], 'meaning':True}
        first=[dict(path='earlier.md',_code=False,_rank=0)]
        side={'_deadline':time.monotonic()+1,'_prior_profile':{'semantic':2,'code':.1},'_prior_hits':first}
        with patch.object(serve,'ask_index',side_effect=reply) as ask:
            quick._content('stars',[],[],20,side)
            self.assertEqual(len(side['hits']),21)
            self.assertEqual(side['hits'][0]['path'],'earlier.md')
            self.assertTrue(side['profile']['semantic_reused'])
            self.assertTrue(side['timed_out'])
            self.assertEqual(ask.call_count,1)

    def test_complete_name_pool_is_reused_without_repeating_es(self):
        side={'_prior_names':{'names':[self.name('fixtures/quiet.md')],'names_engine':'everything'}}
        with patch.object(quick.find,'_es_run') as search:
            quick._names(['quiet'],set(),None,None,[],side)
            search.assert_not_called()
        self.assertEqual(len(side['names']),1)
        self.assertTrue(side['profile']['names_reused'])

    def test_partial_name_failure_is_not_treated_as_a_complete_pool(self):
        row=self.name('fixtures/quiet.md')
        def es(exe,under,*args):
            if under=='unavailable':
                raise quick.LfkError('tool_failed','synthetic failure')
            return [row]
        side={}
        with patch.object(quick.tools,'locate',return_value={'found':True,'path':'fake-es'}), \
             patch.object(quick.find,'_es_run',side_effect=es):
            quick._names(['quiet'],set(),None,None,['available','unavailable'],side)
        self.assertEqual(len(side['names']),1)
        self.assertIn('names_error',side)
        args=SimpleNamespace(query='quiet stars',limit=5,ext=None,kind=None,after=None,before=None,
                             under=None,no_excerpt=True)
        def inspect(*args):
            self.assertNotIn('_prior_names',args[-1])
        with patch.object(quick,'_names',side_effect=inspect),patch.object(quick,'_content'), \
             patch.object(quick,'_names_elsewhere'),patch.object(quick,'_present',return_value=True):
            quick._query_once(args,expanded=True,prior=side)

    def test_expansion_deadline_keeps_completed_candidates_and_kills_slow_es(self):
        from lfkit.util import run
        old=self.name('fixtures/quiet.md',size=11)
        found=self.name('fixtures/quiet stars.md',size=22)
        def es(exe,under,words,limit,sort,timeout=120):
            if sort:
                return [dict(old)] * 2000
            if words[0]=='<quiet>':
                return [dict(found)]
            run([sys.executable,'-c','import time; time.sleep(5)'],timeout=timeout)
            return []
        args=SimpleNamespace(query='quiet stars',limit=5,ext=None,kind=None,after=None,before=None,
                             under=None,no_excerpt=True)
        with patch.object(quick,'EXPANSION_SECONDS',.8),patch.object(quick,'MERGE_RESERVE_SECONDS',.2), \
             patch.object(quick.tools,'locate',return_value={'found':True,'path':'fake-es'}), \
             patch.object(quick.find,'_es_run',side_effect=es),patch.object(quick,'_present',return_value=True), \
             patch.object(quick,'_names_elsewhere',side_effect=lambda *a:a[-1].update(other_drives=[])), \
             patch.object(serve,'ask_index',return_value={'hits':[]}):
            result=quick.cmd_q(args)
        self.assertEqual(result['results'][0]['path'],found['path'])
        self.assertTrue(result['expanded'])
        self.assertIn(quick.EXPANSION_NOTE,result['notes'])
        self.assertLess(result['timing']['expansion_seconds'],1.)

    def test_whole_expansion_guard_includes_merge_and_has_no_late_result_mutation(self):
        release,finished=threading.Event(),threading.Event()
        args=SimpleNamespace(limit=5)
        def stage(args,expanded=False,prior=None,deadline=None):
            if expanded:
                release.wait(2)
                finished.set()
            return {'ok':True,'weak':True,'results':[{'path':'late' if expanded else 'first'}],
                    '_candidates':{},'profile':{}}
        try:
            with patch.object(quick,'EXPANSION_SECONDS',.05),patch.object(quick,'_query_once',side_effect=stage):
                result=quick.cmd_q(args)
                self.assertLess(result['timing']['expansion_seconds'],.2)
                self.assertIn(quick.EXPANSION_NOTE,result['notes'])
                release.set()
                self.assertTrue(finished.wait(1))
            self.assertEqual(result['results'],[{'path':'first'}])
        finally:
            release.set()

    def test_cli_exits_at_default_expansion_cap_with_unresponsive_worker(self):
        code = '''
import sys, time
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from lfkit import quick, cli
def stage(args, expanded=False, prior=None, deadline=None):
    if expanded:
        time.sleep(10)
    return {'ok':True,'weak':True,'count':0,'results':[],'_candidates':{},'profile':{}}
with patch.object(quick, '_query_once', side_effect=stage):
    cli.main(['q','synthetic fixture'])
'''
        scripts = Path(__file__).resolve().parents[1] / 'skills' / 'local-file-kit' / 'scripts'
        began = time.monotonic()
        process = subprocess.run([sys.executable,'-c',code,str(scripts)],capture_output=True,
                                 timeout=6,creationflags=0x08000000 if os.name=='nt' else 0)
        elapsed = time.monotonic()-began
        self.assertEqual(process.returncode,0,process.stderr.decode('utf-8','replace'))
        result = json.loads(process.stdout.decode('utf-8'))
        self.assertIn(quick.EXPANSION_NOTE,result['notes'])
        self.assertGreaterEqual(result['timing']['expansion_seconds'],2.4)
        self.assertLess(result['timing']['expansion_seconds'],3.)
        self.assertLess(elapsed,5.)

    def test_expired_helper_requests_do_not_queue_or_start_a_search(self):
        helper=serve._Service('fake-helper',None,1800)
        helper.lock.acquire()
        try:
            with patch.object(helper,'_start') as start:
                began=time.monotonic()
                with self.assertRaises(quick.LfkError):
                    helper.ask({'op':'search','_deadline':began+.03})
                self.assertLess(time.monotonic()-began,.2)
                start.assert_not_called()
        finally:
            helper.lock.release()
        with patch.object(helper,'_start') as start:
            with self.assertRaises(quick.LfkError):
                helper.ask({'op':'search','_deadline':time.monotonic()-1})
            start.assert_not_called()

    def test_searches_overlap_and_keep_normal_hits_first(self):
        gate=threading.Barrier(2)
        def reply(request):
            gate.wait(timeout=2)
            return {'hits':[dict(path='code.py' if request['code'] else 'note.md')], 'meaning':True}
        out={}
        with patch.object(serve,'ask_index',side_effect=reply):
            quick._content('stars',[],[],5,out)
        self.assertEqual([h['_code'] for h in out['hits']],[False,True])
        self.assertIn('semantic',out['profile'])
        self.assertIn('code',out['profile'])

    def test_semantic_confidence_is_independent_of_rank_fusion_score(self):
        good = dict(_score=.25, _evidence=dict(rank=0, z=7, cosine=.84, code=False))
        self.assertFalse(quick._weak([good]))
        self.assertTrue(quick._weak([dict(good, _evidence=dict(rank=0,z=5,cosine=.73,code=False))]))
        self.assertTrue(quick._weak([dict(good, _type_mismatch=True)]))

    def test_partial_filename_does_not_mask_uncertain_content(self):
        self.assertTrue(quick._weak([dict(_score=.48,name_words=.58,
                                        _evidence=dict(rank=2,z=5.5,cosine=.83,code=False))]))
        self.assertFalse(quick._weak([dict(_score=.8,name_words=1)]))

    def test_code_and_normal_search_use_separate_helpers(self):
        from unittest.mock import Mock
        normal, code = Mock(), Mock()
        normal.ask.return_value = {'encoder':'ready','vectors':100,'code_vectors':0}
        code.ask.return_value = {'encoder':'ready','vectors':0,'code_vectors':20}
        result=serve._route_index(normal,code,{'op':'search','code':True})
        normal.ask.assert_not_called()
        self.assertEqual(result['code_vectors'],20)
        status=serve._route_index(normal,code,{'op':'status'})
        self.assertEqual((status['vectors'],status['code_vectors']),(100,20))
        self.assertEqual(serve._route_index(normal,None,{'op':'search','code':True})['hits'],[])

    def test_memory_release_check(self):
        from unittest.mock import Mock
        main, code, stopped = Mock(), Mock(), Mock()
        main.running.return_value = True
        code.running.return_value = True
        stopped.running.return_value = False
        services = {'main': main, 'code': code, 'none': None, 'stopped': stopped}
        with patch.object(serve, '_log_release') as log:
            self.assertEqual(serve.release_check(services, 80, load=79), [])
            main.quit.assert_not_called()
            self.assertEqual(serve.release_check(services, 0, load=99), [])  # 0 = off
            main.quit.assert_not_called()
            self.assertEqual(serve.release_check(services, 80, load=80), ['main', 'code'])
            main.quit.assert_called_once()
            code.quit.assert_called_once()
            stopped.quit.assert_not_called()  # already let go: not done again
            self.assertEqual(log.call_count, 2)
        with patch.object(serve, 'memory_load', return_value=None):  # unreadable: nothing is released
            self.assertEqual(serve.release_check(services, 80), [])

    def test_memory_reload_check(self):
        from unittest.mock import Mock
        main, code = Mock(), Mock()
        main.running.return_value = False   # let go, still down
        code.running.return_value = True    # a search already started it again
        services = {'main': main, 'code': code}
        state = {'waiting': {'main', 'code'}, 'released_at': 0.0}
        with patch.object(serve, '_log_release') as log:
            self.assertEqual(serve.reload_check(services, state, 70, load=75, now=1000), [])  # still busy
            for _ in range(3):
                self.assertEqual(serve.reload_check(services, state, 70, load=60, now=1000), [])  # calm, not yet a minute
            self.assertEqual(serve.reload_check(services, state, 70, load=75, now=1000), [])  # busy again: count starts over
            for _ in range(3):
                serve.reload_check(services, state, 70, load=60, now=1000)
            main.ask.assert_not_called()
            self.assertEqual(serve.reload_check(services, state, 70, load=60, now=300), [])   # calm, but too soon after the release
            self.assertEqual(serve.reload_check(services, state, 70, load=60, now=1000), ['main'])
            main.ask.assert_called_once_with({'op': 'prewarm'})
            code.ask.assert_not_called()
            self.assertEqual(log.call_count, 1)
            self.assertEqual(state['waiting'], set())
            self.assertEqual(serve.reload_check(services, state, 70, load=10, now=9999), [])  # nothing waiting
            state['waiting'] = {'main'}
            self.assertEqual(serve.reload_check(services, state, 0, load=10, now=9999), [])   # 0 = off
            code.running.return_value = False                                               # the code helper is never preloaded
            state.update(waiting={'code'}, released_at=0.0, calm=9)
            self.assertEqual(serve.reload_check(services, state, 70, load=10, now=9999), [])
            code.ask.assert_not_called()

    def test_memory_reload_waits_for_room(self):
        from unittest.mock import Mock
        main = Mock()
        main.running.return_value = True
        main.pid.return_value = 4242
        services = {'main': main, 'code': None}
        state = {'sizes': {}}
        gb = 1 << 30
        with patch.object(serve, '_log_release'), patch.object(serve, 'private_bytes', return_value=4 * gb):
            self.assertEqual(serve.release_check(services, 80, load=85, sizes=state['sizes']), ['main'])
        self.assertEqual(state['sizes'], {'main': 4 * gb})  # what it held is what a reload will take again
        with patch.object(serve, '_log_release'), patch.object(serve, 'private_bytes', return_value=gb // 10):
            serve.release_check(services, 80, load=85, sizes=state['sizes'])  # let go before its vectors loaded
        self.assertEqual(state['sizes'], {'main': 4 * gb})  # the larger number is kept
        main.running.return_value = False
        state.update(waiting={'main'}, released_at=0.0, calm=9)
        total = 40 * gb  # 4 GB is 10 points of 40 GB
        with patch.object(serve, '_log_release'):
            self.assertEqual(serve.reload_check(services, state, 70, load=65, now=9999, release_at=80, total=total), [])
            main.ask.assert_not_called()  # 65 + 10 is within 5 of 80: it would be let go again
            self.assertEqual(state['waiting'], {'main'})  # still waiting, tried again later
            self.assertEqual(serve.reload_check(services, state, 70, load=60, now=9999, release_at=80, total=total),
                             ['main'])  # 60 + 10 leaves room
            main.ask.assert_called_once_with({'op': 'prewarm'})
            self.assertEqual(state['waiting'], set())

    def test_status_reads_numbers_with_commas(self):
        from lfkit import content
        out = ("index: /x/index.sqlite\nvectors: 1,234,567 in 1,300,000 segments\n"
               "  screenshot      12    12 done\n  doc          45,678   45000 done\nsize: 1 GB\n")
        with patch.object(content.tools, 'require', return_value='digup'), \
                patch.object(content, 'run', return_value=(0, out, '')), \
                patch.object(content, 'app_running', return_value=False):
            d = content.cmd_status(SimpleNamespace(index=None, cpu=False))
        self.assertEqual(d['vectors'], 1234567)
        self.assertEqual({k: v['files'] for k, v in d['kinds'].items()}, {'screenshot': 12, 'doc': 45678})

    def test_copy_places_are_folders_not_parts_of_words(self):
        self.assertEqual(quick._place_rank('D:\\docs\\golden folder\\copyright.txt')[1], 0)
        self.assertEqual(quick._place_rank('D:\\old\\notes.txt')[1], 1)
        self.assertEqual(quick._place_rank('D:\\backup\\notes.txt')[1], 1)

    def test_first_pass_answers_when_a_passage_times_out(self):
        hit = {'path': 'fixtures/quiet stars.md', 'segment_id': 3, 'z': 3.0, 'cosine': .8, '_rank': 0,
               'modified': 1700000000, 'size': 10}

        def content(*a):
            a[-1]['hits'] = [dict(hit)]

        def names(*a):
            a[-1]['names'] = []

        args = SimpleNamespace(query='quiet stars', limit=5, ext=None, kind=None, after=None, before=None,
                               under=None, no_excerpt=False, also=None)
        with patch.object(quick, '_names', side_effect=names), patch.object(quick, '_content', side_effect=content), \
                patch.object(quick, '_names_elsewhere'), patch.object(quick, '_present', return_value=True), \
                patch.object(serve, 'ask', side_effect=quick.LfkError('timeout', 'synthetic slow service')):
            out = quick._query_once(args)
        self.assertEqual(len(out['results']), 1)
        self.assertNotIn('excerpt', out['results'][0])
        self.assertTrue(any('did not answer in time' in n for n in out['notes']))

    def test_refresh_daily_task_is_built(self):
        from lfkit import refresh
        with patch.object(refresh, 'IS_WIN', True), patch.object(serve, '_ps', return_value=(0, '', '')) as ps:
            out = refresh._autostart(SimpleNamespace(autostart='on', at='03:30', max_hours=6))
        self.assertTrue(out['runs'].endswith('refresh --max-hours 6'))
        self.assertIn('LocalFileKit-IndexRefresh', ps.call_args[0][0])

    def test_cached_name_list_matches_spacing_and_parent_terms(self):
        names=serve.NameList()
        names.items=[('sample/별빛/관측 기록.md','관측 기록.md',False,10,100,
                      quick._compact('관측 기록.md'),quick._compact('sample/별빛'))]
        result=names.find({'words':['관측기록','별빛'],'exts':['md']})
        self.assertEqual(len(result['items']),1)
        self.assertEqual(names.find({'words':['관측기록'],'after':101})['items'],[])

    def query(self, query, names=(), hits=(), dump_path='', present=True, **options):
        args = SimpleNamespace(query=query, limit=5, ext=None, kind=None, after=None, before=None,
                               under=None, no_excerpt=True)
        for k, v in options.items():
            setattr(args, k, v)
        def names_reply(*a):
            a[-1].update(names=list(names), names_engine='everything', other_drives=[])
        def content_reply(*a):
            a[4]['hits'] = list(hits)
        with patch.object(quick, '_names', side_effect=names_reply), \
                patch.object(quick, '_content', side_effect=content_reply), \
                patch.object(quick, '_names_elsewhere'), \
                patch.object(quick, '_present', side_effect=lambda p: present or os.path.exists(p)), \
                patch.dict(os.environ, {'LFK_Q_DUMP': dump_path}):
            return quick.cmd_q(args)

    @staticmethod
    def name(path, size=12, mtime=100):
        return dict(path=os.path.abspath(path), size=size, mtime=mtime, is_dir=False)

    def test_particle_variants_keep_original_noun(self):
        words, _ = quick._words('사과 평가가 2024년')
        self.assertEqual(quick._coverage(words, '사과_평가_2024귀속.pdf'), 1)
        self.assertEqual(quick._coverage(['바다가'], '바다가.png'), 1)
        self.assertIn('바다', quick._word_variants('바다가'))
        self.assertEqual(quick._coverage(['바다가'], '바다가_바다.png'), 1)

    def test_joined_and_spaced_terms_and_capture_particle(self):
        self.assertEqual(quick._coverage(['검토의견서'], '검토 의견서.pdf'), 1)
        self.assertEqual(quick._coverage(['예비자', '조회'], '예비자조회.pdf'), 1)
        self.assertIn('캡처', quick._word_variants('캡처한'))
        self.assertIn('png', quick._words('캡처한')[1])

    def test_parent_terms_help_but_filename_is_stronger(self):
        path_only = self.name('fixtures/천문/목록.pdf', size=21)
        filename = self.name('fixtures/천문.pdf', size=22)
        result = self.query('천문', names=[path_only, filename])
        self.assertEqual(result['results'][0]['path'], filename['path'])
        self.assertEqual(result['results'][1]['path_words'], 1)

    def test_repeatable_aliases_do_not_dilute_original_query(self):
        args = cli.build_parser().parse_args(['q','별빛 그림','--also','starlight','--also','star light'])
        self.assertEqual(args.also, ['starlight','star light'])
        picture = self.name('fixtures/star_light.png')
        result = self.query('별빛 그림', names=[picture], also=args.also)
        self.assertEqual(result['results'][0]['name_words'], 1)
        self.assertFalse(result['weak'])
        self.assertFalse(result['expanded'])

    def test_weak_expands_once_and_keeps_previous_candidates(self):
        row = self.name('fixtures/천문.pdf')
        calls = []
        def names_reply(*a):
            out = a[-1]
            calls.append(out.get('expanded'))
            out.update(names=[] if out.get('expanded') else [row], names_engine='everything', other_drives=[])
        args = SimpleNamespace(query='천문 관측 미지의 역사',limit=5,ext=None,kind=None,after=None,before=None,
                               under=None,no_excerpt=True)
        with patch.object(quick,'_names',side_effect=names_reply), patch.object(quick,'_content'), \
                patch.object(quick,'_names_elsewhere'), patch.object(quick,'_present',return_value=True):
            result = quick.cmd_q(args)
        self.assertEqual(calls,[False,True])
        self.assertTrue(result['weak'])
        self.assertIn('못 찾았을 수 있음',result['notes'])
        self.assertEqual(result['results'][0]['path'],row['path'])
        self.assertGreaterEqual(result['timing']['expansion_seconds'],0)

    def test_code_request_and_independent_rank(self):
        calls = []
        def reply(request):
            calls.append(request)
            return {'hits':[dict(path='sample.py' if request['code'] else 'sample.pdf',kind='doc')], 'meaning':True}
        side = {}
        with patch.object(serve,'ask_index',side_effect=reply):
            quick._content('sample',[],[],5,side)
        self.assertEqual([r['code'] for r in calls],[False,True])
        self.assertEqual([h['_rank'] for h in side['hits']],[0,0])
        self.assertEqual(side['hits'][1]['kind'],'code')

    def test_code_text_uses_code_segment_namespace(self):
        hit = dict(path=os.path.abspath('fixtures/별빛.py'),size=12,modified=100,kind='code',_code=True,
                   segment_id=9,loc=20,loc_end=24)
        with patch.object(serve,'ask',return_value={'text':'synthetic code'}) as ask:
            result = self.query('별빛',hits=[hit],no_excerpt=False)
        self.assertTrue(ask.call_args.args[0]['code'])
        self.assertEqual(result['results'][0]['where'],'line 20–24')

    def test_custom_index_does_not_use_app_code_folders(self):
        self.assertEqual(serve._code_folders('isolated-index'),([],[]))
        service = serve._Service('fake-digup','index',30,['code-a','code-b'],['skip'])
        self.assertEqual(service.cmd.count('--code-root'),2)
        self.assertIn('--code-exclude',service.cmd)

    def test_stale_top_match_does_not_create_false_confidence(self):
        with tempfile.TemporaryDirectory() as folder:
            stale = self.name(str(Path(folder) / '천문계약서.pdf'))
            result = self.query('천문계약서',names=[stale],present=False)
            self.assertTrue(result['weak'])
            self.assertTrue(result['expanded'])
            self.assertEqual(result['count'],0)

    def test_unavailable_copy_lead_promotes_existing_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            present = Path(folder) / 'backup.txt'
            present.write_text('fixture',encoding='utf-8')
            result, _ = quick._live_results([{'path':str(Path(folder)/'missing.txt'),
                                              'other_places':[str(present)],'copies':2}],5)
            self.assertEqual(result[0]['path'],str(present))
            self.assertNotIn('copies',result[0])

    def test_live_copy_beyond_display_limit_is_not_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            present = Path(folder) / 'live.txt'
            present.write_text('fixture',encoding='utf-8')
            paths = [str(Path(folder)/f'missing-{i}.txt') for i in range(8)] + [str(present)]
            result, _ = quick._live_results([dict(path=paths[0],other_places=paths[1:6],_copy_paths=paths)],5)
            self.assertEqual(result[0]['path'],str(present))

    def test_expanded_terms_have_individual_candidate_quotas(self):
        calls=[]
        def run(es, under, words, limit, sort):
            calls.append((words,limit))
            return []
        with patch.object(quick.tools,'locate',return_value={'found':True,'path':'fake-es'}), \
                patch.object(quick.find,'_es_run',side_effect=run):
            quick._names(['common','rare'],set(),None,None,[],{'expanded':True})
        self.assertIn((['<rare>','file:'],1000),calls)
        self.assertIn((['<common>','file:'],1000),calls)

    def test_type_hint_applies_to_content_too(self):
        picture = self.name('fixtures/노을_사진.png')
        memo = dict(path=os.path.abspath('fixtures/노을_메모.md'), modified=100, size=30, z=5, kind='doc')
        result = self.query('노을 사진', names=[picture], hits=[memo])
        self.assertEqual(result['results'][0]['path'], picture['path'])

    def test_no_quoted_or_control_tokens_reach_es(self):
        term = quick._es_term('그림이나')
        self.assertEqual(term, '<그림이나|그림>')
        self.assertNotIn('"', quick._es_term('a"b'))
        self.assertNotIn('ext:', quick._es_term('ext:pdf'))

    def test_copy_group_does_not_consume_top_slots(self):
        a = self.name('fixtures/노을.png')
        b = self.name('fixtures/backup/노을 (1).png')
        c = self.name('fixtures/노을_다른.png', size=20)
        result = self.query('노을 그림', names=[a, b, c])
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['results'][0]['copies'], 2)

    def test_batch_query_includes_short_matches(self):
        calls = []
        def run(es, under, words, limit, sort):
            calls.append(words)
            return []
        with patch.object(quick.tools, 'locate', return_value={'found':True,'path':'fake-es'}), \
                patch.object(quick.find, '_es_run', side_effect=run):
            quick._names(['alpha','beta','gamma','delta','epsilon','zeta'], set(), None, None, [], {})
        self.assertEqual(len(calls), 1)
        self.assertTrue(any('<alpha>|<beta>' in call[0] for call in calls))
        self.assertTrue(all(' ' not in arg and '"' not in arg for call in calls for arg in call))

    def test_content_hit_receives_filename_evidence(self):
        report = dict(path=os.path.abspath('fixtures/연구_보고서.pdf'), size=12, modified=100, kind='pdf', z=4)
        memo = dict(path=os.path.abspath('fixtures/memo.md'), size=24, modified=100, kind='doc', z=5)
        result = self.query('연구 보고서', hits=[memo, report])
        self.assertEqual(result['results'][0]['path'], report['path'])
        self.assertEqual(result['results'][0]['why'], 'both')

    def test_ext_and_kind_are_intersected_on_both_engines(self):
        names = [self.name('fixtures/노을.png'), self.name('fixtures/노을.jpg')]
        hits = [dict(path=os.path.abspath('fixtures/노을.pdf'), modified=100, size=4, kind='pdf')]
        result = self.query('노을', names, hits, kind='image', ext='png')
        self.assertEqual([r['path'] for r in result['results']], [names[0]['path']])
        self.assertEqual(self.query('노을', names, hits, kind='image', ext='pdf')['results'], [])

    def test_unknown_size_files_are_not_folded(self):
        names = [self.name('fixtures/a/노을.png', size=None), self.name('fixtures/b/노을.png', size=None)]
        self.assertEqual(self.query('노을', names)['count'], 2)

    def test_metadata_dump_never_contains_passages(self):
        with tempfile.TemporaryDirectory() as folder:
            dump = Path(folder) / 'candidates.jsonl'
            hit = dict(path=str(Path(folder) / '노을.pdf'), size=12, modified=100, kind='pdf',
                       excerpt='PRIVATE PASSAGE', text='PRIVATE TEXT')
            result = self.query('노을', hits=[hit], dump_path=str(dump))
            self.assertNotIn('excerpt', result['results'][0])
            data = json.loads(dump.read_text(encoding='utf-8'))
            self.assertNotIn('excerpt', data['side']['hits'][0])
            self.assertNotIn('text', data['side']['hits'][0])

    def test_dates_and_under_apply_to_both_engines(self):
        with tempfile.TemporaryDirectory() as folder:
            inside = str(Path(folder) / '노을.pdf')
            outside = str(Path(folder + '-other') / '노을.pdf')
            names = [self.name(inside, mtime=1800000000), self.name(outside, mtime=1800000000),
                     self.name(str(Path(folder) / '노을_old.pdf'), mtime=1600000000)]
            hits = [dict(path=outside, modified=1800000000, size=55, kind='pdf')]
            result = self.query('노을', names, hits, under=[folder], after='2024-01-02')
            self.assertEqual([r['path'] for r in result['results']], [inside])


@unittest.skipUnless(os.name == 'nt' and quick.tools.locate('everything')['found'], 'Everything required')
class QuickEverythingTests(unittest.TestCase):
    def test_expanded_search_finds_spacing_and_parent_words(self):
        with tempfile.TemporaryDirectory(prefix='lfk-q-spacing-') as folder:
            parent = Path(folder) / '천문기획'
            parent.mkdir()
            wanted = parent / '검토 의견서.txt'
            wanted.write_text('synthetic fixture', encoding='utf-8')
            for _ in range(30):
                rows = quick.find._es_run(quick.tools.require('everything'), folder, ['file:'], 10, None)
                if rows:
                    break
                time.sleep(.1)
            side = {'expanded':True}
            quick._names(['천문기획','검토의견서'],set(),None,None,[folder],side)
            self.assertIn(str(wanted),[r['path'] for r in side['names']])

    def test_real_es_grouped_terms_survive_windows_argv(self):
        with tempfile.TemporaryDirectory(prefix='lfk-q-argv-') as folder:
            wanted = Path(folder) / 'alpha_beta.txt'
            wanted.write_text('synthetic fixture', encoding='utf-8')
            (Path(folder) / 'alpha_only.txt').write_text('synthetic fixture', encoding='utf-8')
            es = quick.tools.require('everything')
            for _ in range(30):
                rows = quick.find._es_run(es, folder, ['file:'], 10, None)
                if len(rows) == 2:
                    break
                time.sleep(.1)
            expression = '<' + ' '.join(quick._es_term(w) for w in ('alpha', 'beta')) + '>'
            rows = quick.find._es_run(es, folder, expression.split() + ['file:'], 10, None)
            self.assertEqual([r['path'] for r in rows], [str(wanted)])


if __name__ == '__main__':
    unittest.main()
