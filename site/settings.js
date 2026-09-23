const $ = selector => document.querySelector(selector);
export function renderSettings(data) {
  const free = ['free_mode','not_configured'].includes(data.discovery?.status);
  $('#free-status').textContent = free
    ? `${data.sources.length} company sources are monitored without paid search. No API key is required.`
    : 'Optional Google search was enabled for the last crawl. To return to free-only mode, set ENABLE_GOOGLE_DISCOVERY to false in GitHub variables.';
}
export function initSettings(getState) {
  function searchLink() {
    const region=$('#search-region').value;
    const query=`"${$('#search-role').value}" "remote" (careers OR "join our team") ${region==='Worldwide'?'"worldwide"':region} -site:linkedin.com -site:indeed.com -site:glassdoor.com -site:ziprecruiter.com`;
    $('#free-google').href='https://www.google.com/search?q='+encodeURIComponent(query);
  }
  $('#search-region').addEventListener('change',searchLink);
  $('#search-role').addEventListener('change',searchLink);
  searchLink();
  $('#add-company').addEventListener('input',()=>{$('#company-ready').hidden=true;$('#company-error').hidden=true;});
  $('#add-company').addEventListener('submit',event=>{
    event.preventDefault();
    $('#company-error').hidden=true;$('#company-ready').hidden=true;
    try {
      const name=$('#company-name').value.trim(), country=$('#company-home').value.trim();
      const target=new URL($('#company-url').value.trim());
      const hostname=target.hostname.toLowerCase();
      if(target.protocol!=='https:'||target.username||target.password||target.port||target.search||target.hash)throw Error('Use a public HTTPS career URL without login details, query parameters or fragments.');
      if(!/career|vacanc|job|join.our.team|work.with.us|opportunit/i.test(target.pathname))throw Error('Enter the career or jobs page, not the company homepage.');
      if(/(^|\.)(linkedin\.com|indeed\.com|glassdoor\.com|ziprecruiter\.com|lever\.co|greenhouse\.io|ashbyhq\.com|bamboohr\.com|workable\.com)$/.test(hostname))throw Error('Use the company’s own website, not a job portal or external hiring-system URL.');
      if(['india','in','ind'].includes(country.toLowerCase()))throw Error('This watchlist is for companies based outside India.');
      if(name.length<2||country.length<2)throw Error('Provide the company name and home country.');
      const body='Please add this employer career page to the watchlist. I have checked that it belongs to the company.\n\n```json\n'+JSON.stringify({name,url:target.href,country},null,2)+'\n```';
      const params=new URLSearchParams({title:'[Add company] '+name,body});
      $('#company-request').href='https://github.com/imanishmehta/seo-job-radar/issues/new?'+params;
      $('#company-ready').hidden=false;
    } catch(error) {$('#company-error').textContent=error.message;$('#company-error').hidden=false;}
  });
  $('#export-tracker').addEventListener('click',()=>{
    const {data,local}=getState();
    const saved=data.jobs.filter(j=>local[j.id]?.saved||local[j.id]?.applied).map(j=>({id:j.id,title:j.title,company:j.company,url:j.url,saved:!!local[j.id]?.saved,applied:!!local[j.id]?.applied}));
    const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),jobs:saved},null,2)],{type:'application/json'});
    const objectURL=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=objectURL;a.download='seo-job-radar-shortlist.json';a.click();setTimeout(()=>URL.revokeObjectURL(objectURL),1000);
  });
}
