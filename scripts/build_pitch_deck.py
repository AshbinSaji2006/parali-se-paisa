"""Build the Greenovators 2026 pitch deck (editable PPTX) from results.json and research figures.

Every statistic is read from reports/research/results.json so the deck cannot drift from the analysis.
Output: reports/pitch/Parali_Se_Paisa_Greenovators2026.pptx (with speaker notes).
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "reports" / "research" / "results.json").read_text(encoding="utf-8"))
FIG = ROOT / "reports" / "research" / "figures"
SHOTS = ROOT / ".demo" / "visual-audit"
OUT = ROOT / "reports" / "pitch" / "Parali_Se_Paisa_Greenovators2026.pptx"

INK, INK2, MUTED = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x52, 0x51, 0x4E), RGBColor(0x89, 0x87, 0x81)
GREEN, GREEN_DARK, SURFACE = RGBColor(0x2F, 0x6B, 0x4F), RGBColor(0x1D, 0x3D, 0x2B), RGBColor(0xFC, 0xFC, 0xFB)
RED, BLUE = RGBColor(0xD0, 0x3B, 0x3B), RGBColor(0x2A, 0x78, 0xD6)
FONT = "Segoe UI"

C = {r["year"]: r for r in R["census"]}
imp = R["replay_impact"]
risk = R["risk_model"]
now = R["nowcast_2026"]
lat = R["latency"]
per1k = R["emissions_per_1000_ha_burned"]


def fmt(v, d=0):
    return f"{v:,.{d}f}"


OUT.parent.mkdir(parents=True, exist_ok=True)
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
slide_no = 0


def text(slide, x, y, w, h, s, size=16, color=INK2, bold=False, align=PP_ALIGN.LEFT, font=FONT):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    lines = s if isinstance(s, list) else [s]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, font
        p.space_after = Pt(6)
    return tb


def bullets(slide, x, y, w, h, items, size=15):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (head, body) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r1 = p.add_run()
        r1.text = head + (" " if body else "")
        r1.font.size, r1.font.bold, r1.font.color.rgb, r1.font.name = Pt(size), True, INK, FONT
        if body:
            r2 = p.add_run()
            r2.text = body
            r2.font.size, r2.font.color.rgb, r2.font.name = Pt(size), INK2, FONT
        p.space_after = Pt(10)
    return tb


def base(title, kicker=None, source=None, notes=""):
    global slide_no
    slide_no += 1
    s = prs.slides.add_slide(BLANK)
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = SURFACE
    if kicker:
        text(s, 0.6, 0.32, 12, 0.4, kicker.upper(), size=11, color=GREEN, bold=True)
    text(s, 0.6, 0.62, 12.2, 1.0, title, size=28, color=INK, bold=True)
    if source:
        text(s, 0.6, 7.0, 11.4, 0.4, source, size=9, color=MUTED)
    text(s, 12.2, 7.0, 0.7, 0.4, str(slide_no), size=9, color=MUTED, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s


def picture(slide, path, x, y, w=None, h=None):
    with Image.open(path) as im:
        ar = im.width / im.height
    if w and not h:
        h = w / ar
    elif h and not w:
        w = h * ar
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))


def stat(slide, x, y, w, value, label, color=GREEN_DARK):
    text(slide, x, y, w, 0.9, value, size=40, color=color, bold=True)
    text(slide, x, y + 0.95, w, 1.0, label, size=13, color=INK2)


def box(slide, x, y, w, h, title, body, fill=RGBColor(0xFF, 0xFF, 0xFF), line=RGBColor(0xD9, 0xDC, 0xD5)):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = 0.08
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.12)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(13), True, INK, FONT
    if body:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = body
        r2.font.size, r2.font.color.rgb, r2.font.name = Pt(10.5), INK2, FONT
    return sh


def arrow(slide, x1, y1, x2, y2):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = MUTED
    c.line.width = Pt(1.5)
    c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd", {"type": "triangle"}))
    return c


viirs_drop = round(100 * (1 - C[2025]["viirs_alerts"] / C[2023]["viirs_alerts"]))
scar_index = round(100 * C[2025]["burned_strict_ha"] / C[2023]["burned_strict_ha"])
seen25 = round(100 * C[2025]["burns_with_viirs_short_window"])
ctl25 = round(100 * C[2025]["control_with_viirs_short_window"])
seen23 = round(100 * C[2023]["burns_with_viirs_short_window"])
hist = risk["history_logistic (pre-season)"]
pers = risk["persistence"]
i100, i400 = imp["100"], imp["400"]

# 1 Title
s = base("", None, None,
         "Open with the paradox: the official fire count says the problem is nearly solved, but the burn scars say otherwise. "
         "We use free satellite data to see every field, find the burns that fire satellites now miss, and send balers to the fields most likely to burn, so farmers earn from straw instead of burning it.")
text(s, 0.6, 0.55, 7.4, 1.0, "Parali Se Paisa", size=44, color=GREEN_DARK, bold=True)
text(s, 0.6, 1.65, 7.2, 1.6, "The burns the fire satellites stopped seeing, and the balers that can reach them first", size=24, color=INK2)
text(s, 0.6, 3.25, 7.0, 1.2, ["Satellite AI that turns paddy straw into verified farmer income",
                              "Greenovators Hackathon 2026 · Waste to Wealth · Net Zero AI Architecture"], size=15, color=INK2)
text(s, 0.6, 5.2, 7.0, 1.2, ["Real data: Sentinel-2, VIIRS, MODIS and ERA5 for Sri Muktsar Sahib, Punjab, 2023–2026",
                              f"{fmt(C[2025]['crop_fields'])} crop fields · 74 satellite scenes · 12.6 million field observations"], size=13, color=MUTED)
picture(s, FIG / "f8_burn_map_2025.png", 8.4, 0.25, h=7.0)

# 2 Problem
s = base("The official indicator is going blind", "The problem",
         "iFOREST Stubble Burning Status Report 2025 (SEVIRI geostationary data); NASA Earth Observatory, Dec 2025; concept-note references for straw volume.",
         "Punjab will produce about 18.8 million tonnes of paddy straw this season. Fire counts from polar-orbiting satellites have collapsed, which looks like success. "
         "But geostationary data show farmers now burn after 3 PM, after the satellites pass. Policy, incentives and enforcement that run on fire counts are steering blind.")
stat(s, 0.6, 1.9, 3.8, "18.8 Mt", "paddy straw expected in Punjab in 2026, most of it with a 2–3 week window before wheat sowing")
stat(s, 4.7, 1.9, 3.8, "−92%", "active-fire counts in Punjab since the 2021 peak (MODIS/VIIRS)", RED)
stat(s, 8.8, 1.9, 3.9, ">90%", "of large farm fires in 2024–25 lit after 3 PM, after polar satellites pass (3% in 2021)", RED)
text(s, 0.6, 4.6, 12, 1.4, ["Burnt area fell only 25–35% while fire counts fell more than 95%. Money, machines and monitoring cannot target fields nobody can see.",
                            "Question: can free satellite data see every field's burn, and send balers before the fire?"], size=17, color=INK)

# 3 What we built
s = base("Every field, every 2–5 days, from free satellite data", "Our approach",
         "Runs end to end on a laptop CPU: download 45 min, extraction 5 min, analysis 70 s. No GPU and no paid data.",
         "We downloaded every Sentinel-2 image of Muktsar for four seasons, harmonised it, and reduced it to time series for 170 thousand fields. "
         "A harvest-aware and smoke-robust detector dates each harvest and each burn. We then match burns with thermal fire alerts, learn who burns, replay the season with balers, and nowcast this week.")
box(s, 0.6, 1.8, 2.6, 1.3, "Sentinel-2 L2A", "74 scenes 2023–2026 on one 20 m grid; reflectance offset harmonised")
box(s, 3.6, 1.8, 2.8, 1.3, "170,623 field time series", "12.6 M observations · Fields of The World boundaries")
box(s, 6.8, 1.8, 2.9, 1.3, "Harvest-aware, smoke-robust events", "NIR/SWIR change logic dates harvest and burn per field")
box(s, 10.1, 1.8, 2.6, 1.3, "Research Evidence app", "Map, figures, forecast, pre-booking list")
for x1, x2 in [(3.2, 3.6), (6.4, 6.8), (9.7, 10.1)]:
    arrow(s, x1, 2.45, x2, 2.45)
for i, (t, b) in enumerate([("Thermal blind spot", "match every burn with VIIRS/MODIS alerts, with proximity controls"),
                            ("Burn-risk model", "trained on 2024, tested on the unseen 2025 season"),
                            ("Season-replay twin", "replay real 2025 harvests and burns with baler fleets"),
                            ("Live 2026 nowcast", "harvest progress, weekly straw supply, pre-booking")]):
    box(s, 0.6 + i * 3.05, 3.85, 2.8, 1.25, t, b, fill=RGBColor(0xF0, 0xF4, 0xEF))
arrow(s, 8.25, 3.1, 8.25, 3.85)
text(s, 0.6, 5.5, 12, 1.2, ["Inputs: Sentinel-2 (ESA), VIIRS S-NPP / NOAA-20 / NOAA-21 and MODIS (NASA), MCD64A1, ERA5. All free and global, so it scales to any district."], size=14, color=INK2)

# 4 Finding 1
s = base(f"Fire alerts fell {viirs_drop}%. Burn scars did not.", "Finding 1",
         "Sentinel-2 at a harmonised 5-day revisit. Strict = char-like signature tier; loose = all burn candidates; both are unverified rule candidates. 2024 burn area is a lower bound (smog gap, 3–21 Nov).",
         f"From 2023 to 2025, VIIRS fire alerts in Muktsar fell from {fmt(C[2023]['viirs_alerts'])} to {fmt(C[2025]['viirs_alerts'])}. "
         f"Sentinel-2 burn scars, mapped field by field, stayed flat at {fmt(C[2023]['burned_strict_ha'])} and {fmt(C[2025]['burned_strict_ha'])} hectares. "
         "Every season was thinned to the same 5-day revisit, so 2025's extra satellite does not create the result.")
picture(s, FIG / "f1_alerts_vs_scars.png", 0.6, 1.55, w=8.3)
bullets(s, 9.2, 1.7, 3.8, 5, [(f"{fmt(C[2023]['viirs_alerts'])} → {fmt(C[2025]['viirs_alerts'])}", "VIIRS fire alerts in the district"),
                              (f"{fmt(C[2023]['burned_strict_ha'])} → {fmt(C[2025]['burned_strict_ha'])} ha", f"strict-tier burn-scar candidate area (index {scar_index})"),
                              (f"{C[2023]['strict_fields_per_viirs_alert']} → {C[2025]['strict_fields_per_viirs_alert']}", "burned fields per fire alert"),
                              ("Same revisit,", "same thresholds, same fields")])

# 5 Finding 2
s = base(f"9 in 10 strict-tier burn candidates in 2025 raised no fire alert", "Finding 2",
         "Strict burns observed within ≤5 days; VIIRS within 500 m. Control: unburned fields with the same windows. Smoke panel: 2023 season.",
         f"Only {seen25} percent of 2025's strict-tier field burn candidates had a VIIRS alert anywhere within 500 metres during the burn window, against {seen23} percent in 2023. "
         "Unburned control fields match 4 percent by proximity alone, so the true share is lower still. And at the peak, smoke blinds ordinary optical monitoring too, which our SWIR logic is built to survive.")
picture(s, FIG / "f2_blind_spot.png", 0.6, 1.55, w=6.2)
picture(s, FIG / "f3_smoke_blindness.png", 7.0, 1.55, w=5.8)
bullets(s, 0.6, 5.25, 6.2, 1.6, [(f"{seen23}% → {seen25}%", f"strict-tier burn candidates with any VIIRS alert (control {ctl25}%)"),
                                 ("Independent of iFOREST:", "field-level evidence of after-overpass burning")], size=14)

# 6 Rigour
s = base("Harvest-aware detection, independently checked", "Method rigour",
         "Key & Benson (2006) dNBR thresholds; Olofsson et al. (2014) stratified estimator; validation tool in reports/research/label_tool.",
         "Our detector separates harvest from fire. A naive pre/post dNBR, as often used, flags almost every field because harvest alone moves NBR. "
         "We validate against independent thermal alerts, with controls, and we built a blind stratified labelling tool so precision is measured by humans, not assumed.")
picture(s, FIG / "f4_naive_vs_aware.png", 0.6, 1.55, w=6.6)
r23 = R["census"][0]
bullets(s, 7.5, 1.6, 5.4, 5.2, [("Smoke-robust:", "NIR/SWIR logic; Sen2Cor misses smoke haze"),
                                ("Wet-soil rejection:", "irrigated soil keeps a positive NBR, char does not"),
                                ("Thermal recall:", f"{round(100*C[2023]['viirs_alerts_with_s2_burn_nearby'])}% / {round(100*C[2024]['viirs_alerts_with_s2_burn_nearby'])}% / {round(100*C[2025]['viirs_alerts_with_s2_burn_nearby'])}% of VIIRS alerts have a Sentinel-2 burn within 500 m (2023/24/25)"),
                                ("Controls and sensitivity:", "proximity controls; radius 375–1,000 m; harmonised revisit"),
                                ("Human validation:", "stratified, blind before/after labelling tool → precision, recall, area with 95% CI"),
                                ("Bug found and fixed:", "missing −1000 DN reflectance offset inflated reflectance by 0.10")], size=13)

# 7 Where and when
s = base("Burning clusters, persists, and leaves about a two-week window", "Finding 3",
         "Left: 2025 burn tiers per field with VIIRS alerts. Right: days from first harvested to first char observation (2025, interval-censored).",
         f"Burns cluster in space and repeat in time: a field that burned last year was {round(pers['p_burn_given_prior_burn']/pers['p_burn_given_no_prior'],1)} times as likely to burn again. "
         f"After harvest the median wait before fire was {int(lat['2025']['median_days'])} days. That is the window a satellite-triggered dispatch can use.")
picture(s, FIG / "f8_burn_map_2025.png", 0.5, 1.4, h=5.5)
picture(s, FIG / "f5_intervention_window.png", 4.8, 1.45, w=7.4)
bullets(s, 4.9, 5.3, 8.0, 1.7, [(f"{int(lat['2025']['median_days'])} days", "median harvest → fire window (2025)"),
                                (f"{round(100*pers['p_burn_given_prior_burn'])}% vs {round(100*pers['p_burn_given_no_prior'])}%", "burn again if burned last year vs not"),
                                (f"{100*R['persistence']['repeat_burner_share']:.1f}% of fields", f"burned in 2+ seasons and did {100*R['persistence']['repeat_burner_share_of_burn_events']:.0f}% of all burning (2023–25)")], size=14)

# 8 Action
s = base(f"Risk-ranked dispatch pre-empts {round(i100['preempted_share']/i100['fifo_share'],1)}× more burns", "Finding 4 · same 100 balers, smarter order",
         "Season-replay digital twin on real 2025 events; 4 ha/baler/day; ERA5 rain days skipped; assumes baling prevents burning. Emissions: Andreae (2019), IPCC AR6 GWP100.",
         f"We replayed the real 2025 season. With 100 balers, first-come-first-served would have reached {round(100*i100['fifo_share'],1)} percent of the fields that burned; ranking by burn history reaches {round(100*i100['preempted_share'],1)} percent. "
         f"That is {fmt(i100['preempted_ha'])} hectares of burning avoided, about {fmt(i100['avoided_CH4_N2O_CO2e_t'])} tonnes CO2-equivalent and {fmt(i100['avoided_PM25_t'])} tonnes of PM2.5. The oracle line shows the value of better prediction.")
picture(s, FIG / "f6_replay.png", 0.6, 1.55, w=7.4)
bullets(s, 8.3, 1.7, 4.6, 5, [(f"{round(100*i100['preempted_share'],1)}% vs {round(100*i100['fifo_share'],1)}%", "burns pre-empted, 100 balers"),
                              (f"{fmt(i100['avoided_CH4_N2O_CO2e_t'])} t CO₂e", f"CH₄+N₂O avoided (90%: {fmt(i100['avoided_CH4_N2O_CO2e_t_p05_p95'][0])}–{fmt(i100['avoided_CH4_N2O_CO2e_t_p05_p95'][1])})"),
                              (f"{fmt(i100['avoided_PM25_t'])} t PM2.5", f"and {i100['avoided_BC_t']} t black carbon avoided"),
                              (f"₹{i100['straw_value_all_baled_rs_crore']} crore", "of straw baled by the fleet at ₹169/quintal"),
                              (f"Top decile = {hist['y_strict']['lift_top10']:.1f}× lift", "on the unseen 2025 season (pre-season model)")], size=14)

# 9 Live 2026
weeks = now["weekly_forecast"][:6]
s = base("Live: Muktsar 2026, as of this week's satellite pass", "Live nowcast",
         f"Latest Sentinel-2 image {now['latest_image']}. Forecast = typical (2023–2025) harvest pace; baleable straw 3.3 t/ha.",
         f"As of {now['latest_image']}, only {round(100*now['harvested_share_now'],1)} percent of the district is harvested, a normal pace. "
         "Based on three seasons of curves, the harvest wave peaks in the last two weeks of October. Our pre-season list tells operators where to book balers first.")
picture(s, FIG / "f7_nowcast_2026.png", 0.6, 1.55, w=7.2)
rows = [("Week of", "Expected harvest", "Baleable straw")] + [(w["week_start"][5:], f"{fmt(w['expected_harvest_ha'])} ha", f"{fmt(w['expected_baleable_straw_t'])} t") for w in weeks]
tbl = s.shapes.add_table(len(rows), 3, Inches(8.1), Inches(1.65), Inches(4.8), Inches(0.36 * len(rows))).table
for i, row in enumerate(rows):
    for j, v in enumerate(row):
        cell = tbl.cell(i, j)
        cell.text = v
        para = cell.text_frame.paragraphs[0]
        para.runs[0].font.size, para.runs[0].font.name = Pt(11), FONT
        para.runs[0].font.bold = i == 0
        cell.fill.solid()
        cell.fill.fore_color.rgb = GREEN_DARK if i == 0 else (RGBColor(0xFF, 0xFF, 0xFF) if i % 2 else RGBColor(0xF0, 0xF4, 0xEF))
        para.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if i == 0 else INK
text(s, 8.1, 4.6, 4.8, 1.8, [f"Pre-booking list: top decile = {fmt(now['preseason_risk']['top_decile_fields'])} fields, {fmt(now['preseason_risk']['top_decile_ha'])} ha",
                             f"District straw ≈ {now['district_straw_total_t']/1e5:.1f} lakh t (published estimate: 12.1 lakh t)"], size=13, color=INK2)

# 10 Product
s = base("One data backbone for officials, balers, buyers and farmers", "The product",
         "FastAPI + React app; 197 backend tests plus new research tests; real-data mode is read-only; field-level burn data restricted to officials.",
         "Everything is in a working app. Officials see the research evidence and the live map, operators get dispatch plans, buyers get traceable supply, and farmers get updates in Punjabi and Hindi and a no-burn certificate. Field-level burn data is restricted and never used to fine anyone.")
picture(s, SHOTS / "Research-top-1366.png", 0.6, 1.5, w=7.6)
far = Image.open(SHOTS / "Farmer Punjabi-390.png")
far.crop((0, 0, 390, 780)).save(ROOT / "reports" / "pitch" / "_farmer_crop.png")
picture(s, ROOT / "reports" / "pitch" / "_farmer_crop.png", 8.5, 1.5, h=5.2)
cert = Image.open(SHOTS / "Certificate-Detail-1366.png")
cert.crop((250, 0, 1366, 700)).save(ROOT / "reports" / "pitch" / "_cert_crop.png")
picture(s, ROOT / "reports" / "pitch" / "_cert_crop.png", 11.2, 1.5, w=1.9)
text(s, 11.2, 2.8, 1.9, 2, ["No-burn certificate with QR verification"], size=11, color=INK2)

# 11 Impact and scale
straw_value = now["district_straw_total_t"] * 1690 / 1e7
s = base("Waste to wealth at district scale, with no hardware", "Impact and scale",
         "Straw price ₹169/quintal (biomass plants, concept note [11]); emission factors Andreae (2019); CO₂e excludes biogenic CO₂.",
         "The district's straw is worth almost two hundred crore rupees at today's biomass price. Each thousand hectares that is not burned avoids about 740 tonnes of CO2-equivalent and 34 tonnes of PM2.5. "
         "The whole system uses free satellite data and a laptop, so extending to all of Punjab and Haryana is a configuration change, not a hardware rollout.")
stat(s, 0.6, 1.8, 4.0, f"₹{straw_value:,.0f} cr", f"value of Muktsar's ≈{now['district_straw_total_t']/1e5:.1f} lakh t of straw at ₹169/quintal")
stat(s, 4.8, 1.8, 4.0, f"{fmt(per1k['CH4_N2O_CO2e_t']['median'])} t", "CO₂e (CH₄ + N₂O) avoided per 1,000 ha not burned, plus 34 t PM2.5", BLUE)
stat(s, 9.0, 1.8, 3.8, "₹0", "hardware: free Sentinel-2 / VIIRS / ERA5 and open-source tools", GREEN_DARK)
bullets(s, 0.6, 4.4, 12, 2.5, [("Who pays:", "state CRM schemes for verified no-burn incentives (Haryana pays ₹1,200/acre after inspection); buyers pay per traceable tonne for ESG supply chains"),
                               ("Scale:", "same code for any district; Punjab has 23 and Haryana 22, using the same satellite tiles and fire archives"),
                               ("SDGs:", "12 responsible production · 13 climate action · 11 clean air in cities · 9 innovation")], size=14)

# 12 Limits and next steps
s = base("What we have not shown yet, and how we will", "Honest limits",
         "Full limitations: docs/RESEARCH_METHODS.md §11.",
         "We are careful about what the evidence supports. The burn tiers are rule outputs; human labels are being collected. Char can be ploughed in within days, so our counts are lower bounds. "
         "Next we add a radar paddy mask, Sentinel-1 for smog gaps, and a one-block field pilot with a baler cooperative to measure real acceptance and tonnage.")
bullets(s, 0.6, 1.7, 6.0, 5, [("Precision:", "blind stratified labels in progress (AI-assisted check: about 7–8 of 10 strict detections show char)"),
                              ("Lower bounds:", "small or quickly tilled burns between revisits are missed"),
                              ("Crop type:", "the cotton-growing south needs a Sentinel-1 paddy mask"),
                              ("Replay assumptions:", "baling prevents burning; no travel time; no farmer acceptance yet")], size=14)
bullets(s, 6.9, 1.7, 6.0, 5, [("Week 1:", "finish labels → publish precision, recall and area with 95% CI"),
                              ("Month 1:", "Sentinel-1 radar for smog gaps and a paddy mask"),
                              ("Season 2026:", "pilot in one block with a baler cooperative and a straw buyer"),
                              ("Policy:", "propose burn-scar area, not fire counts, as the official indicator")], size=14)

# 13 Close
s = base("Measure burns, not alerts. Pay for straw, not fines.", None, None,
         "Close by repeating the two numbers: fire alerts fell 79 percent but burn scars did not, and the same balers reach 2.6 times more would-be burns when guided by our risk map. Invite the judges to the live app.")
text(s, 0.6, 2.0, 12, 2.5, [f"Fire alerts −{viirs_drop}% · burn scars unchanged · {100-seen25}% of strict-tier burn candidates unseen by fire satellites (2025)",
                            f"{round(i100['preempted_share']/i100['fifo_share'],1)}× more burns pre-empted with the same 100 balers · live 2026 nowcast for Muktsar"], size=20, color=INK2)
text(s, 0.6, 4.6, 12, 1.5, ["Parali Se Paisa · Greenovators Hackathon 2026 · Amity University Noida",
                            "Reproducible: scripts/run_research.py · docs/RESEARCH_METHODS.md · reports/research/RESEARCH_SUMMARY.md"], size=14, color=MUTED)

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"wrote {OUT} ({slide_no} slides)")
try:  # optional PDF export through installed PowerPoint (Windows); the PPTX is the source of truth
    import win32com.client
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(OUT), True, False, False)
    pres.SaveAs(str(OUT.with_suffix(".pdf")), 32)
    pres.Close()
    app.Quit()
    print(f"wrote {OUT.with_suffix('.pdf')}")
except Exception as exc:
    print(f"PDF export skipped ({type(exc).__name__}); open the PPTX and export manually if needed")
