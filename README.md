# SEO Job Radar

Remote SEO jobs checked on employer career pages, deployed at **https://imanishmehta.github.io/seo-job-radar/**.

## What it does

- Crawls the employer career pages in `sources.json`, then follows their own role links and linked hiring systems.
- Supports public Lever, Greenhouse and Ashby feeds, plus HTML role pages and Schema.org JobPosting data.
- Excludes job portals. Search results never become verified jobs automatically.
- Separates India / worldwide eligibility, location restrictions and unclear eligibility. These are conservative text-based labels; check the quoted evidence before applying.
- Filters by remote status, full-time, part-time, contract, posting date and verification status.
- Keeps first-found, employer posting date and last verification separate. A fresh crawl does not turn an old job into a new one.
- Saves and tracks applications in this browser's local storage. There is no login, cross-device sync or automatic application submission.
- Rechecks every six hours with GitHub Actions. Schedules can be delayed by GitHub. Public-repository schedules may be disabled after 60 days without repository activity; crawler commits normally keep this repository active.

## Source coverage and limitations

The dashboard starts with 40 researched employer sources across the Americas, Europe, Africa, Asia and Australia. New sources may be added later. It is **not a complete Google-wide index**. Some employers block crawlers, require JavaScript rendering or use unsupported ATS systems. The Career sources screen reports these gaps instead of implying there are no vacancies.

An active listing means the employer's role page was reachable and the posting was found on its page or current official feed. It is not a guarantee the employer is interviewing. Missing roles in complete ATS feeds and explicit expiry/closure are marked closed. Timeouts and blocked sources become `needs_check`, retaining the previous verification time. The browser also hides active records older than 48 hours from active results, even if the scheduler stops.

Generic HTML crawling is bounded at 18 pages per employer and may not enumerate every role. Worldwide eligibility never follows solely from the word “remote.” Company bases in the initial watchlist are editorial metadata, not a work-location guarantee. New sources should have their employer identity and country checked before inclusion.

### Optional Google discovery

Google discovery is OFF by default, even if a key is saved. To opt in, add a **Serper** API key as repository Actions secret `SERPER_API_KEY` and a repository variable `ENABLE_GOOGLE_DISCOVERY=true`, then run **Refresh career pages and deploy**. Set the variable to `false` to turn paid search off. The integration searches Google for SEO career pages and excludes known job portals. Search candidates appear under Career sources. Review company ownership, then add approved employers to `sources.json`; unreviewed search results are never promoted to verified employer listings. Existing employer crawls need no search key.

Serper usage depends on your account's credits. No search key or private credentials are shipped to the browser. Do not put keys in `sources.json`, frontend files or commits.

## Expand the free watchlist

Open **Expand & settings**. Country and role search shortcuts open ordinary Google searches without an API. They require you to review the results and do not claim automatic global discovery.

Use **Add a company** to prepare a GitHub issue containing the company name, official career URL and home country. Sign in as `imanishmehta` and submit it on GitHub. The Actions workflow accepts only requests authored and triggered by the repository owner. It validates public HTTPS URLs, rejects portals and external ATS URLs as starting sources, checks the page is reachable, prevents duplicate company hosts, commits the company, crawls and redeploys. Rejected or blocked URLs appear as failed Actions runs; review them before adding manually. Request details are public. Never include credentials in an issue.

Alternatively, **Run workflow** accepts `company_name`, `career_url` and `company_country`. Leave them blank for an ordinary refresh. Source configuration is retained in GitHub, so deleting the Codex chat does not stop monitoring. An API key is entered only through GitHub Secrets, never through the public dashboard. Saved/applied records remain browser-local; the settings screen can export them as JSON.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/crawl.py
python3 -m http.server 8765 --directory site
```

Open http://localhost:8765. To check one source: `.venv/bin/python scripts/crawl.py --source brafton --no-discovery`.

## GitHub deployment

Owner: **imanishmehta**. The `main` branch contains source code and `site/data/jobs.json` history. Settings → Pages → Build and deployment must use **GitHub Actions**. `.github/workflows/refresh.yml` crawls, tests, commits updated history and deploys only the public `site/` directory. It runs at 01:17, 07:17, 13:17 and 19:17 UTC, or manually from Actions. Dashboard “Reload results” loads the latest published data; use Actions → Run workflow to start a fresh crawl.

The repository and dashboard are public. Saved/applied state stays on your device. No analytics, tracking pixels or server-held personal application data are used. Google Fonts are loaded from Google's font service.

## API references

- [Lever public postings API](https://github.com/lever/postings-api)
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Ashby public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
