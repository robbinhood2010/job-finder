# LinkedIn Job Finder

A phone-friendly page listing disputes, chargeback, card and payments jobs in Egypt and the Gulf
countries, taken from LinkedIn's public job listings.

- `index.html`: the page.
- `update_jobs.py`: fetches the jobs (job titles and countries are at the top of the file).
- `job_finder.py`: reads LinkedIn's public job listings.
- `.github/workflows/update.yml`: runs the update every morning and publishes the page with GitHub Pages.

To update right away: **Actions** tab → **Update jobs** → **Run workflow**.
