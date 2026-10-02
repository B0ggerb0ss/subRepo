"""Offline contract checks; no live Jev/OneJev/OCR/ASR inference is claimed."""
from __future__ import annotations
import copy,json,unittest
from pathlib import Path
from pydantic import ValidationError
from metadata_models import MediaMetadata
from reference_interfaces import AnalysisUnavailable,SystemOneAdapter,build_jev_state,normalize_answers,project_ranges,stage_cache_key,probe_asset

ROOT=Path(__file__).parent

class Contracts(unittest.TestCase):
    def setUp(self):
        self.example=json.loads((ROOT/'talking_head_45s.example.json').read_text())
        self.catalog=json.loads((ROOT/'question_catalog.json').read_text())

    def test_complete_example_and_generated_schema(self):
        m=MediaMetadata.model_validate(self.example)
        self.assertTrue(m.illustrative)
        self.assertEqual(m.technical.value['duration_s'],45)
        schema=json.loads((ROOT/'media_metadata_v1.schema.json').read_text())
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('Scene',schema['$defs'])

    def test_invalid_probability_and_source_range_rejected(self):
        invalid=copy.deepcopy(self.example)
        invalid['decisions']['kind']['probs']['other']=.9
        with self.assertRaises(ValidationError):MediaMetadata.model_validate(invalid)
        invalid=copy.deepcopy(self.example)
        invalid['timeline'][0]['source_out']=46
        with self.assertRaises(ValidationError):MediaMetadata.model_validate(invalid)
        for change in ['failed_stage','escaping_frame','noncontiguous_score']:
            invalid=copy.deepcopy(self.example)
            if change=='failed_stage':invalid['stage_status']['ocr']='error'
            if change=='escaping_frame':invalid['video_scenes'][0]['keyframe']['path']='../secret.jpg'
            if change=='noncontiguous_score':invalid['decisions']['usable']['probs']={'0':0,'2':0,'3':.05,'4':.2,'5':.75}
            with self.assertRaises(ValidationError):MediaMetadata.model_validate(invalid)

    def test_native_score_is_zero_based_and_confidence_is_separate(self):
        q={'quality':{'type':'score','instructions':'quality','criteria':['poor','fair','good','excellent','ideal']},'kind':{'type':'choice','instructions':'kind','criteria':{'x':'x','y':'y'}},'speech':{'type':'noul','instructions':'speech'}}
        response={'model':'jev-1.13.0','answers':{'quality':{'type':'score','score':3.2,'confidence':.71,'probabilities':{'0':0,'1':.05,'2':.1,'3':.45,'4':.4}},'kind':{'type':'choice','choice':'x','probabilities':{'x':.85,'y':.15},'confidence':.78},'speech':{'type':'noul','noul':.9}}}
        out=normalize_answers(response,q)
        self.assertAlmostEqual(out['quality']['value'],4.2)
        self.assertEqual(out['kind']['confidence'],.78)
        self.assertEqual(out['kind']['probs']['x'],.85)
        self.assertEqual(out['speech']['confidence_kind'],'derived_margin')
        self.assertAlmostEqual(out['speech']['confidence'],.8)

    def test_bad_provider_shapes_do_not_become_fake_decisions(self):
        q={'keep':{'type':'noul','instructions':'keep'}}
        for answer in [float('nan'),-1,1.2,True]:
            with self.assertRaises(AnalysisUnavailable):
                normalize_answers({'model':'test','answers':{'keep':{'type':'noul','noul':answer}}},q)
        with self.assertRaises(AnalysisUnavailable):
            normalize_answers({'model':'test','answers':{}},q)
        with self.assertRaises(AnalysisUnavailable):
            normalize_answers({'model':'test','answers':{'keep':None}},q)

    def test_trim_reuses_source_clock_and_projects_playback_rate(self):
        scenes=[{'scene_id':'a','t0':0,'t1':22.5},{'scene_id':'b','t0':22.5,'t1':45}]
        before=copy.deepcopy(scenes)
        view=project_ranges(scenes,8,23,timeline_start=10,playback_rate=2)
        self.assertEqual(scenes,before)
        self.assertEqual(view[0]['timeline_t0'],10)
        self.assertEqual(view[1]['source_t0'],22.5)
        self.assertEqual(view[1]['timeline_t1'],17.5)

    def test_stage_keys_change_only_for_real_dependencies(self):
        h='f'*64
        a=stage_cache_key(h,'ocr','v1',{'lang':'en','size':1280})
        b=stage_cache_key(h,'ocr','v1',{'size':1280,'lang':'en'})
        self.assertEqual(a,b)
        self.assertNotEqual(a,stage_cache_key(h,'ocr','v1',{'lang':'hi','size':1280}))
        self.assertNotEqual(a,stage_cache_key(h,'ocr','v2',{'lang':'en','size':1280}))

    def test_text_state_contains_layout_but_does_not_pretend_to_see(self):
        state=build_jev_state(self.example,focus='Reliable ML serving')
        self.assertFalse(state['evidence_availability']['pixels_attached'])
        self.assertEqual(state['ocr_layout'][0]['regions'][0]['text'],'RELIABLE ML FEATURES')
        self.assertIn('laplacian_variance',state['scene_manifest'][0]['metrics'])
        self.assertLessEqual(len(json.dumps(state,ensure_ascii=False,separators=(',',':')).encode()),16000)

    def test_cloud_disabled_and_official_text_endpoint_rejects_media(self):
        questions={'keep':{'type':'noul','instructions':'keep'}}
        with self.assertRaises(AnalysisUnavailable):
            SystemOneAdapter('https://api.typesafe.ai/v1/systemone','jev-1.13.0').decide({},questions)
        with self.assertRaises(AnalysisUnavailable):
            SystemOneAdapter('https://api.typesafe.ai/v1/systemone','jev-1.13.0',api_key='test-only',allow_cloud_text=True).decide({},questions,media=[{'type':'image','data':'data:image/png;base64,AA=='}])

    def test_required_catalog_and_declared_group_budget(self):
        groups=self.catalog['groups']
        self.assertEqual([len(groups[k]) for k in ['asset','scene','text','project']],[9,8,5,8])
        self.assertEqual(set(groups['asset']['kind']['criteria']),{'footage','screen_recording','talking_head','slideshow','motion_graphics','photo_sequence','other'})
        self.assertEqual(len(groups['asset']['usable']['criteria']),5)
        self.assertEqual(len(groups['scene']['highlight_value']['criteria']),5)

    def test_probe_real_bundled_media(self):
        repo=ROOT.parents[1]/'AttentionX'
        source=repo/'data/test/test_video.mp4'
        if not source.exists():self.skipTest('repo source not included in implementation pack')
        raw=probe_asset(source)
        self.assertGreater(float(raw['format']['duration']),20)
        self.assertTrue(any(s['codec_type']=='video' for s in raw['streams']))

if __name__=='__main__':unittest.main(verbosity=2)
