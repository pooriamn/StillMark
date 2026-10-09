from pathlib import Path
import yaml
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, ListFlowable, ListItem

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets' / 'documents'
PAGE_W, PAGE_H = A4
MARGIN_X = 22 * mm
MARGIN_Y = 20 * mm
USABLE_W = PAGE_W - 2 * MARGIN_X


def load_yaml(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


site = load_yaml(ROOT / 'content' / 'site.yaml')
artist = load_yaml(ROOT / 'content' / 'artist.yaml')
series = [load_yaml(p) for p in sorted((ROOT / 'content' / 'series').glob('*.yaml'))]
works = [load_yaml(p) for p in sorted((ROOT / 'content' / 'works').glob('*.yaml'))]
series_lookup = {item.get('slug') or item.get('id'): item for item in series}
work_lookup = {item['id']: item for item in works}

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='DocTitle', fontName='Helvetica-Bold', fontSize=22, leading=28, textColor=colors.HexColor('#111111'), spaceAfter=8))
styles.add(ParagraphStyle(name='DocSubtitle', fontName='Helvetica', fontSize=10.5, leading=15, textColor=colors.HexColor('#555555'), spaceAfter=16))
styles.add(ParagraphStyle(name='SectionHead', fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=colors.HexColor('#222222'), spaceBefore=12, spaceAfter=6))
styles.add(ParagraphStyle(name='BodySmall', fontName='Helvetica', fontSize=9.6, leading=14, textColor=colors.HexColor('#222222'), spaceAfter=8))
styles.add(ParagraphStyle(name='MonoMeta', fontName='Helvetica', fontSize=8.7, leading=11, textColor=colors.HexColor('#666666'), spaceAfter=4))
styles.add(ParagraphStyle(name='TableCell', fontName='Helvetica', fontSize=9.0, leading=12, textColor=colors.HexColor('#222222')))
styles.add(ParagraphStyle(name='TableCellBold', parent=styles['TableCell'], fontName='Helvetica-Bold'))


def footer_canvas(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#D5D5D5'))
    canvas.line(MARGIN_X, 14 * mm, PAGE_W - MARGIN_X, 14 * mm)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawString(MARGIN_X, 9 * mm, site['name'])
    canvas.drawRightString(PAGE_W - MARGIN_X, 9 * mm, f'Page {doc.page}')
    canvas.restoreState()


def build_doc(path: Path, story, title: str):
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y,
        bottomMargin=22 * mm,
        title=title,
        author=artist['name'],
    )
    doc.build(story, onFirstPage=footer_canvas, onLaterPages=footer_canvas)


def title_block(kicker: str, title: str, subtitle: str):
    return [
        Paragraph(kicker, styles['MonoMeta']),
        Paragraph(title, styles['DocTitle']),
        Paragraph(subtitle, styles['DocSubtitle']),
        Spacer(1, 4),
    ]


def p(text: str, bold: bool = False):
    return Paragraph(text, styles['TableCellBold' if bold else 'TableCell'])


def table(rows, col_widths, header=True):
    cooked = []
    for row_index, row in enumerate(rows):
        cooked_row = []
        for cell in row:
            text = str(cell)
            cooked_row.append(p(text, bold=header and row_index == 0))
        cooked.append(cooked_row)
    tbl = Table(cooked, colWidths=col_widths, hAlign='LEFT', repeatRows=1 if header else 0)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F3F3') if header else colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FBFBFB')]),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#E3E3E3')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#D8D8D8')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return tbl


def bullet_list(items):
    return ListFlowable(
        [ListItem(Paragraph(item, styles['BodySmall'])) for item in items],
        bulletType='bullet',
        start='circle',
        leftIndent=14,
        bulletFontName='Helvetica',
        bulletFontSize=8,
    )


press_story = []
press_story += title_block(
    'STILLMRK / PRESS KIT',
    'Press kit',
    'A concise public dossier for editors, curators, and collaborators. This version is intentionally compact and can be expanded later with publication history, exhibitions, and editions.',
)
press_story += [
    Paragraph('Studio overview', styles['SectionHead']),
    Paragraph(artist['tagline'], styles['BodySmall']),
    Paragraph(artist['intro'], styles['BodySmall']),
    Paragraph(artist['about'], styles['BodySmall']),
    Paragraph('Practice note', styles['SectionHead']),
    Paragraph(artist['statement'], styles['BodySmall']),
    Paragraph('Public profile', styles['SectionHead']),
    table([
        ['Name', artist['name']],
        ['Base', artist['location']],
        ['Discipline', artist['discipline']],
        ['Current status', artist['status']],
        ['Email', artist['email']],
        ['Instagram', artist['instagram']],
    ], [38 * mm, USABLE_W - 38 * mm], header=False),
    Spacer(1, 10),
    Paragraph('Current public series', styles['SectionHead']),
    bullet_list([
        'Thresholds - entry pressure, walls of light, wet pavement, railings, and doorways.',
        'Witness Horizon - open ground, water, trees, and distant figures held near the edge of recognition.',
        'Weathered Nearness - rain, transit, weather, and the unstable promise of shelter.',
        'Winter Passage - snow, reduction, and the changed shape of nearness when another body enters the frame.',
        'Stage Presence - a smaller counter-sequence built around lit floorboards, exposure, and performance space.',
    ]),
    Spacer(1, 8),
    Paragraph('Contact and requests', styles['SectionHead']),
    Paragraph('Available for editions, exhibitions, editorial licensing, and selected collaborations. High-resolution files, captions, and extended background notes can be prepared on request for publications or curatorial review.', styles['BodySmall']),
    Spacer(1, 8),
]
press_story += title_block(
    'STILLMRK / SHORT BIO',
    'Short biography',
    'A text block that can be copied into festival notes, editorial captions, or exhibition materials.',
)
press_story += [
    Paragraph(f"{artist['name']} is a monochrome photographer based in {artist['location']}. STILLMRK unfolds as a paced sequence rather than a loose feed of images. Roads, shorelines, reflections, winter fields, trees, and weather recur across the work because they keep changing the visible weight of distance. The photographs are made across different places and years, but they are held together by one recurring condition: how a body remains present inside separation, exposure, and brief forms of human nearness.", styles['BodySmall']),
    Paragraph('Editorial use', styles['SectionHead']),
    Paragraph('This press kit is a live placeholder with real public-facing content. Replace it later with finalized publication credits, exhibition history, selected images, and any approved portrait or studio details once those materials are ready.', styles['BodySmall']),
    Paragraph('Selected image notes', styles['SectionHead']),
    table([
        ['Work', 'Editorial note'],
        ['Threshold Walker', work_lookup['threshold-walker']['caption']],
        ['Mirror Shore', work_lookup['mirror-shore']['caption']],
        ['Framed Silence', work_lookup['framed-silence']['caption']],
        ['Storm Mirror', work_lookup['storm-mirror']['caption']],
    ], [40 * mm, USABLE_W - 40 * mm]),
]

cv_story = []
cv_story += title_block(
    'STILLMRK / STUDIO CV',
    'Studio CV',
    'A concise public practice profile for curators, editors, commissioners, and collaborators.',
)
cv_story += [
    Paragraph('Profile', styles['SectionHead']),
    Paragraph(f"{artist['name']} works in monochrome fine art photography, building image sequences that move through thresholds, witness, reflection, weather, and winter passage. The practice prioritizes slow editing, coherence of tone, and series-based storytelling over volume.", styles['BodySmall']),
    Paragraph('Working method', styles['SectionHead']),
    table([
        ['Approach', 'Series-led editing rather than chronological dumping.'],
        ['Visual language', 'Monochrome, reduced palette, image-first pacing, restrained text.'],
        ['Current public body', f"{len(works)} works across {len(series)} public series."],
        ['Core themes', 'Distance, witness, solitude, reflection, weather, and nearness.'],
        ['Collaboration scope', 'Editions, exhibitions, editorial licensing, and selected commissions.'],
        ['Base', artist['location']],
    ], [42 * mm, USABLE_W - 42 * mm], header=False),
    Spacer(1, 10),
    Paragraph('Series profile', styles['SectionHead']),
    bullet_list([
        'Thresholds: architectural edges and the first pressure point of the sequence.',
        'Witness Horizon: open terrain, water, tree mass, and distance made visible.',
        'Weathered Nearness: rain, transit, and temporary shelter as emotional structures.',
        'Winter Passage: snow, reduction, and the altered terms of companionship.',
        'Stage Presence: lit interiors and performance space as a counterpoint to the landscape work.',
    ]),
    Spacer(1, 8),
    Paragraph('Professional note', styles['SectionHead']),
    Paragraph('This CV is intentionally concise and factual. It supports first contact without inventing credentials or padding the record. Detailed publications, exhibitions, awards, and collection notes should be added only when they are accurate and final.', styles['BodySmall']),
    PageBreak(),
]
cv_story += title_block(
    'STILLMRK / CONTACT',
    'Inquiry details',
    'For public use, contact routes are kept simple and direct.',
)
cv_story += [
    table([
        ['Email', artist['email']],
        ['Instagram', artist['instagram']],
        ['Availability', artist['status']],
        ['Website', site['display_url']],
    ], [38 * mm, USABLE_W - 38 * mm], header=False),
    Spacer(1, 10),
    Paragraph('Replacement note', styles['SectionHead']),
    Paragraph('You can later replace this document with a fully detailed CV. At that stage, add dated rows for exhibitions, publications, talks, residencies, commissions, collections, and education only if the entries are accurate and final.', styles['BodySmall']),
]

ex_story = []
ex_story += title_block(
    'STILLMRK / EXHIBITION DOSSIER',
    'Exhibition list',
    'A real public document replacing the placeholder stub. The detailed formal list can be expanded later when confirmed records are ready.',
)
ex_story += [
    Paragraph('Current status', styles['SectionHead']),
    Paragraph('A finalized exhibition history is not yet published in this public dossier. That is deliberate: the public document should remain truthful rather than padded with provisional or informal entries.', styles['BodySmall']),
    Paragraph('What this document currently provides', styles['SectionHead']),
    table([
        ['Public purpose', 'To give curators and organizers a usable document instead of a blank placeholder file.'],
        ['Current state', 'Detailed exhibition chronology in preparation.'],
        ['Private follow-up', 'A more detailed list can be shared directly once records are consolidated.'],
        ['Presentation formats', 'Wall-based sequence, projected edit, editorial pairing, or small-room installation.'],
    ], [42 * mm, USABLE_W - 42 * mm], header=False),
    Spacer(1, 10),
    Paragraph('Curatorial context', styles['SectionHead']),
    Paragraph('STILLMRK is sequence-driven work. Images are built to operate in relation: threshold, open ground, reflection, weather, winter, and the occasional interruption of solitude by another presence. Any exhibition or screening should preserve that pacing rather than treating the body of work as an interchangeable image bank.', styles['BodySmall']),
    Paragraph('Contact', styles['SectionHead']),
    Paragraph(f"For exhibition proposals, installation notes, or a fuller dossier, contact {artist['email']} or reach out via Instagram: {artist['instagram']}", styles['BodySmall']),
]

ASSETS.mkdir(parents=True, exist_ok=True)
build_doc(ASSETS / 'stillmark-press-kit.pdf', press_story, 'STILLMRK Press Kit')
build_doc(ASSETS / 'stillmark-studio-cv.pdf', cv_story, 'STILLMRK Studio CV')
build_doc(ASSETS / 'stillmark-exhibition-list.pdf', ex_story, 'STILLMRK Exhibition List')
print('PDF documents generated in assets/documents/.')
