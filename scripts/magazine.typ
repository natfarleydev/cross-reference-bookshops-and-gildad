// The Origami Book Guide — Typst edition.
//
// A side-by-side alternative to the Gotenberg/HTML generator. Reads the same
// data exported by scripts/export_magazine_data.py and lays the magazine out
// natively in Typst (no browser, no container — a single static binary).
//
//   PYTHONPATH=. .venv/Scripts/python scripts/export_magazine_data.py
//   typst compile --root . scripts/magazine.typ out/origami_magazine_typst.pdf

#let data = json("/out/magazine_data.json")
#let meta = data.meta

// --- palette ---------------------------------------------------------------
#let ink = rgb("#1f2430")
#let paper = rgb("#fbfaf7")
#let accent = rgb("#c2410c")
#let muted = rgb("#6b7280")
#let line = rgb("#e6e2da")
#let bucket-color = (
  simple: rgb("#2f9e44"),
  intermediate: rgb("#1c7ed6"),
  complex: rgb("#ae3ec9"),
)

// Per-level colour ramp (simple -> super complex). A book's detail-page header
// is filled with the gradient across its difficulty band, so the colour itself
// shows the range; section/front-matter headers use a solid colour.
#let level-color = (
  rgb("#2f9e44"),  // 1 simple
  rgb("#1ca38a"),  // 2 low intermediate
  rgb("#1c7ed6"),  // 3 intermediate
  rgb("#6741d9"),  // 4 high intermediate
  rgb("#ae3ec9"),  // 5 complex
  rgb("#d6336c"),  // 6 super complex
)
#let level-fill(lo, hi) = if lo == hi { level-color.at(lo - 1) } else {
  gradient.linear(level-color.at(lo - 1), level-color.at(hi - 1))
}

// Current section, read by the page header; updated as the document advances.
// Holds a display name and a fill (solid colour or gradient). Defaults to the
// front-matter section so the legend page (whose own update would land too late
// for its header) is anchored too.
#let cur = state("cur", (name: "The Guide", fill: accent))

#let img-or(path, ..args) = if path != "" { image("/" + path, ..args) } else {
  box(fill: rgb("#f1efe9"), ..args, inset: 2pt)[
    #set text(7pt, fill: muted)
    #align(center + horizon)[no cover]
  ]
}

// Wrap an image in a link to the page it came from (provenance), when known.
#let linked(url, body) = if url != "" { link(url, body) } else { body }

#let repo = "https://github.com/natfarleydev/cross-reference-bookshops-and-gildad"

// --- page setup ------------------------------------------------------------
#set document(title: "Bookshop.org × Gilad (unofficial)", author: "Origami Book Finder")
#set text(font: ("Arial", "Liberation Sans"), size: 10pt, fill: ink)
#set page(
  paper: "a4",
  margin: (x: 14mm, top: 20mm, bottom: 16mm),
  fill: paper,
  // Full-bleed coloured running header naming the current section.
  header: context {
    let c = cur.get()
    if c.name == "" { return none }
    block(
      width: 100%, fill: c.fill,
      inset: (y: 3mm), outset: (x: 14mm),
    )[
      #set text(fill: white, size: 8.5pt)
      #grid(
        columns: (1fr, auto),
        strong(upper(c.name)),
        [Bookshop.org × Gilad (unofficial)],
      )
    ]
  },
  header-ascent: 6mm,
  footer: context {
    set text(7.5pt, fill: muted)
    grid(
      columns: (1fr, auto),
      [Bookshop.org × Gilad (unofficial) · data from #meta.region_host & Gilad's Origami Database · #link(repo)[source on GitHub]],
      [page #counter(page).display()],
    )
  },
)

// ===========================================================================
// COVER (full bleed)
// ===========================================================================
#page(margin: 0pt, header: none, footer: none, fill: ink)[
  #place(top + left, polygon(fill: accent, (0mm, 0mm), (42mm, 0mm), (0mm, 42mm)))
  #place(bottom + right, polygon(fill: rgb("#9a330a"),
    (56mm, 56mm), (0mm, 56mm), (56mm, 0mm)))
  #pad(x: 20mm, y: 24mm)[
    #set text(fill: white)
    #v(40mm)
    #text(40pt, weight: 800)[Bookshop.org#linebreak()× Gilad]
    #v(6mm)
    #text(15pt)[An unofficial origami book guide]
    #v(2.5mm)
    #text(12pt, fill: rgb("#cbd2dc"))[Folder's edition · #meta.issue]
    #v(12mm)
    #block(width: 130mm, text(13pt)[
      #meta.total_rated origami books you can buy on *#meta.region_host*,
      hand-sorted by skill level with the models inside each one.
    ])
    // push the level breakdown to the foot of the page so the cover reads
    // top-to-bottom instead of clustering in the upper third (balance).
    #v(1fr)
    #text(11pt, fill: rgb("#cbd2dc"))[
      Beginner · #meta.counts.simple books#linebreak()
      Intermediate · #meta.counts.intermediate books#linebreak()
      Complex · #meta.counts.complex books
    ]
    #v(5mm)
    #text(8.5pt, fill: rgb("#7e8794"))[Generated #meta.generated]
  ]
]

// ===========================================================================
// LEGEND
// ===========================================================================
#text(15pt, weight: "bold")[How to use this guide]
#v(3mm)
#block(width: 160mm, text(9.5pt)[
  Every book here is in stock or orderable on Bookshop.org (UK) — buy through the
  linked title to support independent bookshops. Skill levels and the list of
  models inside each book come from *Gilad's Origami Database*.
])
#v(3mm)
#block(width: 160mm, text(9.5pt)[
  The shop carries #meta.catalog_size origami titles; #meta.total_rated of them
  have a published skill rating and appear in the sections that follow. The rest
  (paper packs, unrated reprints, e-books) are browsable in the companion web app.
])
#v(4mm)
#text(15pt, weight: "bold")[Skill levels & the difficulty key]
#v(2mm)
#let key-line(bucket, label, blurb) = block(below: 3mm)[
  #text(fill: bucket-color.at(bucket), weight: "bold")[#label] — #blurb
]
#key-line("simple", "Beginner",
  "simple folds and first models, a gentle place to start.")
#key-line("intermediate", "Intermediate",
  "shaping, sinks and modular work without the white-knuckle complexity.")
#key-line("complex", "Complex",
  "many-step insects, dragons and tessellations for experienced folders.")
#text(8.5pt, fill: muted)[
  #text(fill: bucket-color.complex, weight: "bold")[\[CP\]] marks a crease-pattern-only design.
]

// ===========================================================================
// SECTION LISTINGS
// ===========================================================================
#let card(b) = block(breakable: false, width: 100%, inset: (y: 3pt),
  stroke: (bottom: 0.4pt + line))[
  #grid(
    columns: (26mm, 1fr),
    gutter: 3mm,
    linked(b.url, img-or(b.cover, width: 26mm, height: 36mm, fit: "contain")),
    [
      #text(10pt, weight: "bold")[#link(label("book_" + b.isbn13))[#text(fill: accent)[#b.title]]]
      #linebreak()
      #text(8pt, fill: muted)[#b.author]
      #linebreak()
      #text(8pt)[*#b.difficulty* · #b.design_count diagrams#linebreak()*#b.price* · #b.format · #b.stock]
      #if b.sample != "" [
        #linebreak()
        #text(7.2pt)[#emph[Inside:] #b.sample]
      ]
      #if b.url != "" [
        #linebreak()
        #link(b.url)[#text(7pt, fill: muted)[Buy on Bookshop.org »]]
      ]
    ],
  )
]

#for sec in data.sections {
  cur.update((name: sec.label, fill: bucket-color.at(sec.key)))
  pagebreak()
  block(width: 100%, fill: bucket-color.at(sec.key), inset: 8pt)[
    #set text(fill: white)
    #text(16pt, weight: "bold")[#sec.label · #sec.books.len() books]
    #linebreak()
    #text(9pt)[#sec.blurb]
  ]
  v(6mm)
  columns(2, gutter: 8mm)[
    #for b in sec.books [ #card(b) ]
  ]
}

// ===========================================================================
// PER-BOOK DETAIL PAGES
// ===========================================================================
// `dominant` is the designer of >80% of the book's models; when a line matches
// it the name is omitted (it's stated once in the section header instead).
#let model-line(m, dominant: "", size: 9pt) = block(breakable: false)[
  #text(size)[#m.name#if m.designer != "" and m.designer != dominant [#text(fill: muted)[#if m.designer == "Traditional" [ (traditional)] else [ — #m.designer]]]#if m.page != "" [#text(fill: muted)[ · p.#m.page]]#if m.cp [ #text(fill: bucket-color.complex, weight: "bold")[\[CP\]]]]
]

// The cover is the page's focal point: a large bordered image (its natural
// aspect, no letterbox) that's clearly the biggest element on the page.
#let hero-cover(b) = linked(b.url, if b.cover != "" {
  box(stroke: 0.5pt + line)[#image("/" + b.cover, width: 62mm)]
} else {
  box(width: 62mm, height: 88mm, fill: rgb("#f1efe9"), inset: 4pt)[
    #set text(8pt, fill: muted)
    #align(center + horizon)[no cover]
  ]
})

// A row of sample model photos — lives with the model list, not beside the cover.
#let thumb-strip(b) = grid(
  columns: (1fr,) * 5,
  column-gutter: 3mm,
  ..b.thumbs.map(t => [
    #linked(b.gilad, box(width: 100%, height: 26mm, fill: white,
      stroke: 0.4pt + line, inset: 1pt)[
      #align(center + horizon)[#image("/" + t.img, width: 100%, height: 100%, fit: "contain")]
    ])
    #text(6.5pt, fill: muted)[#align(center)[#t.name]]
  ]),
)

#for b in data.details {
  cur.update((name: b.difficulty, fill: level-fill(b.diff_low, b.diff_high)))
  pagebreak()
  box(width: 0pt, height: 0pt)
  [#metadata(b.isbn13)#label("book_" + b.isbn13)]

  // --- Hero: prominent cover tightly grouped with the title block ---
  grid(
    columns: (62mm, 1fr),
    column-gutter: 9mm,
    hero-cover(b),
    [
      #text(22pt, weight: "bold")[#b.title]
      #v(2mm)
      #if b.subtitle != "" [ #text(12pt, fill: muted)[#b.subtitle] #v(1.5mm) ]
      #text(12pt, fill: muted)[#b.author]
      #v(4.5mm)
      #text(10.5pt)[*#b.difficulty* · #b.design_count diagrams #h(3mm)·#h(3mm) *#b.price* · #b.format · #b.stock]
      #if b.url != "" [
        #v(2.5mm)
        #text(10.5pt)[#link(b.url)[#text(fill: accent, weight: "bold")[Buy on Bookshop.org »]]]
      ]
    ],
  )

  // --- Models: a distinct section, separated by generous whitespace. The
  // sample photos sit here with the list (same hierarchy), demoted below the
  // hero cover. ---
  v(12mm)
  if b.models.len() > 0 {
    let ncol = if b.models.len() > 40 { 3 } else { 2 }
    text(13pt, weight: "bold")[All #b.models.len() model#if b.models.len() != 1 [s]]
    if b.dominant_designer != "" {
      let has-exc = b.models.any(m => m.designer != "" and m.designer != b.dominant_designer)
      let credit = if b.dominant_designer == "Traditional" { "traditional designs" } else {
        "designed by " + b.dominant_designer
      }
      text(10pt, fill: muted)[ — #credit#if has-exc [ unless otherwise stated]]
    }
    if b.thumbs.len() > 0 {
      v(4mm)
      thumb-strip(b)
    }
    v(5mm)
    grid(
      columns: (1fr,) * ncol,
      column-gutter: if ncol == 3 { 5mm } else { 8mm },
      row-gutter: 2.4mm,
      ..b.models.map(m => model-line(m, dominant: b.dominant_designer,
        size: if ncol == 3 { 8pt } else { 9pt })),
    )
  } else {
    text(13pt, weight: "bold")[No model list available from Gilad.]
  }
}
