import os,unittest
from unittest.mock import patch
from v2t.net import address_allowed,public_url
from v2t.browser_policy import browser_url
from v2t.adapter_download import media_url
from v2t.core import Failure,parse_target

class FakeIPPolicy(unittest.TestCase):
 def test_full_fake_range_explicit_only(self):
  for address in ('198.18.0.0','198.18.1.3','198.19.255.255'):
   self.assertFalse(address_allowed(address));self.assertTrue(address_allowed(address,True))
  for address in ('198.17.255.255','198.20.0.0'):self.assertEqual(address_allowed(address),address_allowed(address,True))
 def test_private_loopback_link_local_ipv6_multicast_still_denied(self):
  for address in ('192.168.1.1','10.1.2.3','172.16.0.1','127.0.0.1','169.254.169.254','0.0.0.0','224.0.0.1','::1','fc00::1','fe80::1','ff02::1','::ffff:192.168.1.1'):
   self.assertFalse(address_allowed(address,True),address)
 def test_unknown_host_fake_ip_allowed_across_three_paths(self):
  resolver=lambda *a,**k:[(2,1,6,'',('198.19.2.3',443))]
  url='https://unknown-cdn.example/fixture'
  with patch('socket.getaddrinfo',side_effect=resolver),patch.dict(os.environ,{'ALLOW_FAKE_IP_DNS':'1'}):
   self.assertEqual(public_url(url),url);self.assertEqual(media_url(url,{'allow_fake_ip_dns':True}),url)
  self.assertEqual(browser_url(url,True,resolver),url)
 def test_mixed_fake_and_private_dns_denied(self):
  resolver=lambda *a,**k:[(2,1,6,'',(ip,443)) for ip in ('198.18.0.1','192.168.1.1')]
  with patch('socket.getaddrinfo',side_effect=resolver),patch.dict(os.environ,{'ALLOW_FAKE_IP_DNS':'1'}):
   with self.assertRaises(Failure):public_url('https://cdn.example/')
  with self.assertRaises(Failure):browser_url('https://cdn.example/',True,resolver)
 def test_user_inputs_still_limited_to_video_platforms(self):
  for url in ('https://unknown-cdn.example/video','http://192.168.1.1/','http://198.18.0.1/'):
   with self.assertRaises(Failure):parse_target(url)
