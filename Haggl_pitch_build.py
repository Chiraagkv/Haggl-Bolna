"""Build the Haggl hackathon pitch deck (python-pptx; node/pptxgenjs is not installed here)."""

import sys

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

OUT = sys.argv[1]

# ---------------------------------------------------------------- palette (mandi green + saffron)
GREEN = RGBColor(0x0E, 0x3B, 0x2E)     # dominant: dark slides, headers
GREEN2 = RGBColor(0x1F, 0x6B, 0x4F)    # secondary
MINT = RGBColor(0xE6, 0xF2, 0xEC)      # card tint on light slides
MINT_TXT = RGBColor(0xCF, 0xE6, 0xDA)  # light text on dark
SAFFRON = RGBColor(0xF2, 0xA3, 0x3A)   # the one sharp accent
INK = RGBColor(0x1B, 0x24, 0x21)
MUTED = RGBColor(0x55, 0x63, 0x5D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xC9, 0xD8, 0xD0)
HEAD, BODY = "Cambria", "Calibri"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W = 13.333
M = 0.6  # side margin


def slide(dark=False):
    s = prs.slides.add_slide(BLANK)
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = GREEN if dark else WHITE
    return s


def text(s, x, y, w, h, runs, size=16, color=INK, font=BODY, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         italic=False, margin=0, spacing=None, name=None):
    """runs: str, or list of paragraphs; a paragraph is str or list of (text, {opts})."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(margin)
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = o.get("font", font)
            f.size = Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", italic)
            f.color.rgb = o.get("color", color)
    return tb


def box(s, x, y, w, h, fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, line=None, radius=0.08, name=None):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        sh.name = name
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1)
    sh.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    sh.text_frame.text = ""
    return sh


def badge(s, x, y, d, label, fill=SAFFRON, color=GREEN, size=18, name=None):
    """The deck's motif: a number or glyph in a filled circle."""
    c = box(s, x, y, d, d, fill, shape=MSO_SHAPE.OVAL, name=name)
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = HEAD, Pt(size), True, color
    return c


def arrow(s, x1, y1, x2, y2, color=GREEN2, width=2):
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    ln.line.color.rgb = color
    ln.line.width = Pt(width)
    tail = ln.line._get_or_add_ln()
    from pptx.oxml.ns import qn
    from lxml import etree
    end = etree.SubElement(tail, qn("a:tailEnd"))
    end.set("type", "triangle")
    end.set("w", "med")
    end.set("len", "med")
    return ln


def title(s, t, kicker=None, dark=False):
    if kicker:
        text(s, M, 0.42, W - 2 * M, 0.35, kicker.upper(), size=12, bold=True, color=SAFFRON if dark else GREEN2, name="Kicker")
    text(s, M, 0.72, W - 2 * M, 0.95, t, size=32, bold=True, font=HEAD, color=WHITE if dark else INK, name="Title")


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


def footer(s, t, dark=False):
    text(s, M, 7.0, W - 2 * M, 0.3, t, size=10, color=MINT_TXT if dark else MUTED, name="Source")


# ====================================================================== 1. title
s = slide(dark=True)
text(s, M, 1.2, 7.2, 0.4, "BOLNA BUILDATHON  ·  OCTOBER 2026", size=14, bold=True, color=SAFFRON)
text(s, M, 1.75, 7.2, 1.5, "Haggl", size=80, bold=True, font=HEAD, color=WHITE, name="Title")
text(s, M, 3.35, 6.6, 1.6, "A voice AI buyer that phones a kitchen's suppliers, bargains with real prices and books the order",
     size=24, color=MINT_TXT)
text(s, M, 5.55, 6.6, 0.8, [[("Built on Bolna voice agents  ·  ", {}), ("Hindi · English · Kannada", {"bold": True, "color": WHITE})]],
     size=16, color=MINT_TXT)
# motif: three calls, one per language
bubbles = [("हि", "Namaste, aaj pyaaz aur tel ka bhaav kya hai?"), ("EN", "Hello, could I have today's prices, please?"),
           ("ಕ", "ನಮಸ್ಕಾರ, ಇವತ್ತಿನ ದರ ಎಷ್ಟು?")]
for i, (tag, line) in enumerate(bubbles):
    y = 1.55 + i * 1.55
    x = 8.0 + (0.45 if i == 1 else 0)
    box(s, x, y, 4.45, 1.15, GREEN2, radius=0.3, name=f"Call bubble {i + 1}")
    badge(s, x + 0.22, y + 0.25, 0.65, tag, size=16 if tag != "EN" else 14, name=f"Language badge {i + 1}")
    text(s, x + 1.05, y + 0.12, 3.25, 0.9, line, size=15, color=WHITE, anchor=MSO_ANCHOR.MIDDLE,
         font="Nirmala UI" if tag == "ಕ" else BODY)
notes(s, "Haggl is a voice AI buyer for small food businesses. It phones the owner's own suppliers in their language, "
         "collects prices, bargains using only real competing prices, and books the order once the supplier confirms. "
         "Everything voice-related runs on Bolna; the decisions and safety rules run in our code.")

# ====================================================================== 2. problem
s = slide()
title(s, "A small kitchen loses 15 minutes a day to price calls", "The problem")
box(s, M, 1.85, W - 2 * M, 0.95, MINT, name="Problem statement")
text(s, M + 0.3, 1.92, W - 2 * M - 0.6, 0.85,
     [[("Problem statement (our framing): ", {"bold": True, "color": GREEN}),
       ("small food businesses phone several suppliers every day to get prices, have no time to bargain, and order on trust. "
        "Build a Bolna voice agent that does the calling, bargaining and booking for them.", {})]],
     size=15, anchor=MSO_ANCHOR.MIDDLE)
text(s, M, 3.25, 4.2, 1.5, "15 min", size=72, bold=True, font=HEAD, color=SAFFRON)
text(s, M, 4.65, 4.0, 1.3, "spent phoning four suppliers for one order, every morning", size=18, color=INK)
text(s, M, 5.8, 4.0, 0.8, "From our owner interviews; demo persona: Priya's Cloud Kitchen", size=11, color=MUTED, italic=True)
pains = [("Prices change daily, by supplier", "Pyaaz is ₹25 at one shop and ₹28 at the next. Nobody has time to compare every day."),
         ("No time to haggle", "So the first price heard is usually the price paid, and the cheapest isn't always reliable."),
         ("Suppliers live on the phone", "No apps, no portals: calls in Hindi or Kannada, often during the morning rush.")]
for i, (h, d) in enumerate(pains):
    y = 3.2 + i * 1.22
    badge(s, 5.4, y + 0.1, 0.6, str(i + 1), name=f"Pain {i + 1} badge")
    text(s, 6.25, y, 6.5, 0.4, h, size=19, bold=True, font=HEAD, color=GREEN)
    text(s, 6.25, y + 0.45, 6.5, 0.7, d, size=15, color=INK)
notes(s, "This is our own framing of the problem, not official wording. The owner of a small kitchen phones four suppliers "
         "every morning: about 15 minutes, every day, and she still doesn't bargain. Prices differ by supplier and by day, and "
         "suppliers work over the phone in Hindi or Kannada.")

# ====================================================================== 3. solution
s = slide()
title(s, "Haggl calls, bargains and books. The owner says yes", "The solution")
steps = [("Order", "Owner lists the items, deadline and budget"),
         ("Round 1", "Quotes from every supplier, two calls at a time"),
         ("Rank", "Expected cost: price, delivery fee, credit and lateness risk"),
         ("Round 2", "Best suppliers hear a REAL rival price and can match it"),
         ("Confirm", "Supplier confirms by phone; owner approves if over budget"),
         ("Receipt", "What was booked, and the saving vs last time")]
cw = (W - 2 * M) / 6
for i, (h, d) in enumerate(steps):
    cx = M + i * cw + cw / 2
    badge(s, cx - 0.45, 2.3, 0.9, str(i + 1), size=24, name=f"Step {i + 1}")
    if i < 5:
        arrow(s, cx + 0.55, 2.75, cx + cw - 0.55, 2.75)
    text(s, M + i * cw + 0.1, 3.4, cw - 0.2, 0.45, h, size=20, bold=True, font=HEAD, color=GREEN, align=PP_ALIGN.CENTER)
    text(s, M + i * cw + 0.12, 3.9, cw - 0.24, 1.4, d, size=14, color=INK, align=PP_ALIGN.CENTER)
box(s, M, 5.55, W - 2 * M, 1.0, MINT, name="Tagline")
text(s, M + 0.3, 5.6, W - 2 * M - 0.6, 0.9,
     [[("Whole order: about 6 to 10 short calls, ", {}), ("none of them made by the owner.", {"bold": True, "color": GREEN}),
       ("  The owner's phone rings only to approve an over-budget order and to hear the result.", {})]],
     size=16, anchor=MSO_ANCHOR.MIDDLE)
notes(s, "Six steps. Round 1 collects prices from every supplier that sells what we need. We rank by expected cost, not just "
         "price: a cheap supplier who is often late can cost more. Round 2 calls the best two back with a real competing price. "
         "Then the supplier confirms the exact order, and the owner gets a receipt with the saving.")

# ====================================================================== 4. how Bolna is used
s = slide()
title(s, "Bolna is the voice. Haggl is the brain", "How we use Bolna")
# left: Haggl
box(s, M, 1.95, 3.3, 4.6, MINT, name="Haggl box")
text(s, M + 0.25, 2.1, 2.9, 0.45, "Haggl server", size=20, bold=True, font=HEAD, color=GREEN)
text(s, M + 0.25, 2.65, 2.9, 3.8,
     ["Plans every call and its prompt variables", "Ranks quotes, decides who to call back",
      "Guards: real prices only, budget, spend", "Live board and receipt"],
     size=14, color=INK, spacing=10)
# right: Bolna
bx = 7.15
box(s, bx, 1.95, 4.0, 4.6, GREEN, name="Bolna box")
text(s, bx + 0.25, 2.1, 3.5, 0.45, "Bolna", size=20, bold=True, font=HEAD, color=WHITE)
agents = ["Supplier, round 1", "Supplier, round 2", "Booking confirm", "Owner approval", "Owner report", "Owner order call"]
for i, a in enumerate(agents):
    cx = bx + 0.25 + (i % 2) * 1.8
    cy = 2.65 + (i // 2) * 0.55
    box(s, cx, cy, 1.7, 0.42, GREEN2, radius=0.4, name=f"Agent {i + 1}")
    text(s, cx, cy, 1.7, 0.42, a, size=11, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, bx + 0.25, 4.4, 3.5, 2.0,
     [[("Speech in: ", {"bold": True, "color": SAFFRON}), ("Sarvam saaras:v4", {})],
      [("Thinking: ", {"bold": True, "color": SAFFRON}), ("gpt-4.1-mini", {})],
      [("Voice out: ", {"bold": True, "color": SAFFRON}), ("Sarvam bulbul:v3", {})],
      [("Languages: ", {"bold": True, "color": SAFFRON}), ("Hindi, English, Kannada", {})]],
     size=13, color=WHITE, spacing=4)
# arrows between
labels = [("POST /call  +  prompt variables", 2.55, True), ("submit_quote tool, mid-call", 3.8, False),
          ("Webhooks + extractions at hang-up", 5.05, False)]
for t, y, right in labels:
    if right:
        arrow(s, M + 3.4, y + 0.45, bx - 0.1, y + 0.45)
    else:
        arrow(s, bx - 0.1, y + 0.45, M + 3.4, y + 0.45)
    text(s, M + 3.45, y, bx - M - 3.55, 0.4, t, size=13, bold=True, color=GREEN2, align=PP_ALIGN.CENTER)
# phone
badge(s, 11.65, 3.6, 1.05, "☎", fill=SAFFRON, color=GREEN, size=26, name="Phone")
arrow(s, bx + 4.05, 4.12, 11.6, 4.12)
text(s, 11.25, 4.75, 1.85, 0.9, "Supplier or owner on a normal phone", size=12, color=MUTED, align=PP_ALIGN.CENTER)
footer(s, "Prompt variables carry the call reference, the items, the deadline, real rival prices and the language to start in.")
notes(s, "Haggl never talks to anyone itself. For each call it asks Bolna to dial with one of six purpose-built agents and passes "
         "the details as prompt variables. During the call Bolna's agent calls our submit_quote tool the moment a price is "
         "confirmed, so prices appear on the board live. When the call ends, Bolna sends the transcript and the extractions "
         "(structured answers) to our webhook. Speech is Sarvam in and out, the thinking is gpt-4.1-mini, all on Bolna's flat rate.")

# ====================================================================== 5. Bolna API surface
s = slide()
title(s, "All of Bolna set up by code: one command, no dashboard", "How we use Bolna")
rows = [("Bolna feature", "What we call", "What Haggl does with it"),
        ("Voice agents", "POST / PUT /v2/agent", "6 agents, re-pushed with the new tunnel URL on every start"),
        ("Custom function tool", "api_tools: custom_task", "submit_quote puts prices on the board mid-call"),
        ("Extractions", "POST /dispositions/bulk", "Quotes, yes/no confirmation and totals read from the transcript"),
        ("Multilingual", "multilingual_config + agent_language", "Hindi, English, Kannada; switches mid-call by itself"),
        ("Outbound calls", "POST /call  (user_data)", "Items, deadline and real rival prices per call"),
        ("Status and data", "Webhooks + GET /executions", "Live status, transcript at hang-up, polling if a webhook is lost"),
        ("Account", "GET /user/me", "Wallet and concurrency checked before any order starts")]
tbl = s.shapes.add_table(len(rows), 3, Inches(M), Inches(1.9), Inches(8.6), Inches(4.6)).table
tbl.columns[0].width, tbl.columns[1].width, tbl.columns[2].width = Inches(2.0), Inches(2.75), Inches(3.85)
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = GREEN if r == 0 else (MINT if r % 2 else WHITE)
        cell.margin_left = cell.margin_right = Inches(0.1)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = val
        run.font.name = BODY
        run.font.size = Pt(12 if r else 13)
        run.font.bold = r == 0 or c == 0
        run.font.color.rgb = WHITE if r == 0 else (GREEN if c == 0 else INK)
box(s, 9.55, 1.9, 3.18, 4.6, GREEN, name="One command")
text(s, 9.8, 2.1, 2.7, 0.4, "ONE COMMAND", size=12, bold=True, color=SAFFRON)
box(s, 9.75, 2.6, 2.78, 0.6, GREEN2, radius=0.2, name="Command chip")
text(s, 9.75, 2.6, 2.78, 0.6, "python3 scripts/start.py", size=12, bold=True, font="Courier New", color=WHITE,
     align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, 9.8, 3.4, 2.7, 3.0,
     ["Starts the tunnel and the server", "Creates or updates all 6 agents", "Attaches the tool and the extractions",
      "Re-runs safely: nothing is duplicated"],
     size=14, color=WHITE, spacing=8)
footer(s, "Verified against the live Bolna API, 27–30 Oct 2026. The only manual step left: verifying phone numbers (a free-tier rule).")
notes(s, "This is the Bolna integration in full. Every agent, its tool, its extractions and its three languages are created "
         "through Bolna's API by one command, and a new tunnel URL is pushed to Bolna on every start. We found and documented "
         "several real API behaviours on the way, for example that the extractor sometimes answers in a sentence even when asked "
         "for JSON, so yes/no answers are read leniently.")

# ====================================================================== 6. trust
s = slide()
title(s, "Built so it cannot lie or overspend", "Why an owner can trust it")
cards = [("₹", "Real prices only", "A counter-offer can only cite a price another supplier actually confirmed. A guard in code "
          "blocks anything else, and tests prove it."),
         ("✓", "No yes, no booking", "Over budget, partial or unconfirmed? The owner gets an approval call. Only a clear yes books. "
          "The supplier must confirm the exact order."),
         ("=", "Honest savings", "Measured against what the owner paid last time, never against the highest quote. "
          "A zero saving shows as zero.")]
cwid = (W - 2 * M - 0.6) / 3
for i, (g, h, d) in enumerate(cards):
    x = M + i * (cwid + 0.3)
    box(s, x, 1.95, cwid, 3.85, MINT, name=f"Trust card {i + 1}")
    badge(s, x + 0.3, 2.25, 0.85, g, size=26, name=f"Trust badge {i + 1}")
    text(s, x + 0.3, 3.3, cwid - 0.6, 0.5, h, size=21, bold=True, font=HEAD, color=GREEN)
    text(s, x + 0.3, 3.9, cwid - 0.6, 1.8, d, size=15, color=INK)
text(s, M, 6.15, W - 2 * M, 0.5,
     [[("Every call: ", {"bold": True, "color": GREEN}),
       ("AI disclosed up front  ·  owner call-back offered  ·  \"don't call again\" honoured  ·  ", {}),
       ("234 automated tests", {"bold": True, "color": GREEN})]], size=15, align=PP_ALIGN.CENTER)
notes(s, "Three claims we can defend with code and tests. One: real prices only. Two: no booking without a yes when the order "
         "is over budget, partial or unconfirmed. Three: savings against the owner's own last price. Every call says it is an AI, "
         "offers the owner instead, and honours do-not-call.")

# ====================================================================== 7. demo divider
s = slide(dark=True)
text(s, M, 2.0, 2.0, 1.4, "02", size=80, bold=True, font=HEAD, color=SAFFRON)
text(s, M, 3.35, 10, 1.2, "The demo", size=54, bold=True, font=HEAD, color=WHITE, name="Title")
text(s, M, 4.55, 10, 1.0, "What you will see, step by step, and how each moment answers the problem statement",
     size=22, color=MINT_TXT)
notes(s, "Now the demo. The next slides say exactly what appears on screen, why it matters for the problem, and which Bolna "
         "feature makes it happen.")

# ====================================================================== 8. demo walkthrough
s = slide()
title(s, "What the demo shows, step by step", "The demo")
moments = [("Order form", "Owner lists onions and oil. Before any call, the board shows the plan: Pair 1 Kumar + Ramesh, Pair 2 Gowda + Lakshmi."),
           ("Round 1, live", "Two phones ring. Each price appears 'heard live' as the supplier says it, then 'confirmed' when the call ends."),
           ("Pair 2 bargains", "Gowda is told \"onions ₹25\", a real quote from pair 1, and asked to match."),
           ("Ranking", "Kumar is cheapest on paper but late 2 times out of 3, so Ramesh wins on expected cost."),
           ("Round 2", "Ramesh hears a real rival price, drops to ₹25 and ₹60, and adds 7 days of credit."),
           ("Confirm and receipt", "Ramesh confirms by phone. Receipt: ₹1,100, ₹200 less than last time.")]
for i, (h, d) in enumerate(moments):
    col, row = i % 2, i // 2
    x = M + col * 6.2
    y = 1.95 + row * 1.6
    badge(s, x, y + 0.05, 0.7, str(i + 1), name=f"Moment {i + 1}")
    text(s, x + 0.95, y, 5.0, 0.42, h, size=19, bold=True, font=HEAD, color=GREEN)
    text(s, x + 0.95, y + 0.45, 5.0, 1.05, d, size=14, color=INK)
footer(s, "Demo order: 20 kg onions + 10 litres oil by 07:00, budget ₹1,200. Supplier histories are demo data.")
notes(s, "Read left to right, top to bottom. The board shows each call's status, every price the moment it is confirmed with "
         "the supplier's own words, the full transcript when the call ends, the ranking table, round-2 changes, and finally "
         "a printable receipt. Supplier reliability histories are typed-in demo data and we say so.")

# ====================================================================== 9. mapping
s = slide()
title(s, "How the demo answers the problem statement", "The demo")
rows = [("The problem", "What the demo shows", "Bolna feature behind it"),
        ("Owner spends 15 min phoning", "Haggl places every call; the owner never dials", "Outbound calls, two at a time"),
        ("Prices differ by supplier", "Quotes from each supplier side by side, ranked", "submit_quote tool + quote extraction"),
        ("No time to haggle", "Live price match, then a counter-offer", "Per-call prompt variables (real prices only)"),
        ("Suppliers speak Hindi or Kannada", "Each call starts in that supplier's language", "Multilingual agents (hi, en, kn)"),
        ("Owner must trust the result", "Confirmation call, approval if over budget, receipt", "Extractions + guards in our code")]
tbl = s.shapes.add_table(len(rows), 3, Inches(M), Inches(1.95), Inches(W - 2 * M), Inches(4.5)).table
for c, wd in enumerate((3.6, 4.6, 3.93)):
    tbl.columns[c].width = Inches(wd)
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = GREEN if r == 0 else (MINT if r % 2 else WHITE)
        cell.margin_left = cell.margin_right = Inches(0.15)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        run = cell.text_frame.paragraphs[0].add_run()
        run.text = val
        run.font.name, run.font.size = BODY, Pt(15 if r else 14)
        run.font.bold = r == 0 or c == 0
        run.font.color.rgb = WHITE if r == 0 else (GREEN if c == 0 else INK)
notes(s, "Each part of the problem maps to something visible in the demo and to the Bolna feature that makes it work. "
         "This is the slide to leave up during questions.")

# ====================================================================== 10. free tier
s = slide()
title(s, "Free-tier Bolna: what runs live, and how we designed for it", "The demo")
limits = [("2 calls at once", "Suppliers are called in pairs that sell the same items"),
          ("Verified numbers only", "Teammates play the suppliers; extra suppliers run simulated"),
          ("$5 of credit, about 80 minutes", "Calls kept to one billed minute, about ₹33 per live order"),
          ("60-second calls", "30-second scripts: one question covers every item")]
text(s, M, 1.95, 3.6, 0.4, "Restriction", size=13, bold=True, color=MUTED)
text(s, M + 4.15, 1.95, 3.85, 0.4, "Our design", size=13, bold=True, color=MUTED)
for i, (lim, des) in enumerate(limits):
    y = 2.45 + i * 1.02
    box(s, M, y, 3.6, 0.8, MINT, name=f"Limit {i + 1}")
    text(s, M + 0.2, y, 3.3, 0.8, lim, size=15, bold=True, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)
    arrow(s, M + 3.65, y + 0.4, M + 3.95, y + 0.4)
    text(s, M + 4.15, y, 3.85, 0.8, des, size=15, color=INK, anchor=MSO_ANCHOR.MIDDLE)
box(s, 9.0, 1.95, 3.73, 4.55, GREEN, name="Limitation callout")
text(s, 9.3, 2.2, 3.15, 1.5, "The full ~2-minute demo can't run live on the free tier", size=22, bold=True, font=HEAD,
     color=WHITE)
text(s, 9.3, 3.75, 3.15, 2.6,
     [[("Live: ", {"bold": True, "color": SAFFRON}), ("one pair, Kumar and Ramesh, on real phones.", {})],
      [("Full flow: ", {"bold": True, "color": SAFFRON}), ("all four suppliers in rehearsal mode, same code path, labelled SIMULATED.", {})]],
     size=15, color=WHITE, spacing=10)
notes(s, "We are on Bolna's free tier and could not buy a plan. Two calls at a time, verified numbers only, five dollars of "
         "credit and a one-minute budget per call. So the full two-minute demo with four suppliers can't run live. We designed "
         "around each limit, and we show the live part on real phones and the full flow in rehearsal mode, clearly labelled.")

# ====================================================================== 11. results
s = slide()
title(s, "Cheapest on paper is not cheapest", "Results")
cd = CategoryChartData()
cd.categories = ["Kumar", "Ramesh", "Gowda"]
cd.add_series("Quoted total (₹)", (1100, 1100, 1180))
cd.add_series("Expected cost (₹)", (1228.57, 1137.72, 1244.29))
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(M), Inches(1.9), Inches(7.2), Inches(4.6), cd)
ch = gf.chart
ch.font.name, ch.font.size = BODY, Pt(12)
ch.font.color.rgb = MUTED
ch.has_title = True
ch.chart_title.text_frame.text = "Quoted total vs expected cost, after round 2"
tr = ch.chart_title.text_frame.paragraphs[0].runs[0]
tr.font.size, tr.font.bold, tr.font.color.rgb, tr.font.name = Pt(13), True, INK, BODY
ch.has_legend = True
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.legend.include_in_layout = False
ch.legend.font.size = Pt(12)
plot = ch.plots[0]
plot.gap_width = 70
plot.overlap = -10
for ser, col in zip(plot.series, (LINE, GREEN)):
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = col
plot.has_data_labels = True
dl = plot.data_labels
dl.number_format = '"₹"#,##0'
dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
dl.font.size, dl.font.color.rgb = Pt(12), INK
va = ch.value_axis
va.has_major_gridlines = True
va.major_gridlines.format.line.color.rgb = RGBColor(0xE3, 0xE8, 0xE5)
va.minimum_scale, va.maximum_scale = 0, 1400
va.tick_labels.font.size = Pt(11)
va.format.line.fill.background()
ch.category_axis.tick_labels.font.size = Pt(13)
# stat callouts
stats = [("₹200", "saved on the demo order, 15% below the ₹1,300 Priya paid last time", "Simulated suppliers"),
         ("14.3 min", "of the owner's phone time saved per order, against about 15 minutes of calls by hand", "Simulated suppliers"),
         ("22", "real calls placed through Bolna, 18 completed; round-1 calls average 43 s", "Live, 27–30 Oct")]
for i, (big, label, src) in enumerate(stats):
    y = 1.9 + i * 1.55
    text(s, 8.25, y, 4.5, 0.7, big, size=36, bold=True, font=HEAD, color=SAFFRON if i < 2 else GREEN)
    text(s, 8.25, y + 0.68, 4.5, 0.6, label, size=13, color=INK)
    text(s, 8.25, y + 1.18, 4.5, 0.3, src.upper(), size=10, bold=True, color=MUTED)
footer(s, "Simulated: scripted suppliers on the same code path. Live: our Bolna account. Source: scripts/metrics.py and the order database, 31 Oct 2026.")
notes(s, "Kumar and Ramesh both quote eleven hundred after round 2, but Kumar has been late two times out of three, and Ramesh "
         "gives seven days of credit, so Ramesh's expected cost is lower. The savings and time figures come from the simulated "
         "full order. Live so far: 22 real calls through Bolna. Be honest if asked: no live order has completed booking yet; the "
         "two that reached booking failed on an extraction-format bug fixed on 30 October. Re-run scripts/metrics.py before presenting.")

# ====================================================================== 12. close
s = slide(dark=True)
text(s, M, 0.9, 8, 0.4, "WHAT'S NEXT", size=14, bold=True, color=SAFFRON)
text(s, M, 1.3, 8, 1.0, "From demo to daily habit", size=40, bold=True, font=HEAD, color=WHITE, name="Title")
nxt = [("Test Kannada and English on real calls", "Set up and accepted on all six agents; Hindi is live-tested"),
       ("Paid tier: every supplier in one wave", "Concurrency 10 removes the pairs and the simulated suppliers"),
       ("WhatsApp receipts for the owner", "The receipt already exists; send it where owners already are"),
       ("Real delivery tracking", "Feeds the lateness score that decides who wins")]
for i, (h, d) in enumerate(nxt):
    y = 2.6 + i * 1.0
    badge(s, M, y + 0.05, 0.6, str(i + 1), name=f"Next {i + 1}")
    text(s, M + 0.85, y, 7.0, 0.4, h, size=18, bold=True, color=WHITE)
    text(s, M + 0.85, y + 0.42, 7.0, 0.45, d, size=14, color=MINT_TXT)
text(s, 8.9, 2.6, 3.8, 1.2, "Thank you", size=44, bold=True, font=HEAD, color=WHITE)
text(s, 8.9, 3.8, 3.8, 1.5, "Haggl: your kitchen's voice AI buyer, on Bolna", size=20, color=MINT_TXT)
notes(s, "Next: test Kannada and English on real calls, move to a paid tier so every supplier is called in one wave, send the "
         "receipt on WhatsApp, and feed real delivery data into the reliability score. Thank you.")

prs.save(OUT)
print("saved", OUT)
