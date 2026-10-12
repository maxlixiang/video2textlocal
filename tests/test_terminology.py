import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_core import Fixture,FakeTelegram
from v2t.core import asr_config,word_file,model_config,write_transcript
from v2t.manager import cached_raw
from v2t.polish import config
class Terminology(Fixture):
 def test_file_phrases_and_canonical_terms(self):
  p=self.root/'terms.txt';p.write_text('# comment\nWorkBuddy\nClaude Code\nWorkBuddy\nMCP # note\n',encoding='utf-8')
  self.assertEqual(word_file(p),['WorkBuddy','Claude Code','MCP'])
  with patch.dict(os.environ,{'HOTWORDS_FILE':str(p)}):self.assertIn('Claude Code',asr_config('funasr')['hotwords'])
 def test_hotword_change_invalidates_raw_without_model_reinstall(self):
  row=self.task('douyin');d,models,raw=self.artifacts(row);old=asr_config('funasr')
  with patch.dict(os.environ,{'HOTWORDS':'DifferentHint'}):
   new=asr_config('funasr');self.assertNotEqual(old,new);self.assertEqual(model_config(old),model_config(new));self.assertIsNone(cached_raw(d,'funasr',models))
 def test_polished_without_timestamps_original_unchanged(self):
  segs=[{'start':.05,'end':80.72,'text':'使用 WorkBuddy。'}];raw=self.root/'原稿.md';clean=self.root/'整理稿.md'
  write_transcript(raw,segs,{'engine':'funasr'});write_transcript(clean,segs,{'engine':'DeepSeek'},'整理稿',timestamps=False)
  self.assertIn('[00:00:00.050 - 00:01:20.720]',raw.read_text());self.assertNotIn('[00:',clean.read_text());self.assertIn('使用 WorkBuddy。',clean.read_text())
 def test_glossary_change_invalidates_polish_config(self):
  p=self.root/'terms.txt';p.write_text('WorkBuddy\n',encoding='utf-8')
  with patch.dict(os.environ,{'DEEPSEEK_TERMS_FILE':str(p)}):
   first=config();self.assertIn('不翻译成中文',first['prompt']);p.write_text('WorkBuddy\nMCP\n',encoding='utf-8');self.assertNotEqual(first,config())
 def test_alias_change_is_in_polish_cache_config(self):
  import json
  p=self.root/'aliases.json';p.write_text(json.dumps({'WorkBuddy':['work body']}),encoding='utf-8')
  with patch.dict(os.environ,{'DEEPSEEK_TERM_ALIASES_FILE':str(p)}):
   first=config();self.assertEqual(first['term_aliases']['WorkBuddy'],['work body']);p.write_text(json.dumps({'WorkBuddy':['work body','沃克 body']}),encoding='utf-8');self.assertNotEqual(first,config())
