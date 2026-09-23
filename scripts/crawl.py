"""Read employer career pages. Never ingest job aggregators.

Only a live employer page or its linked ATS can verify a listing. A failed fetch
does not mean a vacancy is closed. Persist first_seen separately from date_posted.
"""
import argparse
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'site/data/jobs.json'
NOW = datetime.now(timezone.utc).isoformat()
SEO = re.compile(r'\bseo\b|search engine optimi[sz]ation|organic (?:search|growth)|link.building|\b[ag]eo\b.*(?:strategist|specialist|manager)', re.I)
CAREER = re.compile(r'career|vacanc|job|join.our.team|work.with.us|opportunit', re.I)
CLOSED = re.compile(r'(?:this|the) (?:job|position|role|vacancy) (?:is |has been |was )?(?:no longer available|closed|filled)|no longer accepting applications|job not found|position has been filled', re.I)
PORTALS = {'linkedin.com','indeed.com','glassdoor.com','ziprecruiter.com','jobgether.com','workingnomads.com','remoterocketship.com','arc.dev','weworkremotely.com','wellfound.com','himalayas.app','dailyremote.com','flexjobs.com','remote.co','nodesk.co','builtin.com','jobstreet.com','reddit.com','facebook.com','quora.com','wfh.team','heyremote.io','digitalmarketing.jobs','laborx.com','seojobs.com','upwork.com','dynamitejobs.com','fiverr.com','freelancer.com','remoteok.com'}
ATS = {'jobs.lever.co','jobs.eu.lever.co','boards.greenhouse.io','job-boards.greenhouse.io','boards.eu.greenhouse.io','jobs.ashbyhq.com','jobs.jobvite.com','apply.workable.com'}

def text(value):
    soup = BeautifulSoup(html.unescape(str(value or '')), 'html.parser')
    for tag in soup.select('script,style,nav,footer,header,noscript,[id*=cookie],[class*=cookie],[id*=Cookie],[class*=Cookie]'):
        tag.decompose()
    return re.sub(r'[ \t\xa0]+', ' ', soup.get_text('\n', strip=True)).strip()

def host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')

def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip('/') or '/', p.query, ''))

def public_url(url):
    p = urlsplit(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username is not None or p.password is not None or p.port not in (None,80,443):
        raise ValueError('Unsupported URL')
    if any(not ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname, p.port or 443)):
        raise ValueError('Non-public destination')
    if any(host(url) == d or host(url).endswith('.'+d) for d in PORTALS):
        raise ValueError('Job portal excluded')

class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'SEOJobRadar/1.0 (+https://github.com/imanishmehta/seo-job-radar)'
        self.robots = {}
        self.cache = {}

    def get(self, url, robots=True):
        if url in self.cache:
            return self.cache[url]
        public_url(url)
        origin = urlsplit(url).scheme + '://' + urlsplit(url).netloc
        if robots:
            if origin not in self.robots:
                try:
                    rr = self.get(origin+'/robots.txt', robots=False)
                    if rr.status_code in (401,403,429) or rr.status_code >= 500:
                        raise RuntimeError('robots.txt unavailable')
                    rp = RobotFileParser()
                    rp.parse(rr.text.splitlines() if rr.status_code == 200 else [])
                    self.robots[origin] = rp
                except requests.RequestException as e:
                    raise RuntimeError('robots.txt unavailable') from e
            if not self.robots[origin].can_fetch('SEOJobRadar', url):
                raise RuntimeError('Blocked by robots.txt')
        current = url
        for _ in range(6):
            public_url(current)
            response = self.session.get(current, timeout=(8,25), allow_redirects=False)
            if response.is_redirect:
                current = urljoin(current,response.headers['Location'])
                continue
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(1)
                response = self.session.get(current, timeout=(8,25), allow_redirects=False)
            if response.is_redirect:
                raise RuntimeError('Unexpected retry redirect')
            if len(response.content) > 8_000_000:
                raise RuntimeError('Page exceeds crawl limit')
            self.cache[url] = response
            return response
        raise RuntimeError('Too many redirects')

    def page(self, url):
        r = self.get(url)
        r.raise_for_status()
        return r

    def api(self, url):
        # Documented public job feeds are APIs, not HTML crawl targets.
        r = self.get(url, robots=False)
        r.raise_for_status()
        return r

def date(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.replace(tzinfo=d.tzinfo or timezone.utc).isoformat()
    except (ValueError,TypeError):
        for fmt in ('%m/%d/%Y','%B %d, %Y','%d %B %Y'):
            try:
                return datetime.strptime(str(value).strip(),fmt).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass
        return None

def classify(title, location, description, workplace=''):
    """Conservative labels; never equate remote with worldwide eligibility."""
    body = title+'\n'+description
    evidence = []
    lines = [l.strip() for l in (location+'\n'+body).splitlines() if l.strip()]
    for line in lines:
        if re.search(r'remote|work.from.home|worldwide|anywhere|must.*(?:based|resid|locat)|eligible|India|time.zone',line,re.I):
            evidence.append(line[:400])
    remote = 'Unclear'
    if re.search(r'hybrid|on.?site|in.office',workplace,re.I):
        remote = 'Hybrid / onsite'
    elif workplace.lower() in ('remote','telecommute') or re.search(r'\bremote\b|work.from.home|work.from.anywhere',location+' '+body,re.I):
        remote = 'Remote'
    # Job-specific mandatory residency wins over general company-wide slogans.
    residency = [l for l in lines if re.search(r'(?:must|only|require|restricted|eligible|based|resid|located)',l,re.I) and re.search(r'United States|(?-i:\bUS\b)|\bUSA\b|\bUK\b|United Kingdom|Canada|Europe|EMEA|Philippines|Australia|South Africa|Latin America',l,re.I) and not re.search(r'time.zone|business.hours|working.hours|overlap|clients|customers',l,re.I)]
    blocked_india = re.search(r'(?:not|no|excluding|except)\s+(?:eligible.*?from\s+)?India',body,re.I)
    india_loc = re.search(r'\bIndia\b|\bDelhi\b|\bMumbai\b|\bBengaluru\b|\bBangalore\b',location+' '+title,re.I)
    global_loc = re.search(r'worldwide|anywhere|global|all countries', location,re.I)
    if blocked_india or (residency and not india_loc):
        eligibility = 'Restricted'
    elif india_loc:
        eligibility = 'India eligible'
    elif location and location.lower().strip() not in ('remote','not specified','multiple locations') and not global_loc:
        eligibility = 'Restricted' if re.search(r'United States|(?-i:\bUS\b)|\bUSA\b|\bUK\b|United Kingdom|Canada|Europe|EMEA|Philippines|Australia|South Africa|Toronto|Vancouver|New York|Boston|Spain|Germany|LATAM|Latin America|Mexico|Brazil|Jamaica|Tokyo',location,re.I) else 'Unclear'
    elif global_loc or re.search(r'(?:work|hiring|hire|applicants|candidates|team members).{0,45}(?:anywhere in the world|worldwide|from anywhere)|100% remote.{0,30}anywhere',body,re.I):
        eligibility = 'Worldwide'
    else:
        eligibility = 'Unclear'
    if remote != 'Remote':
        eligibility = 'Unclear'
    return remote, eligibility, list(dict.fromkeys(evidence))[:8]

def employment(value, description):
    v = (value or '').lower().replace('_',' ').replace('-',' ')
    vals = []
    for pattern, label in [(r'full\s*time','Full-time'),(r'part\s*time','Part-time'),(r'contract|freelanc','Contract'),(r'\bintern(?:ship)?\b','Internship'),(r'temporary','Temporary')]:
        if re.search(pattern,v or description[:1800],re.I):
            vals.append(label)
    return vals or ['Not specified']

def make_job(source, title, url, description, location='', kind='', posted=None, workplace='', salary='', expires=None, proof=''):
    if not SEO.search(title or ''):
        return None
    description = text(description)
    if len(description) < 120:
        return None
    remote, eligibility, evidence = classify(title,location,description,workplace)
    if remote == 'Hybrid / onsite':
        return None
    expiry = date(expires)
    status = 'closed' if CLOSED.search(description) or (expiry and expiry < NOW) else 'active'
    return {'id':hashlib.sha256(canonical(url).encode()).hexdigest()[:20], 'source_id':source['id'],
        'company':source['name'],'company_country':source.get('country','Unverified'),
        'title':text(title),'url':canonical(url),'career_url':source['url'],
        'location':location or 'Not specified','remote':remote,'eligibility':eligibility,
        'employment':employment(kind,description),'salary':salary or 'Not listed',
        'date_posted':date(posted),'valid_through':expiry,'first_seen':NOW,'last_verified':NOW,
        'last_checked':NOW,'status':status,'description':description[:24000],
        'evidence':evidence,'verification':proof,'status_reason':'Live employer listing checked' if status=='active' else 'Employer marks this listing closed or expired'}

def job_schema(soup):
    def walk(value):
        if isinstance(value,dict):
            if 'JobPosting' in ([value.get('@type')] if isinstance(value.get('@type'),str) else value.get('@type',[]) or []):
                yield value
            for k,v in value.items():
                if k != 'description':
                    yield from walk(v)
        elif isinstance(value,list):
            for v in value:
                yield from walk(v)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):
            continue

def locations(value):
    if isinstance(value,list):
        return '; '.join(filter(None,(locations(v) for v in value)))
    if isinstance(value,dict):
        if 'address' in value:
            return locations(value['address'])
        return ', '.join(str(value[k]) for k in ['addressLocality','addressRegion','addressCountry','name'] if value.get(k) and isinstance(value[k],str))
    return str(value or '')

def parse_html(source, response, hint=''):
    soup = BeautifulSoup(response.text,'html.parser')
    schemas = list(job_schema(soup))
    found = []
    if schemas:
        for s in schemas:
            url = urljoin(response.url, s.get('url') or response.url)
            if host(url) != host(response.url):
                url = response.url
            salary = s.get('baseSalary',{})
            if isinstance(salary,dict):
                value=salary.get('value',{})
                salary=' '.join(str(v) for v in [salary.get('currency'),value.get('minValue') if isinstance(value,dict) else value,'to' if isinstance(value,dict) and value.get('maxValue') else None,value.get('maxValue') if isinstance(value,dict) else None,value.get('unitText') if isinstance(value,dict) else None] if v) or ''
            job=make_job(source,s.get('title',''),url,s.get('description',''),locations(s.get('applicantLocationRequirements')) or locations(s.get('jobLocation')),str(s.get('employmentType','')),s.get('datePosted'),s.get('jobLocationType',''),str(salary or ''),s.get('validThrough'),'Employer JobPosting structured data and live page')
            if job:
                found.append(job)
    else:
        heading=soup.find('h1')
        title=text(heading) if heading else hint
        main=soup.find('main') or soup.find('article') or soup
        description=text(main)
        apply=any(re.search(r'apply|submit.*(?:resume|application)|send.*(?:cv|resume)', a.get_text(' ',strip=True),re.I) for a in soup.select('a,button')) or bool(soup.select('input[type="file"],form[action*="apply"]'))
        if SEO.search(title or '') and apply and not re.search(r'\bcareers?\b|\bjobs\b|open positions',title,re.I):
            description=re.split(r'\n(?:More roles|Related openings)\n',description,maxsplit=1,flags=re.I)[0]
            loc=re.search(r'(?:Location|Based in)\s*[:\n]\s*:?\s*([^\n]{2,100})',description,re.I)
            lead=description.splitlines()[:12]
            location=loc.group(1) if loc else next((line for line in lead if re.fullmatch(r'United Kingdom|United States|Canada|Australia|Singapore|Germany|South Africa|Worldwide|Global|India|Remote',line,re.I)), '')
            workplace=next((line for line in lead if re.fullmatch(r'Hybrid|On.?site|Remote',line,re.I)), '')
            posted=re.search(r'Date Posted\s*:\s*([^\n]{2,40})',description,re.I)
            kind=re.search(r'Job Type\s*:\s*([^\n]{2,60})',description,re.I)
            job=make_job(source,title,response.url,description,location,kind.group(1) if kind else '',posted.group(1) if posted else None,workplace=workplace,proof='Live employer role page with application control')
            if job:
                found.append(job)
    return found

def ats_board(url):
    p=urlsplit(url); bits=p.path.strip('/').split('/')
    if p.hostname in ATS and bits and bits[0]:
        return p.scheme+'://'+p.netloc+'/'+bits[0]
    return None

def read_ats(fetch, source, board):
    h=host(board); slug=urlsplit(board).path.strip('/'); jobs=[]
    proof='Employer career page links to this ATS; current published job feed checked'
    if h in ('jobs.lever.co','jobs.eu.lever.co'):
        api='https://api.eu.lever.co' if '.eu.' in h else 'https://api.lever.co'
        raw=[]
        for skip in range(0,1000,100):
            batch=fetch.api(f'{api}/v0/postings/{slug}?mode=json&limit=100&skip={skip}').json()
            if not isinstance(batch,list):
                raise RuntimeError('Invalid Lever feed')
            raw.extend(batch)
            if len(batch)<100:
                break
        else:
            raise RuntimeError('Lever pagination limit reached')
        for j in raw:
            c=j.get('categories',{})
            desc=j.get('descriptionPlain') or j.get('description','')
            desc+='\n'+'\n'.join(x.get('text','')+'\n'+text(x.get('content','')) for x in j.get('lists',[]))+'\n'+text(j.get('additional',''))
            pay=j.get('salaryRange') or {}
            salary=' '.join(str(pay.get(k,'')) for k in ['currency','min','max','interval']).strip()
            jobs.append(make_job(source,j.get('text',''),j['hostedUrl'],desc,c.get('location',''),c.get('commitment',''),None,j.get('workplaceType',''),salary,proof=proof))
    elif 'greenhouse.io' in h:
        raw=fetch.api(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true').json()['jobs']
        for j in raw:
            # updated_at is NOT date posted.
            jobs.append(make_job(source,j['title'],j['absolute_url'],j.get('content',''),j.get('location',{}).get('name',''),proof=proof))
    elif h=='jobs.ashbyhq.com':
        raw=fetch.api(f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true').json()['jobs']
        for j in raw:
            if not j.get('isListed',True):
                continue
            loc='; '.join([j.get('location','')]+[l.get('location','') for l in j.get('secondaryLocations',[])])
            jobs.append(make_job(source,j['title'],j['jobUrl'],j.get('descriptionPlain') or j.get('descriptionHtml',''),loc,j.get('employmentType',''),j.get('publishedAt'),j.get('workplaceType','Remote' if j.get('isRemote') else ''),j.get('compensation',{}).get('scrapeableCompensationSalarySummary',''),proof=proof))
    else:
        return None
    return [j for j in jobs if j]

def crawl_source(source, previous):
    fetch=Fetcher(); result={'id':source['id'],'name':source['name'],'url':source['url'],'country':source.get('country','Unverified'),'last_checked':NOW,'status':'ok','jobs':0,'errors':[],'pages_checked':0}
    found={}; complete_boards=set()
    try:
        initial=fetch.page(source['url'])
        if host(initial.url)!=host(source['url']) and host(initial.url) not in ATS:
            raise RuntimeError('Career page redirected to an unapproved website')
        queue=[(initial.url,initial)]; visited=set(); boards=set()
        while queue and len(visited)<18:
            url,response=queue.pop(0)
            if canonical(url) in visited:
                continue
            visited.add(canonical(url))
            if response is None:
                try:
                    response=fetch.page(url)
                except Exception as e:
                    result['errors'].append(f'{url}: {type(e).__name__}: {e}')
                    continue
            result['pages_checked']+=1
            for job in parse_html(source,response):
                found[job['id']]=job
            soup=BeautifulSoup(response.text,'html.parser')
            links=[(urljoin(response.url,a.get('href') or a.get('src') or ''),a.get_text(' ',strip=True)) for a in soup.select('a[href],iframe[src],script[src]')]
            # Includes ATS URLs embedded in scripts without trusting external search results.
            links += [(html.unescape(u).replace('\\/','/'),'') for u in re.findall(r'https?://(?:jobs\.lever\.co|jobs\.eu\.lever\.co|job-boards\.greenhouse\.io|boards\.greenhouse\.io|jobs\.ashbyhq\.com)/[a-zA-Z0-9_-]+',response.text)]
            board_self=ats_board(response.url)
            if board_self:
                links.insert(0,(board_self,''))
            links.sort(key=lambda item: not bool(SEO.search(item[1]+' '+urlsplit(item[0]).path)))
            for link,label in links:
                board=ats_board(link)
                if board and board not in boards:
                    boards.add(board)
                    try:
                        aj=read_ats(fetch,source,board)
                        if aj is not None:
                            complete_boards.add(board)
                            for job in aj:
                                found[job['id']]=job
                        elif canonical(link) not in visited and len(queue)<25:
                            queue.append((link,None))
                    except Exception as e:
                        result['errors'].append(f'{board}: {type(e).__name__}: {e}')
                # Generic detail links only from employer or employer-linked ATS.
                allowed=host(link)==host(source['url']) or (board and board in boards)
                relevant=(CAREER.search(urlsplit(link).path) and (SEO.search(label+' '+urlsplit(link).path) or len(visited)==1)) or (board and SEO.search(label))
                if allowed and canonical(link) not in visited and len(queue)<25 and relevant and not urlsplit(link).path.endswith(('.pdf','.jpg','.png')):
                    if not board or board not in complete_boards:
                        if SEO.search(label):
                            queue.insert(0,(link,None))
                        else:
                            queue.append((link,None))
        if queue:
            result['errors'].append('Crawl page limit reached; some linked pages were not checked.')
        # Confirm job detail remains reachable; a failed check is not an active job.
        for job in found.values():
            try:
                r=fetch.get(job['url'])
                if r.status_code in (404,410):
                    job.update(status='closed',status_reason=f'Employer job page returned {r.status_code}')
                else:
                    r.raise_for_status()
                    page_text=text(r.text)
                    if CLOSED.search(page_text):
                        job.update(status='closed',status_reason='Employer page says applications are closed')
                    elif canonical(r.url)!=canonical(job['url']) and not SEO.search(text(BeautifulSoup(r.text,'html.parser').find('h1'))):
                        raise RuntimeError('Job page redirects without a matching role')
            except Exception as e:
                job.update(status='needs_check',last_verified=previous.get(job['id'],{}).get('last_verified'),status_reason=f'Job detail could not be verified: {type(e).__name__}')
        for jid,old in previous.items():
            if old['source_id']!=source['id'] or jid in found:
                continue
            j=dict(old); j['last_checked']=NOW
            if any(canonical(j['url']).startswith(b+'/') for b in complete_boards):
                j.update(status='closed',status_reason='Removed from employer’s complete published job feed')
            elif old['status']!='closed':
                try:
                    r=fetch.get(j['url'])
                    if r.status_code in (404,410) or (r.ok and CLOSED.search(text(r.text))):
                        j.update(status='closed',status_reason='Employer removed or closed the job page')
                    else:
                        j.update(status='needs_check',status_reason='Not found during the current career-page crawl')
                except Exception:
                    j.update(status='needs_check',status_reason='Could not recheck the previous listing')
            found[jid]=j
        result['status']='partial' if result['errors'] else 'ok'
        if not found and not complete_boards:
            result['status']='limited'
            result['errors'].append('No readable SEO job detail found. This is not proof the company has no vacancies.')
    except Exception as e:
        result['status']='error'; result['errors'].append(f'{type(e).__name__}: {e}')
        for jid,old in previous.items():
            if old['source_id']==source['id']:
                j=dict(old)
                if j['status']!='closed':
                    j.update(status='needs_check',status_reason='Career source unavailable; previous verification retained',last_checked=NOW)
                found[jid]=j
    for jid,j in found.items():
        if jid in previous:
            j['first_seen']=previous[jid]['first_seen']
    result['jobs']=sum(j['status']=='active' for j in found.values())
    return result,list(found.values())

def discover():
    """Optional Google discovery via Serper. Results are candidates, never jobs."""
    key=os.getenv('SERPER_API_KEY')
    enabled=os.getenv('ENABLE_GOOGLE_DISCOVERY','').lower()=='true'
    if not enabled or not key:
        return {'status':'free_mode','provider':'Official career-page watchlist','google_enabled':False,
                'message':'Free mode: monitored employer career pages are checked every 6 hours. Use country search shortcuts and Add company to expand coverage. No paid search requests are made.',
                'checked_at':NOW,'candidates':[]}
    candidates=[]; errors=[]
    # Free Serper accounts reject some quoted / advanced query patterns.
    # Keep search plain; enforce employer-only sources on returned URLs.
    regions=['United States','United Kingdom','Canada','Australia','Germany','Singapore','Ireland','Netherlands']
    region=regions[int(datetime.now(timezone.utc).timestamp()//21600)%len(regions)]
    queries=[f'SEO agency careers remote {region}', f'SEO remote contract careers {region}',
             f'SEO part time join our team {region}', 'SEO worldwide company careers']
    for query in queries:
        try:
            r=requests.post('https://google.serper.dev/search',headers={'X-API-KEY':key},json={'q':query,'num':10},timeout=25)
            r.raise_for_status()
            for item in r.json().get('organic',[]):
                u=item.get('link','')
                if not u or any(host(u)==d or host(u).endswith('.'+d) for d in PORTALS) or host(u) in ATS:
                    continue
                if CAREER.search(urlsplit(u).path):
                    candidates.append({'url':u,'title':item.get('title',''),'status':'Employer ownership needs review'})
        except Exception as e:
            errors.append(type(e).__name__)
    return {'status':'partial' if errors else 'ok','provider':'Google via Serper','checked_at':NOW,'candidates':list({c['url']:c for c in candidates}.values()),'errors':errors,'message':'Search results require employer ownership review before being added to sources.json.'}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--source'); parser.add_argument('--no-discovery',action='store_true'); args=parser.parse_args()
    sources=json.loads((ROOT/'sources.json').read_text())
    old=json.loads(DATA.read_text()) if DATA.exists() else {}
    previous={j['id']:j for j in old.get('jobs',[])}
    discovery=old.get('discovery',{'status':'not_configured','candidates':[]}) if args.no_discovery or args.source else discover()
    if not args.no_discovery and not args.source:
        from auto_company import adopt
        # Retry pending verification without additional search requests.
        candidates={c['url']:c for c in old.get('discovery',{}).get('candidates',[])}
        candidates.update({c['url']:c for c in discovery.get('candidates',[])})
        discovery['candidates']=list(candidates.values())[:100]
        added=adopt(discovery,sources,Fetcher())
        if added:
            source_path=ROOT/'sources.json'
            temp_sources=source_path.with_suffix('.tmp')
            temp_sources.write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n')
            temp_sources.replace(source_path)
    selected=[s for s in sources if not args.source or s['id']==args.source]
    if not selected:
        raise SystemExit('No matching source')
    jobs=[]; reports=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(crawl_source,s,previous):s for s in selected}
        for future in as_completed(futures):
            report,items=future.result(); reports.append(report); jobs.extend(items)
            print(f"{report['name']}: {report['status']}, {report['jobs']} active, {report['pages_checked']} pages",flush=True)
    if args.source:
        jobs += [j for j in old.get('jobs',[]) if j['source_id']!=args.source]
        reports += [s for s in old.get('sources',[]) if s['id']!=args.source]
    jobs=dedupe_jobs(jobs)
    for report in reports:
        report['jobs']=sum(j['source_id']==report['id'] and j['status']=='active' for j in jobs)
    payload={'schema_version':1,'updated_at':NOW,'schedule':'Every 6 hours','jobs':sorted(jobs,key=lambda j:(j['company'],j['title'])),'sources':sorted(reports,key=lambda s:s['name']),'discovery':discovery}
    DATA.parent.mkdir(parents=True,exist_ok=True)
    temp=DATA.with_suffix('.tmp'); temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n'); temp.replace(DATA)
    print(json.dumps({'jobs':len(jobs),'active':sum(j['status']=='active' for j in jobs),'sources':len(reports)}))

def dedupe_jobs(jobs):
    unique={}
    for job in jobs:
        path=re.sub(r'^/(?:en|en-us|en-uk|en-gb)(?=/)', '',urlsplit(job['url']).path,flags=re.I)
        key=(job['source_id'],host(job['url']),path,job['title'],job['location'])
        if key not in unique:
            unique[key]=job
        else:
            unique[key]['first_seen']=min(unique[key]['first_seen'],job['first_seen'])
    return list(unique.values())

if __name__=='__main__':
    main()
