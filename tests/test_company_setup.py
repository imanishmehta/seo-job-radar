import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from add_company import parse_request, validate_request
import crawl

class CompanySetupTests(unittest.TestCase):
    def test_stranger_cannot_add_company(self):
        event={'issue':{'user':{'login':'stranger'},'title':'[Add company] Example'},'sender':{'login':'stranger'}}
        with self.assertRaises(ValueError):parse_request(event,'imanishmehta')
    def test_owner_request_parsed_as_data(self):
        event={'issue':{'user':{'login':'imanishmehta'},'title':'[Add company] Example','body':'```json\n{"name":"Example", "url":"https://example.com/careers", "country":"Canada"}\n```'},'sender':{'login':'imanishmehta'}}
        self.assertEqual(parse_request(event,'imanishmehta')['country'],'Canada')
    def test_nonowner_edit_is_rejected(self):
        event={'issue':{'user':{'login':'imanishmehta'},'title':'[Add company] Example'},'sender':{'login':'stranger'}}
        with self.assertRaises(ValueError):parse_request(event,'imanishmehta')
    def test_url_credentials_and_queries_are_rejected(self):
        for u in ['https://example.com/careers?token=secret','https://example.com/careers#secret','http://example.com/careers']:
            with self.assertRaises(ValueError):validate_request({'name':'Example','url':u,'country':'Canada'})
    @patch('add_company.public_url')
    def test_reject_ats_as_company_source(self,_):
        with self.assertRaises(ValueError):validate_request({'name':'Example','url':'https://jobs.ashbyhq.com/careers','country':'Canada'})
    @patch('add_company.public_url')
    def test_stable_company_id(self,_):
        row={'name':'Example','url':'https://example.com/careers','country':'Canada'}
        self.assertEqual(validate_request(row)['id'],validate_request(row)['id'])
    def test_key_alone_never_enables_paid_search(self):
        with patch.dict('os.environ',{'SERPER_API_KEY':'test-key','ENABLE_GOOGLE_DISCOVERY':'false'}),patch('crawl.requests.post') as post:
            self.assertEqual(crawl.discover()['status'],'free_mode')
            post.assert_not_called()
    def test_no_key_is_free_even_with_opt_in(self):
        with patch.dict('os.environ',{'SERPER_API_KEY':'','ENABLE_GOOGLE_DISCOVERY':'true'}),patch('crawl.requests.post') as post:
            self.assertEqual(crawl.discover()['status'],'free_mode')
            post.assert_not_called()

if __name__=='__main__':unittest.main()
