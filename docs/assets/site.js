/* Shared by the four pages under docs/. Each page carries the small
   `data-core` block inline and fetches the large files it needs, so a
   reader who only wants the landing page never downloads the 39-call
   trail (GitHub issue #52). Which renderers run is decided by
   `<body data-page="...">` at the bottom of this file. */

const CHIP_CLASS = {
  registry: {covered:"ok", partial:"warn", none:"bad", unknown:""},
  execution: {complete:"ok", partial:"warn", failed:"bad"},
  pagination: {complete:"ok", truncated:"warn", unknown:""},
  result: {hit:"ok", empty:""},
};

const REPO_URL = "https://github.com/pranava0x0/Commonwealth-MCP";

function repoLink(path, text){
  const a = el("a", "", text);
  a.href = `${REPO_URL}/${path.endsWith("/") ? "tree" : "blob"}/main/${path}`;
  return a;
}

function el(tag, cls, text){
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function readEmbedded(id){
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing embedded data block #${id}`);
  return JSON.parse(node.textContent);
}

/* The three large files. Fetched once per page, on the first render that
   needs one. Opened from disk rather than served, fetch() rejects the
   file:// URL, so the caller shows the one-line fix rather than an empty
   section. */
const _loaded = new Map();
function loadData(name){
  if (!_loaded.has(name))
    _loaded.set(name, fetch(`data/${name}.json`).then(r => {
      if (!r.ok) throw new Error(`${r.status} fetching data/${name}.json`);
      return r.json();
    }));
  return _loaded.get(name);
}

function dataError(where, err){
  const box = document.getElementById(where);
  if (!box) return;
  const p = el("p","meta");
  p.append(location.protocol === "file:"
    ? "This section reads data/*.json, which a browser will not fetch from " +
      "a file:// page. Serve the folder instead: python -m http.server -d docs"
    : `Data failed to load: ${err.message}. Regenerate with tools/build_site.py.`);
  box.replaceChildren(p);
}

const plural = (n, w) => n === 1 ? w : w + "s";

const sentenceCase = t => t.charAt(0).toUpperCase() + t.slice(1);

const joinNames = names => names.length <= 2 ? names.join(" and ") :
  names.slice(0, -1).join(", ") + ", and " + names[names.length - 1];

/* A list too long to show at once. The first `initial` nodes are drawn and
   the rest arrive on one click, which is what keeps the tools and sources
   references to a screen and a half before a reader asks for more.

   `isItem` exists because the hidden nodes are not all items: the tools
   list interleaves a heading per package, and a button offering seven more
   tools when six are hidden and the seventh node is a heading is a lie the
   reader can count. */
function showMore(box, nodes, initial, noun, isItem){
  box.replaceChildren(...nodes.slice(0, initial));
  const rest = nodes.slice(initial);
  if (!rest.length) return;
  const n = isItem ? rest.filter(isItem).length : rest.length;
  const btn = el("button","cta secondary showmore",
                 `Show ${n} more ${plural(n, noun)}`);
  btn.type = "button";
  btn.addEventListener("click", ()=>{ box.append(...rest); btn.remove(); });
  box.after(btn);
}

function clearShowMore(box){
  const btn = box.nextElementSibling;
  if (btn && btn.classList.contains("showmore")) btn.remove();
}

/* --- copy buttons ------------------------------------------------------ */

function withCopyButton(pre){
  const wrap = el("div", "copywrap");
  const btn = el("button", "copy-btn", "Copy");
  btn.type = "button";
  btn.addEventListener("click", async ()=>{
    try{
      await navigator.clipboard.writeText(pre.textContent);
      btn.textContent = "Copied";
    }catch(err){
      // A denied clipboard is not worth an error state; the text is
      // right there and selectable.
      btn.textContent = "Select and copy";
    }
    setTimeout(()=>{ btn.textContent = "Copy"; }, 2000);
  });
  wrap.append(pre, btn);
  return wrap;
}

function addCopyButtons(){
  if (!navigator.clipboard) return;
  for (const pre of [...document.querySelectorAll("pre.copyable")]){
    if (pre.parentElement.classList.contains("copywrap")) continue;
    const wrap = withCopyButton(pre.cloneNode(true));
    pre.replaceWith(wrap);
  }
}

/* --- badges shared by the trail and the featured walk ------------------ */

/* The registry gap and the clean empty are the two answers this project
   exists to distinguish, and both once badged "ok" because the badge only
   looked at warnings — a call with nothing to warn about read as a success
   whether it found a record, found none, or had nowhere to look. Coverage
   decides the badge; the warning count is the fallback. */
function outcomeChip(a){
  const cov = a.coverage || {};
  const n = (a.warning_codes || []).length;
  return a.error ? el("span","chip bad","error")
    : a.requires_user_choice ? el("span","chip warn","ambiguous")
    : cov.registry === "none" ? el("span","chip bad","registry gap")
    : cov.execution === "failed" ? el("span","chip bad","source failed")
    : cov.result === "empty" ? el("span","chip","no records")
    : n ? el("span","chip warn", n + " " + plural(n, "warning"))
    : el("span","chip ok","ok");
}

function coverageChips(cov){
  const box = el("div","chips");
  for (const dim of ["registry","execution","pagination","result"]){
    if (!(dim in cov)) continue;
    const v = cov[dim];
    box.append(el("span","chip "+(CHIP_CLASS[dim][v]||""), dim+": "+v));
  }
  return box;
}

/* --- landing page ------------------------------------------------------ */

const COUNT_EXPLAINS = {
  sources: "Government systems registered and returning data. Nothing is " +
    "covered without one of these behind it. A few more are registered as " +
    "inventory with no endpoint yet; those are listed separately on the " +
    "sources page and are not counted here.",
  tools: "Callable MCP functions, covering parcels, zoning, boundaries, " +
    "addresses, buildings, roads, public places, monitored environmental " +
    "sites, the Code of Virginia, and what is registered.",
  jurisdictions: "Every place the resolver can tell apart by name — all " +
    "133 Virginia counties and independent cities, all 189 incorporated " +
    "towns, and the state. Fairfax City and Fairfax County are two of " +
    "them, and they are not the same government.",
};

function renderCounts(core){
  const wrap = document.getElementById("counts");
  if (!wrap) return;
  const c = core.counts;
  const seg = (n, label, title) => {
    const s = el("span","count-seg");
    s.title = title;
    s.append(el("b","",String(n)), document.createTextNode(" "+label));
    return s;
  };
  // sources_active, not sources: a `proposed` manifest is inventory with
  // no endpoint behind it, and counting it here would claim coverage the
  // registry does not have.
  wrap.append(
    seg(c.sources_active, plural(c.sources_active,"source"),
        COUNT_EXPLAINS.sources),
    el("span","count-arrow","→"),
    seg(c.tools, plural(c.tools,"tool"), COUNT_EXPLAINS.tools),
    el("span","count-arrow","→"),
    seg(c.jurisdictions, plural(c.jurisdictions,"jurisdiction"),
        COUNT_EXPLAINS.jurisdictions));
}

function renderWorksWith(core){
  const box = document.getElementById("works-with");
  if (!box) return;
  box.append(el("span","works-label","Works with"));
  for (const c of core.clients)
    box.append(el("span","chip", c.id));
}

/* One card per question, each linking to the recorded call that answers
   it. The questions are the capability copy, so the card list and the
   registry cannot describe different things. */
const ASK_ANSWERS = {
  "boundary.lookup": "The county or independent city, and the town where " +
    "one applies.",
  "parcel.lookup": "The assessor's record. Where a locality and the state " +
    "both publish one, both come back.",
  "geocode.address": "The state's address points, and the government " +
    "covering them — often not the postal city.",
  "zoning.lookup": "The locality's own map layer. Screening evidence; the " +
    "adopted ordinance governs.",
  "landmark.lookup": "Schools, libraries and fire stations, each with the " +
    "agency that contributed it.",
  "code_section.lookup": "The section text from the state's own site, " +
    "linked to the live page.",
};

function renderAsk(core){
  const box = document.getElementById("ask-cards");
  if (!box) return;
  const byTool = new Map(core.featured.steps.map(s => [s.tool, s.index]));
  for (const [cap, answer] of Object.entries(ASK_ANSWERS)){
    const card = el("div","card ask-card");
    card.append(el("p","q", core.capability_copy[cap].question));
    card.append(el("p","a", answer));
    const idx = byTool.get({
      "boundary.lookup": "geo.resolve_location",
      "parcel.lookup": "geo.find_parcel",
      "zoning.lookup": "geo.find_zoning",
      "landmark.lookup": "geo.find_landmarks",
    }[cap]);
    const a = el("a","meta", idx === undefined
      ? "On the trail" : "See the call");
    a.href = idx === undefined ? "examples.html" : `examples.html#call-${idx}`;
    card.append(a);
    box.append(card);
  }
}

function renderFeaturedWalk(core){
  const box = document.getElementById("featured-walk");
  if (!box) return;
  const f = core.featured;
  document.getElementById("featured-lede").textContent =
    `${f.address}, asked four ways. Three of the four answers come back ` +
    "differently, and telling them apart is the point of the whole thing.";
  f.steps.forEach((s, i) => {
    const row = el("div","walk-step");
    const head = el("div","tool-head");
    head.append(el("span","idx", String(i + 1)),
                el("code","tool-name", s.tool),
                outcomeChip(s));
    row.append(head, el("p","note", s.note));
    const a = el("a","meta","Read the full answer");
    a.href = `examples.html#call-${s.index}`;
    row.append(a);
    box.append(row);
  });
}

/* What a healthy first run prints, captured by running the command at
   build time rather than pasted, so the counts in it cannot drift from the
   registry the same build read. */
/* One quick-start step at a time. Four stacked steps were 1,568 px, most of
   it below a reader who had not finished step one; the tabs are the same
   four steps in the height of the tallest. Keyboard behaviour follows the
   tabs pattern: arrows move, Home and End jump to the ends. */
function wireStepper(){
  const bar = document.querySelector(".stepper");
  if (!bar) return;
  const tabs = [...bar.querySelectorAll(".step-tab")];
  const panel = t => document.getElementById(t.getAttribute("aria-controls"));

  function select(i, focus){
    tabs.forEach((t, j) => {
      t.setAttribute("aria-selected", String(j === i));
      t.tabIndex = j === i ? 0 : -1;
      panel(t).hidden = j !== i;
    });
    if (focus) tabs[i].focus();
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", ()=>select(i, false));
    t.addEventListener("keydown", e => {
      const step = {ArrowRight: 1, ArrowLeft: -1}[e.key];
      const to = step !== undefined ? (i + step + tabs.length) % tabs.length
        : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
      if (to === null) return;
      e.preventDefault();
      select(to, true);
    });
  });
  select(0, false);
  return select;
}

/* The plugin bundle: one install for the server and its skills. Written
   from the marketplace the repo publishes, so the command and the manifest
   name the same thing. */
function renderPluginInstall(core){
  const box = document.getElementById("plugin-snippet");
  if (!box) return;
  const m = core.plugin;
  box.replaceChildren(withCopyButton(el("pre","",
    `/plugin marketplace add ${m.marketplace}\n/plugin install ${m.name}@${m.marketplace_name}`)));
  const note = el("p","meta");
  // The profile the manifest launches, not every tool that exists: those
  // were the same number until a profile change made them differ.
  note.append(`Registers ${m.tool_count} tools and installs ` +
    `${m.skill_count} ${plural(m.skill_count,"skill")}. `);
  note.append(repoLink(m.path + "/", "See what it contains"));
  note.append(".");
  box.append(note);
}

function renderDoctorSample(core){
  const box = document.getElementById("doctor-sample");
  if (box) box.textContent = core.doctor_output;
}

function renderStarterPrompts(core){
  const box = document.getElementById("starter-prompts");
  if (!box) return;
  for (const p of core.starter_prompts){
    const row = el("div","prompt");
    row.append(withCopyButton(el("pre","", p.text)));
    const a = el("a","meta", `What ${p.tool} answered`);
    a.href = `examples.html#call-${p.call}`;
    row.append(a);
    box.append(row);
  }
}

function renderClients(core){
  const picker = document.getElementById("client-picker");
  if (!picker) return;
  const snippet = document.getElementById("client-snippet");
  const note = document.getElementById("client-note");
  const clients = core.clients || [];
  const show = (i)=>{
    for (const [j,b] of [...picker.children].entries())
      b.setAttribute("aria-pressed", String(j === i));
    const c = clients[i];
    snippet.replaceChildren(withCopyButton(
      el("pre","",`.venv/bin/commonwealth configure ${c.id}`)));
    const where = c.format === "toml"
      ? "This client keeps its config in TOML, so the command prints the " +
        "block to paste rather than writing a file."
      : `Writes ${c.path || "the client's own config file"}` +
        `${c.scope === "project" ? ", in the current directory" : ""}. ` +
        "The absolute path to this checkout is filled in for you.";
    note.textContent = [where, c.note].filter(Boolean).join(" ") +
      " Add --dry-run to see the change without making it.";
  };
  clients.forEach((c,i)=>{
    const b = el("button","chip chip-btn",c.id);
    b.type = "button";
    b.addEventListener("click", ()=>show(i));
    picker.append(b);
  });
  if (clients.length) show(0);
}

/* The coverage table is the one part of the landing page that needs the
   large file, so it is drawn after the fetch rather than holding up the
   first paint. */
function renderCoverage(core, coverage){
  const note = document.getElementById("counts-note");
  if (!note) return;
  // The summary answers the question most readers have — does this work
  // where I am — so the eleven-row table can stay closed until it does not.
  const summary = document.getElementById("coverage-summary");
  if (summary){
    // Which questions a statewide source answers, and which need a local
    // one, read off the registry rather than listed here: a statewide
    // layer added for a new subject moves that subject across on its own.
    const active = core.sources.filter(s => s.declared_state === "active");
    const statewide = new Set(active.filter(s => s.jurisdiction === "va")
      .flatMap(s => s.capabilities));
    const anywhere = core.capabilities.filter(c => statewide.has(c));
    const localOnly = core.capabilities.filter(c => !statewide.has(c));
    const placesFor = cap => new Set(active
      .filter(s => s.jurisdiction !== "va" && s.capabilities.includes(cap))
      .map(s => s.jurisdiction)).size;
    summary.replaceChildren();
    summary.append(
      "Statewide layers answer " +
      joinNames(anywhere.map(c => core.capability_copy[c].subject)) +
      " anywhere in Virginia. " +
      // The subjects are written lowercase because they read mid-sentence
      // everywhere else on the site; this is the one place one starts one.
      sentenceCase(joinNames(localOnly.map(c => {
        const n = placesFor(c);
        return `${core.capability_copy[c].subject} needs a local source, ` +
          `and ${n} ${n === 1 ? "locality publishes" : "localities publish"} ` +
          "one";
      }))) + ". Everywhere else, the answer says no source is registered " +
      "rather than coming back empty. ");
    const a = el("a","","Every registered source");
    a.href = "sources.html";
    summary.append(a, ".");
  }
  const jurName = id => (coverage.jurisdictions.find(j => j.id === id) || {}).name || id;
  const srcJurisdiction = id => (core.sources.find(s => s.id === id) || {}).jurisdiction;

  // This was four branching sentence templates producing prose like
  // "parcel.lookup covers all 14 jurisdictions through Virginia's statewide
  // registry" — which read as though 14 were the whole state, and buried
  // the one number a reader wants (where does this actually work?) in a
  // clause. A two-column table answers it directly.
  const kinds = core.jurisdiction_kinds;
  const intro = el("p");
  intro.append(`The registry contains ${(kinds.county || 0) + (kinds["independent-city"] || 0)} ` +
    `counties and independent cities and ${kinds.town || 0} towns. ` +
    "This table shows registered source availability. It does not measure " +
    "record completeness, current service health, or legal authority.");
  note.replaceChildren(intro);

  const wrapT = el("div", "tablewrap");
  const table = el("table");
  const thead = el("thead");
  const hr = el("tr");
  hr.append(el("th", "", "Question"), el("th", "", "Where it works"));
  thead.append(hr);
  const tbody = el("tbody");

  for (const cap of core.capabilities){
    const cc = coverage.capability_coverage[cap];
    // "va" matching its own statewide source is the statewide fan-out
    // landing on the state row, not a local source.
    const localRows = cc.covered.filter(row => row.jurisdiction !== "va" &&
      row.sources.some(id => srcJurisdiction(id) === row.jurisdiction));
    // Covered, but by neither its own source nor the statewide row: a town
    // picking up its county's source through the resolved stack.
    const inheritedRows = cc.covered.filter(row => row.jurisdiction !== "va" &&
      !localRows.includes(row));
    const gapCount = cc.gaps.length;

    const tr = el("tr");
    const capCell = el("td");
    capCell.append(el("div", "cap-q", core.capability_copy[cap].question));
    capCell.append(el("code", "cap-id", cap));
    tr.append(capCell);
    const td = el("td");

    if (gapCount === 0){
      // "no gaps" and "a statewide source" are different facts. A
      // capability covered everywhere by local manifests has no gaps and
      // no statewide source, and saying otherwise would be false.
      const statewide = cc.covered.some(row => row.jurisdiction === "va");
      td.append(statewide
        ? "A statewide source is registered; local record coverage varies."
        : "A source is registered for each place listed.");
      if (localRows.length){
        const names = joinNames(localRows.map(row => jurName(row.jurisdiction)));
        const one = localRows.length === 1;
        td.append(statewide
          ? ` ${names} ${one ? "also publishes its own layer, and it is"
                             : "also publish their own layers, and those are"}`
            + " queried alongside the statewide one."
          : ` ${names} ${one ? "publishes its own layer"
                             : "publish their own layers"}.`);
      }
    } else {
      td.append(joinNames(localRows.map(row => jurName(row.jurisdiction))) +
        " only.");
      if (inheritedRows.length){
        td.append(" " + joinNames(inheritedRows.map(row =>
          jurName(row.jurisdiction) + " selects a source from " +
          joinNames([...new Set(row.sources.map(
            id => jurName(srcJurisdiction(id))))]))) + ", " +
          "with town-specific authority and coverage still requiring verification.");
      }
      td.append(" For the other " + gapCount + " " +
        plural(gapCount, "place") + " on the list, the answer says no " +
        "source is registered there, rather than coming back empty.");
    }
    tr.append(td);
    tbody.append(tr);
  }
  table.append(thead, tbody);
  wrapT.append(table);
  note.append(wrapT);

  const seeAlso = el("p", "meta");
  seeAlso.append("Widening this is the main open work. ");
  const a = el("a", "", "See the open issues");
  a.href = REPO_URL + "/issues";
  seeAlso.append(a, ".");
  note.append(seeAlso);
}

/* --- workflows --------------------------------------------------------- */

function renderSkills(core){
  const box = document.getElementById("skills-list");
  if (!box) return;
  const shipped = core.skills.filter(s => s.status === "shipped");
  const planned = core.skills.filter(s => s.status !== "shipped");
  const cards = [];
  for (const s of shipped){
    const card = el("div","card skill-card");
    const head = el("div","tool-head");
    head.append(el("code","tool-name", s.name),
                el("span","status-note shipped", s.status));
    card.append(head);
    if (s.description) card.append(el("p","", s.description));
    if (s.steps && s.steps.length){
      // The walk is what a skill adds over its tools, so it is the part
      // of the card a reader should see without opening anything.
      const ol = el("ol","steps-mini");
      // The heading carries its own "1 — "; the list numbers it too, and
      // "1. 1 — parcel.lookup" reads like a typo.
      s.steps.forEach(t=>ol.append(el("li","",
        t.replace(/`/g,"").replace(/^\d+\s*[—-]\s*/,""))));
      card.append(ol);
    }
    if (s.prompt) card.append(withCopyButton(el("pre","", s.prompt)));
    const links = el("p","meta");
    links.append(repoLink(
      `plugins/commonwealth-mcp/skills/${s.name}/SKILL.md`, "SKILL.md"));
    if (s.capabilities.length)
      links.append(" · needs " + s.capabilities.join(", "));
    card.append(links);
    cards.push(card);
  }
  // Six cards is the tallest section on the page. Three, and a button for
  // the rest, is the same treatment the tools and sources references get.
  showMore(box, cards, 3, "workflow");

  if (!planned.length) return;
  const list = el("ul","plain planned");
  for (const s of planned){
    const li = el("li");
    li.append(el("code","", s.name), ` — ${s.status}. ${s.description}`);
    list.append(li);
  }
  const fold = el("details","fold");
  const sum = el("summary");
  sum.append(el("h3","", `Named but not written (${planned.length})`));
  fold.append(sum, list);
  box.after(fold);
}

/* --- tools reference --------------------------------------------------- */

function toolRow(t, profileOf){
  const row = el("details","card tool-card");
  const head = el("summary","tool-head");
  head.append(el("code","tool-name",t.name));
  head.append(el("span","tool-summary",t.summary));
  head.append(el("span","chip",profileOf(t.name)));
  row.append(head);

  // Read off the bound function at build time, so the page cannot
  // advertise an argument the server does not take.
  const params = t.parameters || [];
  if (params.length){
    const line = el("p","meta tool-params");
    line.append("takes ");
    params.forEach((prm,i)=>{
      if (i) line.append(", ");
      const c = el("code","",prm.name);
      if (prm.required) c.className = "req";
      line.append(c);
    });
    const required = params.filter(prm=>prm.required).length;
    line.append(required ? " — bold is required" : " — all optional");
    row.append(line);
  }
  row.append(el("p","tool-full",t.description));
  return row;
}

function renderTools(core){
  const box = document.getElementById("tool-results");
  if (!box) return;
  const search = document.getElementById("tool-search");
  const countLine = document.getElementById("tool-count");
  const emptyLine = document.getElementById("tool-empty");
  const filters = document.getElementById("tool-filters");
  const packages = [...new Set(core.tools.map(t=>t.package))].sort();
  const inDefault = new Set(core.profiles.default);
  const profileOf = name => inDefault.has(name) ? "default"
    : core.profiles.discovery.includes(name) ? "discovery" : "all";
  let active = "";

  document.getElementById("profiles-line").textContent =
    "Models pick the wrong tool more often as the list grows, so a profile " +
    "limits how many are exposed at once: " +
    Object.entries(core.profiles)
      .map(([k,v])=>`${k} exposes ${v.length}`).join(", ") + ". " +
    "Rows are grouped by package, each package's default-profile tools " +
    "first, and the chip on a row says which profile carries it.";

  for (const pkg of packages){
    const n = core.tools.filter(t=>t.package === pkg).length;
    const b = el("button","chip chip-btn",`${pkg} (${n})`);
    b.type = "button";
    b.dataset.pkg = pkg;
    b.setAttribute("aria-pressed","false");
    b.addEventListener("click", ()=>{
      active = active === pkg ? "" : pkg;
      for (const other of filters.children)
        other.setAttribute("aria-pressed", String(other.dataset.pkg === active));
      draw();
    });
    filters.append(b);
  }

  function matches(t, q){
    if (active && t.package !== active) return false;
    if (!q) return true;
    const hay = [t.name, t.package, t.toolset, t.description,
                 ...(t.parameters||[]).map(prm=>prm.name)]
                .join(" ").toLowerCase();
    return q.split(/\s+/).every(word=>hay.includes(word));
  }

  function draw(){
    const q = (search.value || "").trim().toLowerCase();
    const shown = core.tools.filter(t=>matches(t,q));
    clearShowMore(box);
    // Grouped by package, default-profile tools first inside each group:
    // the nine a client sees by default are the nine worth reading first.
    const ordered = [];
    for (const pkg of packages){
      const rows = shown.filter(t=>t.package === pkg);
      if (!rows.length) continue;
      const head = el("h3","group-head",
        `${pkg} — ${rows.length} ${plural(rows.length,"tool")}`);
      ordered.push(head, ...rows
        .sort((a,b)=> (inDefault.has(b.name) - inDefault.has(a.name)) ||
                      a.name.localeCompare(b.name))
        .map(t=>toolRow(t, profileOf)));
    }
    // Expanding for a search or a filter shows everything that matched;
    // the unfiltered list is the one that holds tools back.
    const initial = (q || active) ? ordered.length
      : ordered.findIndex((n,i)=> ordered.slice(0,i)
          .filter(x=>x.classList.contains("tool-card")).length ===
          inDefault.size);
    showMore(box, ordered, initial < 0 ? ordered.length : initial, "tool",
             n => n.classList.contains("tool-card"));
    countLine.textContent = shown.length === core.tools.length
      ? `All ${core.tools.length} tools.`
      : `${shown.length} of ${core.tools.length} ${plural(core.tools.length,"tool")}.`;
    // An empty search result here is a search that matched nothing, which
    // is the one kind of empty this project does not have to qualify.
    emptyLine.hidden = shown.length > 0;
    emptyLine.textContent = shown.length ? "" :
      "No tool matches that. The names are packages and verbs — try " +
      "zoning, parcel, address, boundaries, or source.";
  }

  search.addEventListener("input", draw);
  draw();
}

/* --- sources reference ------------------------------------------------- */

function sourceCard(s){
  const card = el("div","card source-card");
  card.append(el("h3","",s.name));
  const chips = el("div","chips");
  chips.append(el("span","chip", s.jurisdiction_name),
               el("span","chip", s.authority_level.replace(/_/g," ")),
               el("span","chip" + (s.declared_state === "active" ? " ok" : ""),
                  s.declared_state));
  card.append(chips);
  // A proposed row declares no capability, because a capability id is a
  // promise that a query can be routed somewhere.
  card.append(el("p","", s.publisher + ". " + (s.answers.length
    ? "Answers " + joinNames(s.answers) + "."
    : "No capability yet — nothing routes here.")));
  if (s.known_limitations.length){
    // The limitation text is the source's own contract and stays word for
    // word; what changes is that it opens on request rather than filling
    // eleven screens with the ones nobody asked about.
    const fold = el("details","fold lim");
    const sum = el("summary");
    sum.append(el("h3","",
      `Known limitations (${s.known_limitations.length})`));
    const ul = el("ul","plain");
    s.known_limitations.forEach(l=>ul.append(el("li","",l)));
    fold.append(sum, ul);
    card.append(fold);
  }
  const meta = el("p","meta");
  const a = el("a","","Source terms");
  a.href = s.terms_url;
  meta.append(a, " · ", el("code","", s.id));
  card.append(meta);
  return card;
}

function renderSources(core){
  const box = document.getElementById("sources-cards");
  if (!box) return;
  const active = core.sources.filter(s=>s.declared_state === "active");
  const proposed = core.sources.filter(s=>s.declared_state !== "active");
  document.getElementById("sources-lede").textContent =
    `Every question this server answers is answered from one of these ` +
    `${active.length} systems. Each is registered with a manifest that ` +
    "records what it publishes and what its terms allow. Ask about a place " +
    "none of them covers and the answer says exactly that, rather than " +
    "coming back empty.";

  const search = document.getElementById("source-search");
  const countLine = document.getElementById("source-count");
  const emptyLine = document.getElementById("source-empty");
  const filters = document.getElementById("source-filters");
  // The capability ids the registered sources actually answer, so a
  // filter chip can never name something nothing routes to.
  const caps = [...new Set(active.flatMap(s=>s.capabilities))].sort();
  let active_cap = "";

  for (const cap of caps){
    // The subject, in the words the questions use. The full id stays in
    // the tooltip, because that is what the manifest says.
    const b = el("button","chip chip-btn", core.capability_copy[cap].subject);
    b.type = "button";
    b.title = cap;
    b.dataset.cap = cap;
    b.setAttribute("aria-pressed","false");
    b.addEventListener("click", ()=>{
      active_cap = active_cap === cap ? "" : cap;
      for (const other of filters.children)
        other.setAttribute("aria-pressed",
                           String(other.dataset.cap === active_cap));
      draw();
    });
    filters.append(b);
  }

  function matches(s, q){
    if (active_cap && !s.capabilities.includes(active_cap)) return false;
    if (!q) return true;
    const hay = [s.name, s.id, s.publisher, s.jurisdiction,
                 s.jurisdiction_name, ...s.answers,
                 ...s.capabilities, ...s.known_limitations]
                .join(" ").toLowerCase();
    return q.split(/\s+/).every(w=>hay.includes(w));
  }

  function draw(){
    const q = (search.value || "").trim().toLowerCase();
    const shown = active.filter(s=>matches(s,q));
    clearShowMore(box);
    showMore(box, shown.map(sourceCard),
             (q || active_cap) ? shown.length : 6, "source");
    countLine.textContent = shown.length === active.length
      ? `All ${active.length} registered sources.`
      : `${shown.length} of ${active.length} sources.`;
    emptyLine.hidden = shown.length > 0;
    emptyLine.textContent = shown.length ? "" :
      "No registered source matches that. That is a search miss, not a " +
      "coverage gap — the proposed list below may still name the " +
      "publisher, and the coverage table says what is answerable where.";
  }
  search.addEventListener("input", draw);
  draw();

  if (!proposed.length) return;
  document.getElementById("sources-proposed-head").textContent =
    `Known about, not wired up (${proposed.length})`;
  document.getElementById("sources-proposed-note").textContent =
    "These are inventory. Each names a publisher worth covering and " +
    "carries what was checked and when; none has an endpoint behind it, " +
    "and nothing can query one. They are here so the gap is countable " +
    "rather than remembered.";
  const pbox = document.getElementById("sources-proposed-cards");
  proposed.forEach(s=>pbox.append(sourceCard(s)));
}

function renderJurisdictions(core){
  const line = document.getElementById("jur-line");
  if (!line) return;
  const kinds = Object.entries(core.jurisdiction_kinds)
    .map(([k,v])=>`${v} ${k}`).join(", ");
  line.textContent =
    `${core.counts.jurisdictions} places are in the table (${kinds}) — ` +
    "every locality and incorporated town in Virginia, built from the " +
    "state boundary layer and the Census county list and checked against " +
    "each other. Names collide constantly here. When one matches more " +
    "than one place, every match comes back for the caller to choose " +
    "between.";
  const chips = document.getElementById("trap-chips");
  for (const [a,b] of core.trap_pairs)
    chips.append(el("span","chip warn",`${a} ≠ ${b}`));
}

/* --- the recorded trail ------------------------------------------------ */

function renderCall(call, i){
  const a = call.audit;
  // Thirty-nine expanded cards ran to most of the page height, and a
  // reader scrolling to the section below had to go past all of them.
  // Collapsed, the trail is a scannable list of what each call
  // demonstrates and you open the one you care about.
  const card = el("details","call");
  card.id = "call-" + i;
  const head = el("summary","call-head");
  head.append(el("span","idx",String(i+1).padStart(2,"0")),
              el("span","tool",a.tool));
  if (a.duration_ms > 0) head.append(el("span","ms",a.duration_ms+" ms"));
  head.append(outcomeChip(a));
  card.append(head, el("p","note",call.note));

  const chips = a.error
    ? (()=>{const c=el("div","chips");
        c.append(el("span","chip bad","error: "+a.error));return c;})()
    : coverageChips(a.coverage);
  if (a.requires_user_choice)
    chips.append(el("span","chip warn","requires user choice"));
  for (const w of a.warning_codes)
    chips.append(el("span","chip warn",w));
  card.append(chips);

  const srcBits = a.sources.map(s =>
    `${s.source_id} (${s.authority_level}, ${s.access_path}` +
    (s.cache_age_seconds>0 ? `, cache ${s.cache_age_seconds}s` : "") + ")");
  const line = el("p","srcline",
    (srcBits.length ? "sources: "+srcBits.join(" · ") + " · " : "") +
    `evidence records: ${a.evidence_count} · args: ` +
    (a.args ? JSON.stringify(a.args) : `[names only: ${a.arg_names}]`) +
    (a.request_id ? ` · request ${a.request_id.slice(0,8)}` : ""));
  card.append(line);

  if (call.http_calls !== undefined){
    if (call.http_calls.length){
      const wrap = el("div","http-calls");
      wrap.append(el("p","srcline",
        `${call.http_calls.length} ${plural(call.http_calls.length,"request")}` +
        " actually sent to the government service:"));
      for (const hc of call.http_calls){
        const pre = el("pre");
        pre.style.maxHeight = "180px";
        pre.textContent = `GET ${hc.url}\nparams: ` +
          JSON.stringify(hc.params) + "\nresponse: " +
          JSON.stringify(hc.response);
        wrap.append(pre);
      }
      card.append(wrap);
    } else {
      card.append(el("p","srcline",
        "No request was sent. This answer came from the local registry."));
    }
  }

  const det = el("details");
  det.append(el("summary","",call.is_error
    ? "the error text, as the model sees it" : "the full answer"));
  const pre = el("pre");
  pre.textContent = call.is_error
    ? call.error_text
    : JSON.stringify(call.envelope, null, 1);
  det.append(pre);
  card.append(det);
  return card;
}

function renderAudit(demo){
  // Written from the trail rather than typed into the page: it said
  // "Fourteen real lookups" while the server had grown to fourteen TOOLS
  // and the trail had not been rerun.
  const tools = new Set(demo.calls.map(c => c.audit && c.audit.tool));
  document.getElementById("calls-lede").textContent =
    `${demo.call_count} real lookups in ${demo.groups.length} walks, and ` +
    `the exact answer each one came back with — at least one call for ` +
    `every one of the ${tools.size} tools the server exposes. This is ` +
    "what an AI assistant connected to it would receive.";
  const sum = document.getElementById("audit-summary");
  const sources = new Set(), warnings = new Set();
  let evidence = 0, errors = 0;
  for (const c of demo.calls){
    evidence += c.audit.evidence_count;
    if (c.audit.error) errors += 1;
    c.audit.sources.forEach(s=>sources.add(s.source_id));
    c.audit.warning_codes.forEach(w=>warnings.add(w));
  }
  sum.append(
    el("span","chip",`${demo.call_count} calls`),
    el("span","chip",`${sources.size} sources touched`),
    el("span","chip",`${evidence} evidence records`),
    el("span","chip warn",`${warnings.size} warning kinds`),
    el("span","chip bad",`${errors} typed error`),
    el("span","chip",`mode: ${demo.mode}`));

  const box = document.getElementById("calls");
  box.replaceChildren();
  for (const g of demo.groups){
    box.append(el("h3","group-head", g.title));
    box.append(el("p","lede", g.note));
    for (let i = g.first; i < g.first + g.count; i++)
      box.append(renderCall(demo.calls[i], i));
  }
}

// A jump link that lands on a collapsed row shows the reader a summary and
// nothing else, which looks like a broken anchor. Open it first.
function openCall(idx){
  const card = document.getElementById("call-" + idx);
  if (!card) return;
  card.open = true;
  card.scrollIntoView({block:"start"});
}

/* The index is by walk, not one flat row of 39 numbered tool names: six
   `registry.resolve_jurisdiction` entries in a row said nothing about why
   each call was made. */
function renderJumpIndex(demo){
  const box = document.getElementById("jump-tabs");
  if (!box) return;
  for (const g of demo.groups){
    const b = el("button","tab", `${g.title} (${g.count})`);
    b.type = "button";
    b.title = g.note;
    b.addEventListener("click", ()=>{
      openCall(g.first);
      box.querySelectorAll(".tab").forEach(t=>t.classList.remove("active"));
      b.classList.add("active");
    });
    box.append(b);
  }
}

function renderDecoder(core, demo){
  const covBox = document.getElementById("decoder-coverage");
  if (!covBox) return;
  const coverageSeen = {}, warningSeen = {};
  demo.calls.forEach((c,i)=>{
    const cov = c.audit.coverage || {};
    for (const [dim,val] of Object.entries(cov))
      (coverageSeen[dim+":"+val] ||= []).push(i);
    for (const w of c.audit.warning_codes || [])
      (warningSeen[w] ||= []).push(i);
  });

  function seenLine(idxs){
    if (!idxs || !idxs.length)
      return el("p","seen","none of the recorded calls below produced this");
    const p = el("p","seen");
    p.append(document.createTextNode("seen in call" +
      (idxs.length>1?"s ":" ") +
      idxs.map(i=>String(i+1).padStart(2,"0")).join(", ")));
    return p;
  }

  let covValueCount = 0;
  for (const def of Object.values(core.coverage_definitions))
    covValueCount += Object.keys(def.values).length;
  covBox.querySelector("summary").textContent =
    `Coverage dimensions (${Object.keys(core.coverage_definitions).length} ` +
    `dimensions, ${covValueCount} values)`;
  for (const [dim, def] of Object.entries(core.coverage_definitions)){
    const grid = el("div","decoder-grid");
    for (const [val, meaning] of Object.entries(def.values)){
      const item = el("div","decoder-item");
      item.append(el("div","dt", dim + " — " + def.question));
      item.append(el("div","dv", val));
      item.append(el("p","",meaning));
      item.append(seenLine(coverageSeen[dim+":"+val]));
      grid.append(item);
    }
    covBox.append(grid);
  }

  const warnBox = document.getElementById("decoder-warnings");
  warnBox.querySelector("summary").textContent =
    `Warning codes (${Object.keys(core.warning_definitions).length})`;
  const grid = el("div","decoder-grid");
  for (const [code, meaning] of Object.entries(core.warning_definitions)){
    const item = el("div","decoder-item");
    item.append(el("div","dt", code));
    item.append(el("p","",meaning));
    item.append(seenLine(warningSeen[code]));
    grid.append(item);
  }
  warnBox.append(grid);
}

/* --- the resolver playground ------------------------------------------- */

function renderResolveResult(entry, query){
  const box = document.getElementById("resolver-result");
  box.replaceChildren();
  if (!entry){
    box.append(el("p","resolve-none",
      `Nothing recorded for "${query}". This page carries answers for ` +
      "every name, alias, id, and FIPS code in the table, worked out when " +
      "the page was built. Try one of the examples above, or a full " +
      "county or city name."));
    return;
  }
  if (entry.resolved){
    const p = el("div","resolve-hit");
    // A town's name already ends in "(town)", so appending its kind
    // would print it twice.
    const kind = entry.resolved.name.toLowerCase()
      .includes(`(${entry.resolved.kind})`) ? "" : ` (${entry.resolved.kind})`;
    p.append(document.createTextNode(
      `${entry.resolved.name}${kind} — resolved via ` +
      `basis "${entry.basis}".`));
    if (entry.former_name){
      const note = el("span","cand");
      note.textContent =
        `"${entry.former_name}" is the name of a government that no ` +
        "longer exists. Three Virginia cities gave up their charters and " +
        "became towns inside their county, so a record using the old " +
        "name predates that change.";
      p.append(note);
    }
    box.append(p);
  } else {
    const p = el("div","resolve-amb");
    p.append(document.createTextNode(
      `That name matches ${entry.candidates.length} places. All of them ` +
      "come back, so you can pick:"));
    for (const c of entry.candidates){
      const line = el("span","cand");
      line.textContent = `• ${c.name} — ${c.distinguisher}`;
      p.append(line);
    }
    box.append(p);
  }
}

/* 235 KB of precomputed answers for a widget nobody has typed in yet, so
   the file is fetched on the first interaction rather than on load. */
function renderResolver(){
  const input = document.getElementById("resolver-input");
  if (!input) return;
  let queryMap = null;
  let pending = null;

  function ensure(){
    if (queryMap) return Promise.resolve(queryMap);
    if (!pending) pending = loadData("resolver-demo").then(d => {
      const list = document.getElementById("resolver-suggestions");
      for (const q of d.query_list) list.append(new Option(q));
      // A Map, not the raw object: a plain-object lookup keyed by
      // arbitrary user input (`obj[q]`) returns inherited properties for
      // keys like "__proto__" or "constructor" instead of undefined,
      // which crashes the renderer on `entry.candidates.length` below.
      queryMap = new Map(Object.entries(d.queries));
      return queryMap;
    }).catch(err => { dataError("resolver-result", err); throw err; });
    return pending;
  }

  const examples = document.getElementById("resolver-examples");
  for (const q of ["fairfax","richmond","bedford","bedford city",
                   "vienna","51059"]){
    const chip = el("button","chip chip-btn", q);
    chip.type = "button";
    chip.addEventListener("click", ()=>{ input.value = q; showQuery(q); });
    examples.append(chip);
  }

  function showQuery(raw){
    const q = raw.trim().toLowerCase();
    if (!q){ document.getElementById("resolver-result").replaceChildren(); return; }
    ensure().then(map => renderResolveResult(map.get(q), raw.trim()),
                  ()=>{});
  }
  input.addEventListener("input", ()=>showQuery(input.value));
  input.addEventListener("focus", ensure, {once:true});
}

/* --- footer, nav, moved anchors ---------------------------------------- */

function renderFooter(core){
  const foot = document.getElementById("foot");
  if (!foot) return;
  const d = core.demo_meta;
  foot.append(
    `Generated from the live registries: commonwealth-mcp ${core.version}, ` +
    `registry revision ${core.registry_revision}. Audit demo generated ` +
    `${d.generated_at} in ${d.mode} mode over fixtures recorded ` +
    `${d.fixture_recorded_at}. Specs, decisions, and research live in ` +
    "the repo: ");
  foot.append(repoLink("design/", "design/"));
  foot.append(", ");
  foot.append(repoLink("research/", "research/"));
  foot.append(".");
}

/* Anchors that used to name a section of the one-page site and now name a
   page. A bookmark, a link in llms.txt, or a shared `#call-7` still lands
   on the content it named. */
const MOVED_ANCHORS = {
  tools: "tools.html", sources: "sources.html", coverage: "sources.html#places",
  examples: "examples.html", try: "examples.html",
  what: "#ask", install: "#quick-start",
};

function followMovedAnchor(){
  const hash = location.hash.slice(1);
  if (!hash) return;
  const call = hash.match(/^call-(\d+)$/);
  if (call){ location.replace(`examples.html#${hash}`); return; }
  const target = MOVED_ANCHORS[hash];
  if (!target) return;
  if (target.startsWith("#")){
    const node = document.querySelector(target);
    if (node) node.scrollIntoView({block:"start"});
  } else {
    location.replace(target);
  }
}

/* --- page dispatch ----------------------------------------------------- */

(function(){
  const page = document.body.dataset.page;
  let core;
  try{
    core = readEmbedded("data-core");
  }catch(err){
    const p = document.getElementById("loaderr");
    if (p){ p.hidden = false; p.textContent =
      "Data failed to load: " + err.message +
      ". Regenerate with tools/build_site.py."; }
    return;
  }

  renderFooter(core);
  addCopyButtons();

  if (page === "index"){
    renderCounts(core);
    renderWorksWith(core);
    renderAsk(core);
    renderFeaturedWalk(core);
    renderDoctorSample(core);
    renderStarterPrompts(core);
    renderClients(core);
    renderPluginInstall(core);
    wireStepper();
    renderSkills(core);
    renderResolver();
    loadData("coverage").then(c => renderCoverage(core, c),
                              err => dataError("counts-note", err));
    followMovedAnchor();
    window.addEventListener("hashchange", followMovedAnchor);
  } else if (page === "tools"){
    renderTools(core);
  } else if (page === "sources"){
    renderSources(core);
    renderJurisdictions(core);
  } else if (page === "examples"){
    renderResolver();
    loadData("audit-demo").then(demo => {
      renderAudit(demo);
      renderJumpIndex(demo);
      renderDecoder(core, demo);
      // A shared #call-7 link lands on a collapsed row otherwise.
      const syncHashCall = () => {
        const m = location.hash.match(/^#call-(\d+)$/);
        if (m) openCall(Number(m[1]));
      };
      syncHashCall();
      window.addEventListener("hashchange", syncHashCall);
    }, err => dataError("calls", err));
  }
})();
