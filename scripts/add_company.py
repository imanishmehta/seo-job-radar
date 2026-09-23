"""Accept an owner-confirmed company through GitHub, without browser credentials."""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from crawl import ROOT, ATS, CAREER, Fetcher, canonical, host, public_url

def parse_request(event, owner):
    if 'issue' in event:
        issue = event['issue']
        if issue.get('user', {}).get('login') != owner or event.get('sender', {}).get('login') != owner:
            raise ValueError('Only the repository owner can add companies')
        if not issue.get('title', '').startswith('[Add company]'):
            raise ValueError('Not a company request')
        match = re.search(r'```json\s*(.*?)\s*```', issue.get('body') or '', re.S)
        if not match:
            raise ValueError('Missing company JSON')
        return json.loads(match.group(1))
    if event.get('sender', {}).get('login') != owner:
        raise ValueError('Only the repository owner can add companies')
    inputs=event.get('inputs',{})
    return {'name':inputs.get('company_name'),'url':inputs.get('career_url'),'country':inputs.get('company_country')}

def validate_request(values):
    name=str(values.get('name') or '').strip()
    country=str(values.get('country') or '').strip()
    url=str(values.get('url') or '').strip()
    if not 2 <= len(name) <= 100 or not 2 <= len(country) <= 80:
        raise ValueError('Provide a company name and home country')
    if country.lower() in ('india','in','ind'):
        raise ValueError('This watchlist is for companies based outside India')
    p=urlsplit(url)
    if len(url)>1000 or p.scheme!='https' or p.query or p.fragment:
        raise ValueError('Use the public HTTPS career-page URL without query parameters or fragments')
    public_url(url)
    if host(url) in ATS or any(host(url).endswith('.'+d) for d in ['bamboohr.com','recruitee.com','myworkdayjobs.com','applytojob.com','teamtailor.com']):
        raise ValueError('Start at the company website, not its external hiring-system URL')
    if not CAREER.search(p.path):
        raise ValueError('Provide the company career / jobs page')
    return {'id':host(url).replace('.','-')+'-'+hashlib.sha256(canonical(url).encode()).hexdigest()[:6],
            'name':name,'url':canonical(url),'country':country,'discovered_via':'Owner-confirmed career page'}

def main():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    owner=os.environ['GITHUB_REPOSITORY_OWNER']
    company=validate_request(parse_request(event,owner))
    # Verify a live same-host page. A blocked site needs manual review, not blind adoption.
    response=Fetcher().page(company['url'])
    if host(response.url)!=host(company['url']):
        raise ValueError('Career URL redirected to a different host; review it first')
    path=ROOT/'sources.json'; sources=json.loads(path.read_text())
    if any(host(s['url'])==host(company['url']) for s in sources):
        print('Company already monitored; no duplicate added')
        return
    sources.append(company)
    path.write_text(json.dumps(sources,indent=2,ensure_ascii=False)+'\n')
    print('Added company:',company['name'])

if __name__=='__main__':
    main()
