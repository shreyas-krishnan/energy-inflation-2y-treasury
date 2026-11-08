// Lay out outputs/build/deck.json as a 16:9 PowerPoint deck. Content and numbers come only from
// the JSON (built by src/report.py from the model run); this script is presentation only.
// Usage: node reports/render_deck.js outputs/build/deck.json out.pptx [--only N]
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(path.join(__dirname, "apply_theme.js"));

const args = process.argv.slice(2);
const [inPath, outPath] = args;
const onlyIdx = args.indexOf("--only");
const only = onlyIdx >= 0 ? Number(args[onlyIdx + 1]) : null;
const spec = JSON.parse(fs.readFileSync(inPath, "utf8"));

const THEME = {
  name: "Energy and Treasuries",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1F2933", lt1: "FFFFFF", dk2: "14213D", lt2: "EEF1F5",
    accent1: "D98E04", accent2: "2A78D6", accent3: "1BAF7A", accent4: "EB6834",
    accent5: "5B6770", accent6: "24324F", hlink: "2A78D6", folHlink: "5B6770",
  },
};
const W = 13.333, H = 7.5, MX = 0.6;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Energy Inflation and the Two-Year Treasury";
const C = pres.SchemeColor;

const footer = (dark) => ({ text: { text: spec.footer, options: { x: MX, y: H - 0.45, w: 10.5, h: 0.3, fontSize: 10,
  color: dark ? C.background2 : C.accent5, margin: 0 } } });

pres.defineSlideMaster({
  title: "Dark title", background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 1.0, w: W - 2 * MX, h: 2.0, fontSize: 40, bold: true, align: "left",
      color: C.background1, valign: "bottom", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: MX, y: 3.15, w: W - 2 * MX, h: 0.5, fontSize: 18,
      color: C.background2, margin: 0 }, text: "" } },
    footer(true),
  ],
});
pres.defineSlideMaster({
  title: "Title only", background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: W - 2 * MX, h: 1.3, fontSize: 32, bold: true, align: "left",
      color: C.text2, valign: "top", margin: 0 }, text: "" } },
    footer(false),
  ],
  slideNumber: { x: W - MX - 0.5, y: H - 0.45, w: 0.5, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "Dark close", background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.5, w: W - 2 * MX, h: 1.1, fontSize: 40, bold: true, align: "left",
      color: C.background1, valign: "top", margin: 0 }, text: "" } },
    footer(true),
  ],
});

// Motif: numbered amber circle
function marker(slide, x, y, num, name) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { type: "none" },
    objectName: `${name}-marker` });
  slide.addText(String(num), { x, y, w: 0.42, h: 0.42, fontSize: 14, bold: true, color: C.background1, align: "center",
    valign: "middle", margin: 0, isTextBox: true, objectName: `${name}-num` });
}

function pointList(slide, pts, x, y, w, rowH, dark, name) {
  pts.forEach((p, i) => {
    marker(slide, x, y + i * rowH, i + 1, `${name}-${i}`);
    slide.addText(p, { x: x + 0.6, y: y + i * rowH - 0.05, w: w - 0.6, h: rowH - 0.1, fontSize: 16,
      color: dark ? C.background1 : C.text1, valign: "top", margin: 0, isTextBox: true, objectName: `${name}-text-${i}` });
  });
}

function fitImage(im, maxW, maxH) {
  let w = Math.min(im.width_in, maxW), h = w * im.height_in / im.width_in;
  if (h > maxH) { h = maxH; w = h * im.width_in / im.height_in; }
  return { w, h };
}

const sections = { title: "Question", chart: "Evidence", ladder: "Evidence", wide: "Evidence", cards: "Decision", close: "Decision" };
let lastSection = null;

spec.slides.forEach((s, i) => {
  if (only !== null && i + 1 !== only) return;
  const sec = sections[s.kind];
  if (sec !== lastSection) { pres.addSection({ title: sec }); lastSection = sec; }
  const master = s.kind === "title" ? "Dark title" : s.kind === "close" ? "Dark close" : "Title only";
  const slide = pres.addSlide({ masterName: master, sectionTitle: sec });
  slide.addText(s.title, { placeholder: "title" });

  if (s.kind === "title") {
    slide.addText(s.subtitle, { placeholder: "body" });
    const cw = (W - 2 * MX - 2 * 0.35) / 3;
    s.stats.forEach(([val, lab], j) => {
      const x = MX + j * (cw + 0.35), y = 4.3;
      slide.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 2.0, fill: { color: C.accent6 }, line: { type: "none" },
        objectName: `stat-card-${j}` });
      slide.addText(val, { x: x + 0.3, y: y + 0.25, w: cw - 0.6, h: 1.0, fontSize: val.length > 12 ? 24 : 40, bold: true,
        color: C.accent1, fontFace: THEME.headFontFace, valign: "middle", margin: 0, isTextBox: true, objectName: `stat-val-${j}` });
      slide.addText(lab, { x: x + 0.3, y: y + 1.3, w: cw - 0.6, h: 0.5, fontSize: 16, color: C.background2, margin: 0,
        isTextBox: true, objectName: `stat-lab-${j}` });
    });
  } else if (s.kind === "chart") {
    const { w, h } = fitImage(s.image, 8.1, 5.0);
    slide.addImage({ path: s.image.path, x: MX, y: 1.85, w, h, altText: s.title, objectName: "chart" });
    pointList(slide, s.points, MX + w + 0.45, 2.0, W - MX - (MX + w + 0.45), 1.15, false, "point");
  } else if (s.kind === "ladder") {
    const cw = 3.55, gap = 0.75, y = 2.3;
    s.steps.forEach(([val, lab], j) => {
      const x = MX + j * (cw + gap);
      const last = j === s.steps.length - 1;
      slide.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 2.2, fill: { color: last ? C.text2 : C.background2 },
        line: { type: "none" }, objectName: `step-${j}` });
      slide.addText(val, { x: x + 0.3, y: y + 0.25, w: cw - 0.6, h: 1.0, fontSize: 44, bold: true, fontFace: THEME.headFontFace,
        color: last ? C.accent1 : C.text2, margin: 0, isTextBox: true, objectName: `step-val-${j}` });
      slide.addText(lab, { x: x + 0.3, y: y + 1.3, w: cw - 0.6, h: 0.75, fontSize: 16, color: last ? C.background1 : C.text1,
        valign: "top", margin: 0, isTextBox: true, objectName: `step-lab-${j}` });
      if (!last) slide.addShape(pres.shapes.RIGHT_ARROW, { x: x + cw + 0.15, y: y + 0.85, w: gap - 0.3, h: 0.5,
        fill: { color: C.accent5 }, line: { type: "none" }, objectName: `arrow-${j}` });
    });
    const pw = (W - 2 * MX - 2 * 0.4) / 3;
    s.points.forEach((p, j) => {
      const x = MX + j * (pw + 0.4);
      marker(slide, x, 5.25, j + 1, `ctx-${j}`);
      slide.addText(p, { x: x + 0.6, y: 5.2, w: pw - 0.6, h: 1.1, fontSize: 16, color: C.text1, valign: "top", margin: 0,
        isTextBox: true, objectName: `ctx-text-${j}` });
    });
  } else if (s.kind === "wide") {
    const { w, h } = fitImage(s.image, W - 2 * MX, 5.1);
    slide.addImage({ path: s.image.path, x: (W - w) / 2, y: 1.8, w, h, altText: s.title, objectName: "chart" });
  } else if (s.kind === "cards") {
    const cw = (W - 2 * MX - 0.4) / 2, ch = 2.1;
    s.cards.forEach(([head, body], j) => {
      const x = MX + (j % 2) * (cw + 0.4), y = 1.85 + Math.floor(j / 2) * (ch + 0.35);
      slide.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: ch, fill: { color: C.background2 }, line: { type: "none" },
        objectName: `card-${j}` });
      marker(slide, x + 0.35, y + 0.4, j + 1, `card-${j}`);
      slide.addText(head, { x: x + 0.95, y: y + 0.32, w: cw - 1.25, h: 0.6, fontSize: 22, bold: true, color: C.text2,
        fontFace: THEME.headFontFace, margin: 0, isTextBox: true, objectName: `card-head-${j}` });
      slide.addText(body, { x: x + 0.95, y: y + 1.0, w: cw - 1.25, h: 1.05, fontSize: 16, color: C.text1, valign: "top",
        margin: 0, isTextBox: true, objectName: `card-body-${j}` });
    });
  } else if (s.kind === "close") {
    pointList(slide, s.points, MX, 2.1, 6.6, 1.3, true, "cond");
    const x = 7.75, w = W - MX - x;
    slide.addShape(pres.shapes.RECTANGLE, { x, y: 1.9, w, h: 0.95 + 0.62 * s.next.length, fill: { color: C.accent6 },
      line: { type: "none" }, objectName: "next-card" });
    slide.addText("Next releases to watch", { x: x + 0.35, y: 2.1, w: w - 0.7, h: 0.5, fontSize: 20, bold: true,
      color: C.accent1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true, objectName: "next-head" });
    slide.addText(s.next.map((t, j) => ({ text: t, options: { breakLine: j < s.next.length - 1 } })),
      { x: x + 0.35, y: 2.7, w: w - 0.7, h: 0.62 * s.next.length, fontSize: 16, color: C.background1, valign: "top",
        paraSpaceAfter: 8, margin: 0, isTextBox: true, objectName: "next-list" });
  }
  if (s.notes) slide.addNotes(s.notes);
});

(async () => {
  await pres.writeFile({ fileName: outPath });
  await applyTheme(outPath, THEME);
})();
