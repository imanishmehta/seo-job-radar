"""Conservative, bounded adoption of employers discovered by search."""
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup

COUNTRIES = {'US':'United States','USA':'United States','GB':'United Kingdom','UK':'United Kingdom',
             'CA':'Canada','AU':'Australia','NZ':'New Zealand','DE':'Germany','IE':'Ireland',
             'SG':'Singapore','ZA':'South Africa','NL':'Netherlands','FR':'France','ES':'Spain',
             'PL':'Poland','PT':'Portugal','AE':'United Arab Emirates','BR':'Brazil','MX':'Mexico'}

def organizations(soup):
    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            types=value.get('@type', [])
            if isinstance(types,str): types=[types]
            if any(t in ('Organization','Corporation','LocalBusiness','ProfessionalService') for t in types):
                yield value
            # Do not mistake a job's hiringOrganization for the website owner.
            if '@graph' in value: yield from walk(value['@graph'])
    for script in soup.select('script[type="application/ld+json"]'):
        try: yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError): continue

def verify(candidate, fetcher):
    from crawl import ATS, CAREER, canonical, host, public_url
    url=candidate['url']; p=urlsplit(url)
    public_url(url)
    if p.scheme!='https' or p.query or p.fragment or host(url) in ATS:
        raise ValueError('Official HTTPS company page required')
    if any(host(url).endswith('.'+d) for d in ('bamboohr.com','recruitee.com','myworkdayjobs.com','applytojob.com','teamtailor.com')):
        raise ValueError('External hiring system needs company ownership review')
    home=p.scheme+'://'+p.netloc+'/'
    response=fetcher.page(home)
    if host(response.url)!=host(home): raise ValueError('Homepage redirects to another host')
    soup=BeautifulSoup(response.text,'html.parser')
    heading=' '.join(t.get_text(' ',strip=True) for t in soup.select('title,h1'))
    if re.search(r'job board|job portal|job search|jobs aggregator|recruitment agency|staffing agency',heading,re.I):
        raise ValueError('Possible intermediary; manual review required')
    career_links=[]
    for a in soup.select('a[href]'):
        link=urljoin(response.url,a['href']); lp=urlsplit(link)
        if host(link)==host(url) and CAREER.search(lp.path) and not lp.query and not lp.fragment:
            if canonical(url)==canonical(link) or p.path.startswith(lp.path.rstrip('/')+'/'):
                career_links.append(link)
    if not career_links: raise ValueError('Homepage does not link to this career section')
    organization=None; country=None
    for org in organizations(soup):
        if not isinstance(org.get('url'),str) or host(org['url'])!=host(home): continue
        address=org.get('address',{})
        if not isinstance(address,dict): continue
        c=address.get('addressCountry','')
        if isinstance(c,dict): c=c.get('name','')
        if not isinstance(c,str): continue
        c=COUNTRIES.get(c.upper(),c)
        if c in COUNTRIES.values() and isinstance(org.get('name'),str) and 2<=len(org['name'])<=100:
            organization=org;country=c;break
    if not organization: raise ValueError('Company identity or non-India address needs review')
    career=min(career_links,key=len)
    page=fetcher.page(career)
    if host(page.url)!=host(home): raise ValueError('Career section redirects outside company')
    if not CAREER.search(BeautifulSoup(page.text,'html.parser').get_text(' ',strip=True)):
        raise ValueError('Career page evidence missing')
    return {'id':host(home).replace('.','-')+'-'+hashlib.sha256(canonical(career).encode()).hexdigest()[:6],
            'name':organization['name'],'url':canonical(career),'country':country,
            'discovered_via':'Automatic: homepage career link and same-domain organization address',
            'verification':{'homepage':home,'career_link':career,'organization_url':organization['url'],'country':country}}

def adopt(discovery, sources, fetcher):
    from crawl import host, PORTALS
    known={host(s['url']) for s in sources}; pending=[]; added=[]; checked=0
    for item in discovery.get('candidates',[]):
        if host(item['url']) in known or any(host(item['url'])==d or host(item['url']).endswith('.'+d) for d in PORTALS): continue
        if checked>=6 or len(added)>=3:
            pending.append({**item,'status':'Pending next run: verification limit'});continue
        checked+=1
        try:
            company=verify(item,fetcher)
            sources.append(company);known.add(host(company['url']));added.append(company)
        except Exception as exc:
            reason=str(exc) if isinstance(exc,ValueError) else 'Page could not be verified; manual review required'
            pending.append({**item,'status':reason})
    discovery['candidates']=sorted(pending,key=lambda c: not c['status'].startswith('Pending next run'))
    discovery['auto_added']=[{'name':s['name'],'url':s['url']} for s in added]
    discovery['auto_add_enabled']=True
    discovery['message']=f'{len(added)} employers automatically added this run. Official homepage links and company address evidence are required; uncertain pages stay in review. Maximum 3 additions per run.'
    return added
