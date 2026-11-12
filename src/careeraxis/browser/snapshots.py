"""Browser-side selectors and page snapshots for CareerAxis."""

_JOB_STATE = r"""() => {
  const urls = [...new Set([...document.querySelectorAll("a[href]")].flatMap(anchor => {
    try {
      const url = new URL(anchor.href, location.href);
      return url.origin === location.origin && /^\/students\/jobs\/\d+\/?$/.test(url.pathname)
        ? [url.href] : [];
    } catch { return []; }
  }))];
  const text = (document.body && document.body.innerText || "").replace(/\s+/g, " ");
  return {
    urls,
    no_results: /\b(no (jobs?|job postings?|opportunities|matching results?) found|nothing found|0 (jobs?|results?))\b/i.test(text)
  };
}"""
_SEARCH_SNAPSHOT = r"""() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const opportunities = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll("a[href]")) {
    let url;
    try { url = new URL(anchor.href, location.href); } catch { continue; }
    if (url.origin !== location.origin || !/^\/students\/jobs\/\d+\/?$/.test(url.pathname)
        || /\/(apply|saved|delete)(\/|$)/i.test(url.pathname)) continue;
    const linkTitle = clean(anchor.innerText || anchor.textContent);
    if (!linkTitle || seen.has(url.href)) continue;
    let card = anchor;
    for (let node = anchor.parentElement, depth = 0; node && depth < 7; node = node.parentElement, depth++) {
      const identity = `${node.className || ""} ${node.id || ""}`;
      if (/^(ARTICLE|LI|TR)$/.test(node.tagName) || node.getAttribute("role") === "article"
          || /(job|opportunit|listing|result|position|posting)/i.test(identity)) {
        card = node;
        break;
      }
    }
    const heading = card.querySelector("h1,h2,h3,h4,h5,[class*=title i]");
    const title = clean(heading && (heading.innerText || heading.textContent)) || linkTitle;
    const details = clean(card.innerText || card.textContent).slice(0, 4000);
    opportunities.push({title, url: url.href, details});
    seen.add(url.href);
  }
  const controls = [...document.querySelectorAll("a,button,[role=button]")];
  const hasNext = controls.some(el => {
    const label = clean(el.getAttribute("aria-label") || el.innerText || el.textContent).toLowerCase();
    return /^(next|next page|load more results|›|»)$/.test(label)
      && el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden'
      && !el.closest('.disabled,[disabled],[aria-disabled="true"]');
  });
  const bodyText = clean(document.body && document.body.innerText);
  const noResults = /\b(no (jobs?|job postings?|opportunities|matching results?) found|nothing found|0 (jobs?|results?))\b/i.test(bodyText);
  return {opportunities, has_next_page: hasNext, no_results: noResults};
}"""
_DETAIL_SNAPSHOT = r"""() => {
  const main = document.querySelector("main") || document.querySelector("[role=main]") || document.body;
  const clean = value => (value || "").replace(/[\u200B-\u200F\uFEFF\u2060-\u206F]/g, "").replace(/\s+/g, " ").trim();
  const documentTitle = clean(document.title.replace(/^[^|]+\|\s*/, ""));
  const genericTitle = /^(students|loading\.\.\.|be scam-aware|appointments|documents|resources|search events|search topics|search organisations|internship|internship opportunities|opportunity details|careeraxis|careeraxis opportunities|opportunities|notifications)$/i;
  const headings = [...main.querySelectorAll("h1,h2,h3")]
    .map(heading => clean(heading.innerText || heading.textContent))
    .filter(heading => heading && !genericTitle.test(heading) && !/\{\{[^}]+\}\}/.test(heading));
  const recordTitle = !genericTitle.test(documentTitle) ? documentTitle : headings[0] || "";
  const links = [...main.querySelectorAll("a[href]")]
    .filter(a => /apply|application|employer site|external/i.test(
      `${a.innerText || a.textContent} ${a.getAttribute("aria-label") || ""} ${a.title || ""}`
    ))
    .map(a => a.href);
  return {
    title: recordTitle,
    text: clean(main.innerText || main.textContent).slice(0, 20000),
    application_links: links,
    links: [...main.querySelectorAll("a[href]")].flatMap(a => {
      try {
        const url = new URL(a.href, location.href);
        const navigation = new Set([
          "/students", "/students/jobs", "/students/jobs/search", "/students/organisations", "/students/events",
          "/students/appointments", "/students/resources", "/students/notifications", "/students/dashboard",
          "/students/profile", "/students/bookmarks", "/students/settings/preferences",
          "/students/settings/communication", "/students/account", "/students/info/contact",
          "/students/info/termsandconditions", "/students/logout", "/workgroups/internship", "/workgroups/mlcps"
        ]);
        if (url.href === location.href || navigation.has(url.pathname)) return [];
        return url.protocol === "https:" ? [url.href] : [];
      } catch { return []; }
    })
  };
}"""
_SECTION_PATHS = {
    "events": "/students/events",
    "resources": "/students/resources/search/",
    "organisations": "/students/organisations/Search",
    "appointment_topics": "/students/appointments/topics",
    "internship_jobs": "/workgroups/internship/Jobs",
}
_PORTAL_SNAPSHOT = r"""(section) => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const patterns = {
    events: /^\/students\/events\/detail\/\d+\/?$/,
    resources: /^\/students\/docs\/detail\/\d+\/?$/,
    organisations: /^\/students\/organisations\/detail\/\d+\/[A-Za-z0-9._-]+\/?$/,
    appointment_topics: /^\/students\/appointments\/topics\/\d+\/?$/,
    internship_jobs: /^\/workgroups\/internship\/Jobs\/detail\/\d+\/?$/
  };
  const items = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll("a[href]")) {
    let url;
    try { url = new URL(anchor.href, location.href); } catch { continue; }
    if (url.origin !== location.origin || !patterns[section]?.test(url.pathname) || seen.has(url.href)) continue;
    const title = clean(anchor.innerText || anchor.textContent);
    if (!title) continue;
    const card = anchor.closest("article,li,tr,[role=article],.list-group-item") || anchor;
    items.push({title, url: url.href, summary: clean(card.innerText || card.textContent).slice(0, 4000)});
    seen.add(url.href);
  }
  const labels = [...document.querySelectorAll("a,button,[role=button]")]
    .filter(el=>el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden'
      && !el.closest('.disabled,[disabled],[aria-disabled="true"]')).map(el =>
    clean(el.getAttribute("aria-label") || el.innerText || el.textContent).toLowerCase()
  );
  const currentPage = Number(clean(document.querySelector(".pagination li.active")?.innerText || "1"));
  const pageNumbers = [...document.querySelectorAll(".pagination a")]
    .filter(el=>el.getClientRects().length>0&&!el.closest('.disabled,[disabled],[aria-disabled="true"]'))
    .map(el => Number(clean(el.innerText))).filter(Number.isFinite);
  const hasNext = labels.some(label => /^(next|next page|load more results|show more|›|»)$/.test(label))
    || (Number.isFinite(currentPage) && pageNumbers.some(number => number > currentPage));
  const bodyText = clean(document.body && document.body.innerText);
  const noResults = /\b(no (jobs?|events?|resources?|organisations?|topics?|matching results?) found|nothing found|0 (jobs?|events?|results?))\b/i.test(bodyText);
  return {items, has_next_page: hasNext, no_results: noResults};
}"""

_DETAIL_READY_STATE = r"""() => {
              const clean = value => (value || "").replace(/[\u200B-\u200F\uFEFF\u2060-\u206F]/g, "").replace(/\s+/g, " ").trim();
              const main = document.querySelector("main") || document.querySelector("[role=main]") || document.body;
              const generic = /^(students|loading\.\.\.|be scam-aware|appointments|documents|resources|search events|search topics|search organisations|internship|internship opportunities|opportunity details|careeraxis|careeraxis opportunities|opportunities|notifications)$/i;
              const headings = [...main.querySelectorAll("h1,h2,h3")].map(node => clean(node.innerText || node.textContent));
              const documentTitle = clean(document.title.replace(/^[^|]+\|\s*/, ""));
              const heading = !generic.test(documentTitle) && !/\{\{[^}]+\}\}/.test(documentTitle)
                ? documentTitle
                : headings.find(value => value && !generic.test(value) && !/\{\{[^}]+\}\}/.test(value));
              const text = clean(main.innerText || main.textContent);
              const placeholder = !heading;
              return {ready: !placeholder && text.length > 250, heading};
            }"""
