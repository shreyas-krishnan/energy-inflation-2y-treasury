// Lay out outputs/build/memo.json as a Word document. Content and numbers come only from the
// JSON (built by src/report.py from the model run); this script is presentation only.
// Usage: node reports/render_memo.js outputs/build/memo.json outputs/deliverables/memo.docx
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, Footer, PageNumber, HeadingLevel,
  PageBreak, TableLayoutType,
} = require("docx");

const [inPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(fs.readFileSync(inPath, "utf8"));

const FONT = "Calibri";
const INK = "1F2933", MUTED = "5B6770", RULE = "C9D1D9", HEAD_FILL = "E8EDF2", CALLOUT_FILL = "FDF3E1", ACCENT = "B86E00";
const PAGE_W = 12240, MARGIN = 1296;           // US Letter, 0.9" margins
const CONTENT_W = PAGE_W - 2 * MARGIN;         // 9648 DXA

const border = { style: BorderStyle.SINGLE, size: 4, color: RULE };
const cellBorders = { top: border, bottom: border, left: border, right: border };

function runs(list, size) {
  return list.map(([text, bold]) => new TextRun({ text, bold: !!bold, font: FONT, size, color: INK }));
}

function table(b) {
  const size = b.small ? 16 : 18;
  const widths = b.widths.map((w) => Math.round(w * CONTENT_W));
  widths[widths.length - 1] += CONTENT_W - widths.reduce((a, c) => a + c, 0);
  const mkCell = (text, i, head) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    borders: cellBorders,
    shading: head ? { type: ShadingType.CLEAR, color: "auto", fill: HEAD_FILL } : undefined,
    margins: { top: 50, bottom: 50, left: 80, right: 80 },
    children: [new Paragraph({ spacing: { before: 0, after: 0 },
      children: [new TextRun({ text: String(text), bold: head, font: FONT, size, color: INK })] })],
  });
  const rows = [new TableRow({ tableHeader: true, children: b.header.map((h, i) => mkCell(h, i, true)) })];
  for (const r of b.rows) rows.push(new TableRow({ cantSplit: true, children: r.map((c, i) => mkCell(c, i, false)) }));
  const out = [new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    layout: TableLayoutType.FIXED, rows })];
  if (b.note) out.push(new Paragraph({ spacing: { before: 40, after: 120 },
    children: [new TextRun({ text: b.note, italics: true, font: FONT, size: 16, color: MUTED })] }));
  else out.push(new Paragraph({ spacing: { before: 0, after: 80 }, children: [] }));
  return out;
}

const children = [];
for (const b of spec.blocks) {
  switch (b.type) {
    case "title":
      children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: b.text })] })); break;
    case "subtitle":
      children.push(new Paragraph({ spacing: { after: 160 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 6 } },
        children: [new TextRun({ text: b.text, font: FONT, size: 17, color: MUTED })] })); break;
    case "h1":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: b.text })] })); break;
    case "h2":
      children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: b.text })] })); break;
    case "p":
      children.push(new Paragraph({ spacing: { after: 100 }, children: runs(b.runs, 20) })); break;
    case "bullets":
      for (const it of b.items) children.push(new Paragraph({ numbering: { reference: "bullets", level: 0 },
        spacing: { after: 50 }, children: [new TextRun({ text: it, font: FONT, size: 20, color: INK })] }));
      children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
      break;
    case "callout": {
      const box = { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 6 };
      const shade = { type: ShadingType.CLEAR, color: "auto", fill: CALLOUT_FILL };
      children.push(new Paragraph({ shading: shade, border: { top: box, left: box, right: box }, spacing: { before: 60, after: 0 },
        children: [new TextRun({ text: b.title, bold: true, font: FONT, size: 24, color: INK })] }));
      children.push(new Paragraph({ shading: shade, border: { bottom: box, left: box, right: box }, spacing: { before: 0, after: 140 },
        children: [new TextRun({ text: b.text, font: FONT, size: 20, color: INK })] }));
      break;
    }
    case "table": children.push(...table(b)); break;
    case "image": {
      const px = (inch) => Math.round(inch * 96);
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 120 }, keepLines: true,
        children: [new ImageRun({ type: "png", data: fs.readFileSync(b.path),
          transformation: { width: px(b.width_in), height: px(b.height_in) },
          altText: { title: "Chart", description: b.path.split("/").pop(), name: "chart" } })] }));
      break;
    }
    case "pagebreak": children.push(new Paragraph({ children: [new PageBreak()] })); break;
    default: throw new Error("unknown block " + b.type);
  }
}

const heading = (size, before, after) => ({
  run: { font: FONT, size, bold: true, color: INK },
  paragraph: { spacing: { before, after }, keepNext: true, keepLines: true },
});

const doc = new Document({
  creator: "energy-inflation-2y-treasury pipeline",
  title: "Energy Inflation and the Two-Year Treasury",
  styles: {
    default: { document: { run: { font: FONT, size: 20, color: INK } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal", ...heading(36, 0, 60) },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, ...heading(26, 220, 80) },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, ...heading(22, 140, 60) },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 15840 },
      margin: { top: 1152, bottom: 1152, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.LEFT, children: [
      new TextRun({ text: spec.footer + "   Page ", font: FONT, size: 14, color: MUTED }),
      new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 14, color: MUTED }),
      new TextRun({ text: " of ", font: FONT, size: 14, color: MUTED }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 14, color: MUTED }),
    ] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => fs.writeFileSync(outPath, buf));
