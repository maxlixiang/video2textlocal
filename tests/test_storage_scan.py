import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from v2t.adapter_common import usage,space
from v2t.core import Failure

class StorageScan(unittest.TestCase):
 def setUp(self):self.root=Path(tempfile.mkdtemp(prefix='v2t-storage-scan-'))
 def test_transient_scan_error_retries(self):
  calls=[0]
  def walk(*args,**kwargs):
   calls[0]+=1
   if calls[0]==1:kwargs['onerror'](PermissionError(13,'fixture'))
   return []
  with patch('v2t.adapter_common.os.walk',side_effect=walk),patch('v2t.adapter_common.time.sleep'):
   self.assertEqual(usage(self.root),0);self.assertEqual(calls[0],2)
 def test_persistent_access_error_is_not_disk_full(self):
  def walk(*args,**kwargs):kwargs['onerror'](PermissionError(13,'fixture'));return []
  with patch('v2t.adapter_common.os.walk',side_effect=walk),patch('v2t.adapter_common.time.sleep'),self.assertRaises(Failure) as e:usage(self.root)
  self.assertEqual(e.exception.code,'storage_unavailable')
  self.assertTrue((self.root/'.storage-check.json').is_file())
 def test_free_space_query_failure_is_not_disk_full(self):
  with patch('v2t.adapter_common.shutil.disk_usage',side_effect=PermissionError(13,'fixture')),self.assertRaises(Failure) as e:space(self.root,0,1024,1)
  self.assertEqual(e.exception.code,'storage_unavailable')
 def test_actual_low_free_space_remains_disk_full(self):
  with patch('v2t.adapter_common.shutil.disk_usage',return_value=type('D',(),{'free':5})()),self.assertRaises(Failure) as e:space(self.root,10,1024,1)
  self.assertEqual(e.exception.code,'disk_full')
