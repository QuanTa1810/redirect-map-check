# redirect-map-check

A small script for one boring but important job after a site migration: making sure every old URL in your redirect map really lands on the new URL you planned, in one permanent hop.

Paste your map as `old URL -> new URL` lines, run the script, get a CSV. No dependencies beyond Python 3.8+.

```
python3 redirect_map_check.py example_map.txt > report.csv
```

## What it catches

- **Wrong target** (`EXPECTED_MISMATCH`): the old URL ends somewhere other than the map says.
- **Dead ends** (`FINAL_4XX`, `FINAL_5XX`, `UNREACHABLE`): the chain stops on an error, or the host does not answer.
- **Chains** (`REDIRECT_CHAIN`): more than one hop, e.g. http → https → www.
- **Loops** (`REDIRECT_LOOP`, `TOO_MANY_REDIRECTS`).
- **Temporary redirects** (`TEMPORARY_REDIRECT`): a 302/303/307 where you probably meant a 301/308.
- **Downgrades** (`HTTPS_TO_HTTP`) and **dumping on the homepage** (`REDIRECT_TO_HOMEPAGE`).
- **Meta refresh** redirects (`META_REFRESH`) are followed and flagged. JavaScript redirects are not followed.

## Example

Input (`example_map.txt`):

```
http://wikipedia.org -> https://www.wikipedia.org/
http://github.com -> https://github.com/
http://example.com/old-page -> https://example.com/new-page
https://httpbin.org/redirect/2
```

Output, from a real run on 25 Oct 2026:

```
input,expected,final_url,final_status,redirects,chain,matches_expected,issues
http://wikipedia.org,https://www.wikipedia.org/,https://www.wikipedia.org/,200,2,301 -> 301 -> 200,yes,REDIRECT_CHAIN
http://github.com,https://github.com/,https://github.com/,200,1,301 -> 200,yes,
http://example.com/old-page,https://example.com/new-page,http://example.com/old-page,404,0,404,no,"FINAL_4XX, EXPECTED_MISMATCH"
https://httpbin.org/redirect/2,,https://httpbin.org/get,200,2,302 -> 302 -> 200,,"TEMPORARY_REDIRECT, REDIRECT_CHAIN"
```

Wikipedia lands on the right page but takes two hops. The `example.com/old-page` line is the kind that hurts: it was never redirected at all.

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--workers` | 10 | Parallel requests |
| `--timeout` | 15 | Seconds per hop |
| `--max-hops` | 10 | Redirects to follow before giving up |
| `--user-agent` | `browser` | `googlebot` sends Google's smartphone user-agent string, to spot sites that redirect bots differently |

Requests come from your own machine, so some sites that block automated traffic will show up as errors. Check those by hand in a browser.

## Quick one-liner instead

For a handful of URLs you do not need a script at all:

```
while read u; do curl -s -L -o /dev/null -w "$u -> %{url_effective} %{http_code} (%{num_redirects} hops)\n" "$u"; done < urls.txt
```

It tells you where each URL ends, but not whether that matches your map, and it does not flag 302s or loops.

## Running it at scale

The script is fine for a few thousand lines on a laptop. If you would rather not run anything locally, need a weekly re-check on a schedule, or want the results in Google Sheets / n8n, I also publish the same checks as a hosted tool: [Bulk Redirect Checker on Apify](https://apify.com/quanta1810/bulk-redirect-checker) (paid per URL; I built it).

## License

MIT
