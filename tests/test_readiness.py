import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from v2t.readiness import check,manager_health
from v2t.core import asr_config

class Readiness(unittest.TestCase):
    def setUp(self):
        # Preserve isolated test directories; no bulk cleanup.
        self.root=Path(tempfile.mkdtemp(prefix='v2t-readiness-'))
        self.env={'DATA_ROOT':str(self.root),'MEDIA_ROOT':str(self.root),'MODEL_ROOT':str(self.root),
                  'HOTWORDS_FILE':str(self.root/'hotwords.txt'),'RESULT_MIN_FREE_BYTES':'0','MEDIA_MIN_FREE_BYTES':'0'}
        (self.root/'hotwords.txt').write_text('WorkBuddy\n',encoding='utf-8')
    def lock(self):
        (self.root/'models.lock.json').write_text(json.dumps({e:{'config':asr_config(e)} for e in ('funasr','whisper')}))
    def test_missing_config_not_healthy(self):
        with patch.dict(os.environ,self.env),patch('v2t.readiness.subprocess.run'):
            self.lock();self.env['HOTWORDS_FILE']=str(self.root/'missing.txt')
            with patch.dict(os.environ,self.env):self.assertFalse(check('gpu')['ready'])
    def test_model_mismatch_not_healthy(self):
        with patch.dict(os.environ,self.env):
            (self.root/'models.lock.json').write_text('{}')
            self.assertFalse(check('gpu')['ready'])
    def test_gpu_prerequisites_ready_not_inference_claim(self):
        with patch.dict(os.environ,self.env),patch('v2t.readiness.subprocess.run'):
            self.lock();self.assertTrue(check('gpu')['ready'])
    def test_missing_credentials_not_healthy(self):
        with patch.dict(os.environ,{**self.env,'WINDOWS_ADAPTER_ENABLED':'1','ADAPTER_INTERNAL_KEY_FILE':str(self.root/'missing.key')}):
            self.assertFalse(check('download')['ready'])
    def test_stale_manager_marker_not_healthy(self):
        (self.root/'readiness.json').write_text('{"ready":true,"checked_at":0}')
        with patch.dict(os.environ,{'DB_ROOT':str(self.root)}):self.assertFalse(manager_health())
