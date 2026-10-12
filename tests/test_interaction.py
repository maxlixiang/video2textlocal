import asyncio,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_core import Fixture,FakeTelegram
from v2t.core import Failure,atomic_json,file_hash,media_dir
from v2t.manager import Manager
from v2t.presentation import filename,short_title,error_text
from v2t.telegram import FileBody,Telegram,UPLOAD_LIMIT

class Interaction(Fixture):
    def manager(self,t):
        return Manager(self.store,self.root/'results',self.root/'models',t,{7},service=lambda *a,**k:self.fail('complete video must skip downloading/GPU'),polisher=lambda *a:self.fail('video must not call DeepSeek'))
    def video(self,row):
        source=self.root/'media'/row['id'];source.mkdir(parents=True);p=source/'media.bin';p.write_bytes(b'fixed video')
        atomic_json(source/'media.json',{'sha256':file_hash(p),'has_video':True,'extension':'mp4','title':'律师如何低成本给Agent接上法律数据库？更多标题'})
    def test_video_button_owner_dedup_and_retry(self):
        row=self.task('douyin');t=FakeTelegram();m=self.manager(t)
        cb={'callback_query':{'id':'cb','from':{'id':8},'data':'video:'+row['id']}}
        asyncio.run(m.handle(cb));self.assertEqual(self.store.get(row['id'])['status'],'choice')
        cb['callback_query']['from']['id']=7
        asyncio.run(m.handle(cb));asyncio.run(m.handle(cb))
        self.assertEqual(self.store.get(row['id'])['mode'],'video');self.assertEqual(self.store.get(row['id'])['polish'],0)
        self.video(row);sent=[]
        def send(chat,path,name,caption,video):sent.append(name);raise Failure('send_failed')
        t.send_media=send;asyncio.run(m.process(self.store.claim()))
        self.assertEqual(self.store.get(row['id'])['error'],'send_failed')
        t.send_media=lambda chat,path,name,caption,video:sent.append(name) or 100
        self.store.enqueue(row['id'],7,False);asyncio.run(m.process(self.store.claim()))
        self.assertEqual(self.store.get(row['id'])['status'],'done');self.assertEqual(len(sent),2)
        self.assertTrue(sent[-1].endswith('_视频.mp4'));self.assertFalse((self.root/'results'/row['id']/'raw.json').exists())
    def test_three_choices_and_invalid_link_feedback(self):
        t=FakeTelegram();m=self.manager(t);row=self.task()
        choices=m.choices(row)['inline_keyboard'];self.assertEqual([b['callback_data'].split(':')[0] for r in choices for b in r],['video','raw','both','engine'])
        asyncio.run(m.handle({'message':{'from':{'id':7},'chat':{'id':9},'message_id':55,'text':'https://example.org/not-a-video'}}))
        self.assertIn('地址错误',t.statuses[-1][1]['text'])
    def test_title_safety_and_lengths(self):
        self.assertEqual(len(short_title('中'*40)),20)
        self.assertEqual(len(short_title(' '.join('word'+str(i) for i in range(20))).split()),10)
        for s in ['../../坏标题\n"|?*','CON','https://cdn.example/media?signature=secret']:
            n=filename(s,'原稿');self.assertFalse(any(c in n for c in '/\\\r\n"'));self.assertNotIn('signature',n)
    def test_streamed_multipart_and_upload_size_guard(self):
        p=self.root/'movie';p.write_bytes(b'x'*200000)
        body=FileBody(p,'中文_视频.mp4','video',{'chat_id':'7'},'video/mp4');parts=list(body)
        self.assertEqual(sum(map(len,parts)),body.length);self.assertLessEqual(max(map(len,parts[1:-1])),65536)
        with p.open('r+b') as f:f.truncate(UPLOAD_LIMIT+1)
        with patch('urllib.request.urlopen',side_effect=self.fail):
            with self.assertRaises(Failure) as exc:Telegram('test').send_media(7,p,'视频.mp4','',True)
        self.assertEqual(exc.exception.code,'send_too_large')
    def test_audio_only_youtube_cache_cannot_satisfy_video(self):
        from v2t.download import cached_media
        row=self.task();source=self.root/'media'/row['id'];source.mkdir(parents=True)
        p=source/'media.bin';p.write_bytes(b'audio-only');atomic_json(source/'media.json',{'sha256':file_hash(p),'has_video':False})
        with patch('v2t.download.probe',side_effect=self.fail):self.assertIsNone(cached_media(source,want_video=True))

    def test_polish_explicit_non_thinking_and_truncation_evidence(self):
        from v2t.polish import polish
        row=self.task();directory,models,raw=self.artifacts(row);calls=[]
        def truncated(url,payload,**kwargs):
            calls.append(payload)
            return {'choices':[{'finish_reason':'length','message':{'content':'partial'}}],'usage':{'completion_tokens':4096}}
        with self.assertRaises(Failure) as exc:polish(directory,raw,request=truncated,sleep=lambda _:None)
        self.assertEqual(exc.exception.code,'polish_truncated');self.assertEqual(calls[0]['thinking'],{'type':'disabled'})
        evidence=list((directory/'polish_blocks').glob('*.failure.json'));self.assertEqual(len(evidence),1)
        self.assertFalse(json.loads(evidence[0].read_text())['saved_as_complete']);self.assertFalse((directory/'polished.json').exists())
        cleaned=polish(directory,raw,request=lambda *a,**k:{'choices':[{'finish_reason':'stop','message':{'content':'测试整理稿。'}}]},sleep=lambda _:None)
        self.assertTrue(cleaned['segments'])
