import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import crawl

class ClassificationTests(unittest.TestCase):
    def test_us_remote_is_not_worldwide(self):
        self.assertEqual(crawl.classify('SEO Manager','United States','Fully remote. Work from anywhere.','Remote')[1],'Restricted')
    def test_india_remote(self):
        self.assertEqual(crawl.classify('Remote SEO Strategist - India','Delhi','Work with clients in the United States.','remote')[1],'India eligible')
    def test_remote_without_country_is_unknown(self):
        self.assertEqual(crawl.classify('SEO Specialist','Remote','We are looking for a specialist.','Remote')[1],'Unclear')
    def test_residency_overrides_global_slogan(self):
        self.assertEqual(crawl.classify('SEO Lead','Worldwide','Work from anywhere in the world.\nCandidates must be based in the United States.','Remote')[1],'Restricted')
    def test_timezone_is_not_residency(self):
        self.assertEqual(crawl.classify('SEO Specialist','Worldwide','Must work US business hours.','Remote')[1],'Worldwide')
    def test_pronoun_us_is_not_united_states(self):
        self.assertEqual(crawl.classify('SEO Specialist','Anywhere','Work with us. Only talented applicants should apply.','Remote')[1],'Worldwide')
    def test_nonremote_does_not_get_india_label(self):
        self.assertEqual(crawl.classify('SEO Specialist','India','Work at our office.','Hybrid')[1],'Unclear')
    def test_multiple_employment_types(self):
        self.assertEqual(crawl.employment('Contractor Full-Time',''),['Full-time','Contract'])
    def test_posted_date_is_never_invented(self):
        j=crawl.make_job({'id':'a','name':'A','url':'https://example.com/careers'},'SEO Specialist','https://example.com/careers/seo','A remote SEO specialist role. '*15)
        self.assertIsNone(j['date_posted'])
    def test_explicit_expiry(self):
        j=crawl.make_job({'id':'a','name':'A','url':'https://example.com/careers'},'SEO Specialist','https://example.com/careers/seo','A remote SEO specialist role. '*15,expires='2020-01-01')
        self.assertEqual(j['status'],'closed')
    def test_source_failure_preserves_history_but_hides_active(self):
        old={'id':'j','source_id':'a','status':'active','first_seen':'2025-01-01','last_verified':'2025-01-02'}
        with patch.object(crawl.Fetcher,'page',side_effect=RuntimeError('Blocked')):
            report,jobs=crawl.crawl_source({'id':'a','name':'A','url':'https://example.com/careers'},{'j':old})
        self.assertEqual(report['status'],'error')
        self.assertEqual(jobs[0]['status'],'needs_check')
        self.assertEqual(jobs[0]['last_verified'],'2025-01-02')
        self.assertEqual(jobs[0]['first_seen'],'2025-01-01')
    def test_internal_urls_rejected(self):
        for u in ['http://127.0.0.1/test','http://169.254.169.254/latest/meta-data','file:///tmp/a','https://example.com:9999/a']:
            with self.assertRaises(ValueError):
                crawl.public_url(u)
    def test_generic_career_heading_is_not_a_job(self):
        response=type('Response',(),{'url':'https://example.com/careers','text':'<h1>SEO Careers with Example</h1><p>Remote jobs. '+('Helpful text '*30)+'</p><button>Apply now</button>'})()
        self.assertEqual(crawl.parse_html({'id':'a','name':'A','url':response.url},response),[])
    def test_nested_jsonld(self):
        soup=crawl.BeautifulSoup('<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"SEO Specialist"}]}</script>','html.parser')
        self.assertEqual(next(crawl.job_schema(soup))['title'],'SEO Specialist')

if __name__=='__main__':
    unittest.main()
