import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from auto_company import verify, adopt

class AutoCompanyTests(unittest.TestCase):
    def fetcher(self, country='US', linked=True, orgurl='https://employer.example'):
        org={'@type':'Organization','name':'Employer','url':orgurl,'address':{'addressCountry':country}}
        body='<title>Employer marketing</title><script type="application/ld+json">'+json.dumps(org)+'</script>'
        if linked: body+='<a href="/careers">Careers</a>'
        pages={'https://employer.example/':body,'https://employer.example/careers':'<h1>Careers at Employer</h1>'}
        return SimpleNamespace(page=lambda url:SimpleNamespace(url=url,text=pages[url]))

    @patch('crawl.public_url')
    def test_verified_company_added(self,_):
        company=verify({'url':'https://employer.example/careers/seo'},self.fetcher())
        self.assertEqual(company['country'],'United States')
        self.assertEqual(company['url'],'https://employer.example/careers')

    @patch('crawl.public_url')
    def test_unverified_evidence_rejected(self,_):
        for f in [self.fetcher(country='IN'),self.fetcher(country=''),self.fetcher(linked=False),self.fetcher(orgurl='https://another.example')]:
            with self.subTest(fetcher=f),self.assertRaises(ValueError):
                verify({'url':'https://employer.example/careers/seo'},f)

    @patch('auto_company.verify')
    def test_dedupe_limits_and_review(self,verify_mock):
        verify_mock.side_effect=lambda item,_:{'name':'Employer','url':item['url'],'country':'United States'}
        d={'candidates':[{'url':f'https://e{i}.example/careers'} for i in range(7)]}
        sources=[{'url':'https://e0.example/careers'}]
        added=adopt(d,sources,None)
        self.assertEqual(len(added),3)
        self.assertEqual(len(sources),4)
        self.assertEqual(len(d['candidates']),3)

    @patch('auto_company.verify',side_effect=ValueError('Company identity needs review'))
    def test_failure_keeps_review(self,_):
        d={'candidates':[{'url':'https://employer.example/careers'}]}
        sources=[]
        self.assertEqual(adopt(d,sources,None),[])
        self.assertIn('needs review',d['candidates'][0]['status'])
        self.assertEqual(sources,[])

if __name__=='__main__': unittest.main()
