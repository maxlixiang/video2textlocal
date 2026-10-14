import unittest
from unittest.mock import patch
from v2t.adapter_download import media_url
from v2t.browser_policy import browser_url
from v2t.core import Failure

class RedirectHost(unittest.TestCase):
 def test_exact_observed_host_allowed_with_global_dns(self):
  resolve=lambda *a,**k:[(2,1,6,'',('1.1.1.1',443))]
  url='https://ttby.v.smtcdns.com/fixture'
  with patch('socket.getaddrinfo',side_effect=resolve):self.assertEqual(media_url(url,{}),url)
  self.assertEqual(browser_url(url,resolver=resolve),url)
 def test_new_cdn_hosts_allowed_private_addresses_still_blocked(self):
  resolve=lambda *a,**k:[(2,1,6,'',('1.1.1.1',443))]
  for host in ('new-cdn.example','smtcdns.com','extra.ttby.v.smtcdns.com'):
   with patch('socket.getaddrinfo',side_effect=resolve):
    self.assertEqual(media_url('https://'+host+'/fixture',{}),'https://'+host+'/fixture')
  resolve=lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))]
  with patch('socket.getaddrinfo',side_effect=resolve),self.assertRaises(Failure):media_url('https://ttby.v.smtcdns.com/fixture',{'allow_fake_ip_dns':True})
  with self.assertRaises(Failure):browser_url('https://ttby.v.smtcdns.com/fixture',True,resolve)
 def test_fake_ip_requires_existing_explicit_switch(self):
  resolve=lambda *a,**k:[(2,1,6,'',('198.18.0.1',443))]
  url='https://ttby.v.smtcdns.com/fixture'
  with patch('socket.getaddrinfo',side_effect=resolve):
   with self.assertRaises(Failure):media_url(url,{})
   self.assertEqual(media_url(url,{'allow_fake_ip_dns':True}),url)
