"""Replace the opening Chapter 3 pages in ver31 with a capture-to-ingestion revision."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/duveen/Downloads/ver31.pdf')
WORK = ROOT / 'tmp' / 'pdfs'
INSERT = WORK / 'chapter3_replacement.pdf'
OUTPUT = ROOT / 'output' / 'pdf' / 'Signora_Report_Chapter_3_Revised.pdf'

PAGE_W, PAGE_H = A4
LEFT, RIGHT = 2.7 * cm, 2.2 * cm
ACCENT = colors.HexColor('#1F4E79')
INK = colors.HexColor('#17212B')
MUTED = colors.HexColor('#5B6874')
PALE = colors.HexColor('#EAF2F8')
GREEN = colors.HexColor('#EAF5EE')
AMBER = colors.HexColor('#FFF5E6')


def para(text, style):
    return Paragraph(text, style)


def box(c, x, y, w, h, title, lines, fill=colors.white, title_fill=ACCENT):
    c.setStrokeColor(ACCENT)
    c.setLineWidth(0.8)
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, 7, fill=1, stroke=1)
    c.setFillColor(title_fill)
    c.roundRect(x, y + h - 20, w, 20, 7, fill=1, stroke=0)
    c.rect(x, y + h - 20, w, 13, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 8.3)
    c.drawCentredString(x + w / 2, y + h - 13.5, title)
    c.setFillColor(INK)
    c.setFont('Helvetica', 7.3)
    start = y + h - 34
    for i, line in enumerate(lines):
        c.drawCentredString(x + w / 2, start - i * 10, line)


def arrow(c, x1, y1, x2, y2, label=None, dashed=False):
    c.saveState()
    c.setStrokeColor(ACCENT)
    c.setFillColor(ACCENT)
    c.setLineWidth(1.3)
    if dashed:
        c.setDash(3, 2)
    c.line(x1, y1, x2, y2)
    import math
    angle = math.atan2(y2-y1, x2-x1)
    size = 6
    c.line(x2, y2, x2-size*math.cos(angle-0.45), y2-size*math.sin(angle-0.45))
    c.line(x2, y2, x2-size*math.cos(angle+0.45), y2-size*math.sin(angle+0.45))
    c.restoreState()
    if label:
        c.setFillColor(MUTED)
        c.setFont('Helvetica', 6.5)
        c.drawCentredString((x1+x2)/2, (y1+y2)/2 + 4, label)


def header_footer(c, doc):
    page = doc.page
    printed = 10 + page
    c.saveState()
    c.setStrokeColor(colors.HexColor('#C9D5E0'))
    c.line(LEFT, PAGE_H - 1.65 * cm, PAGE_W - RIGHT, PAGE_H - 1.65 * cm)
    c.setFillColor(MUTED)
    c.setFont('Helvetica', 7.2)
    c.drawString(LEFT, PAGE_H - 1.35 * cm, 'CHAPTER 3  |  PROPOSED METHODOLOGY')
    c.drawRightString(PAGE_W - RIGHT, PAGE_H - 1.35 * cm, 'Signora / SignSure')
    c.line(LEFT, 1.42 * cm, PAGE_W - RIGHT, 1.42 * cm)
    c.setFillColor(INK)
    c.setFont('Helvetica', 9)
    c.drawCentredString(PAGE_W / 2, 0.92 * cm, str(printed))
    c.restoreState()


class DiagramPage:
    def __init__(self, kind): self.kind = kind
    def wrap(self, aw, ah): return aw, ah
    def drawOn(self, canvas, x, y, _sW=0):
        # Coordinates are deliberately absolute so diagrams remain consistent with A4 layout.
        if self.kind == 'architecture': architecture_diagram(canvas)
        elif self.kind == 'acquisition': acquisition_diagram(canvas)
        else: ingestion_diagram(canvas)


def architecture_diagram(c):
    c.saveState()
    c.setFillColor(INK); c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(PAGE_W/2, PAGE_H-2.55*cm, 'System Architecture')
    c.setFillColor(MUTED); c.setFont('Helvetica', 8.5)
    c.drawCentredString(PAGE_W/2, PAGE_H-2.95*cm, 'Capture, prepare, store, select and render a traceable ISL motion clip')
    x1, x2, x3 = LEFT, LEFT+5.45*cm, LEFT+10.9*cm
    w, h = 4.15*cm, 1.35*cm
    ys = [PAGE_H-5.2*cm, PAGE_H-7.45*cm, PAGE_H-9.7*cm, PAGE_H-11.95*cm]
    box(c,x1,ys[0],w,h,'CAPTURE INPUTS',['Smartsuit body pose','Smartgloves finger motion','Headcam face / head tracking'],PALE)
    box(c,x1,ys[1],w,h,'ROKOKO STUDIO',['Pair and time-align devices','Record named performance','Review the take'],PALE)
    box(c,x1,ys[2],w,h,'NATIVE TAKE + EXPORT',['Native recording retained','Combined FBX exported','Mixamo skeleton, 60 fps'],PALE)
    box(c,x1,ys[3],w,h,'SOURCE ARCHIVE',['One FBX per gloss / take','Session notes and reference video','Immutable source for review'],PALE)
    for a,b in zip(ys,ys[1:]): arrow(c,x1+w/2,a,x1+w/2,b+h)
    box(c,x2,ys[0],w,h,'CAPTURE PAGE',['Preview FBX and channels','Enter sign-start / sign-end','Upload a reviewed capture'],GREEN)
    box(c,x2,ys[1],w,h,'INGESTION SERVICE',['Validate + parse FBX','Snap phase boundaries','Create normalized landmarks'],GREEN)
    box(c,x2,ys[2],w,h,'MOTION LIBRARY',['SQLite: identity + QC','Motion JSON: frame data','Source-to-clip traceability'],GREEN)
    box(c,x2,ys[3],w,h,'COMPOSITION',['Choose canonical take','Use Start / Sign / End','Check transitions'],GREEN)
    for a,b in zip(ys,ys[1:]): arrow(c,x2+w/2,a,x2+w/2,b+h)
    box(c,x3,ys[0],w,h,'REACT PLAYER',['Request prepared frames','Apply timing + calibration','Stream canonical frame JSON'],AMBER)
    box(c,x3,ys[1],w,h,'UNITY WEBGL RUNTIME',['Validate and filter frames','Retarget body, hands, head','Apply facial blendshapes'],AMBER)
    box(c,x3,ys[2],w,h,'SIGNORA AVATAR',['Rigged 3D avatar','Rendered signing movement','Visible viewer output'],AMBER)
    box(c,x3,ys[3],w,h,'OPTIONAL VALIDATION',['Reference video + source FBX','Landmark comparison','Evidence kept separate'],AMBER)
    for a,b in zip(ys,ys[1:]): arrow(c,x3+w/2,a,x3+w/2,b+h)
    arrow(c,x1+w,ys[2]+h/2,x2,ys[2]+h/2,'combined FBX')
    arrow(c,x2+w,ys[3]+h/2,x3,ys[0]+h/2,'prepared motion')
    c.setFillColor(MUTED); c.setFont('Helvetica-Oblique',7.3)
    c.drawCentredString(PAGE_W/2, 2.25*cm, 'Figure 3.1: End-to-end architecture of the Signora motion-capture system.')
    c.restoreState()


def acquisition_diagram(c):
    c.saveState()
    c.setFillColor(INK); c.setFont('Helvetica-Bold', 13)
    c.drawCentredString(PAGE_W/2, PAGE_H-2.55*cm, 'Capture Acquisition and Signal Flow')
    c.setFillColor(MUTED); c.setFont('Helvetica', 8.3)
    c.drawCentredString(PAGE_W/2, PAGE_H-2.92*cm, 'Each device contributes a distinct input; Rokoko Studio combines the recorded channels into one take.')
    xL=LEFT; xM=LEFT+6.0*cm; xR=LEFT+12.0*cm; w=4.25*cm; h=1.45*cm
    rows=[PAGE_H-5.1*cm, PAGE_H-7.4*cm, PAGE_H-9.7*cm, PAGE_H-12.0*cm]
    data=[
      ('SMARTSUIT PRO II',['Inertial body sensors','Input: torso / limb motion','Output: body skeletal stream']),
      ('SMARTGLOVES',['Finger sensors, left + right','Input: finger articulation','Output: hand / finger stream']),
      ('HEADCAM + PHONE CAMERA',['Phone camera observes face','Input: face / head appearance','Output: head pose + facial stream']),
      ('COIL PRO / SESSION SETUP',['Positioning / session accessory','Input: setup information','Output: session support data']),
    ]
    for y,(title,lines) in zip(rows,data):
        box(c,xL,y,w,h,title,lines,PALE)
        arrow(c,xL+w,y+h/2,xM,y+h/2)
    box(c,xM,rows[1]-0.25*cm,w,5.65*cm,'ROKOKO STUDIO',['Pairs the capture devices','Uses one recording session','Receives body, hand, head and','available facial channels','Creates a named native take','Provides take review / trimming'],GREEN)
    for y in rows: arrow(c,xM+w,y+h/2,xR,y+h/2)
    box(c,xR,rows[1]-0.25*cm,w,5.65*cm,'RECORDING OUTPUT',['Native Rokoko take','contains synchronized channels','        ↓','Export action','        ↓','Combined FBX file','for one gloss / take'],AMBER)
    c.setFillColor(MUTED);c.setFont('Helvetica',7.0)
    c.drawCentredString(PAGE_W/2, 2.28*cm, 'Arrows show data direction. The phone camera supplies visual face input to the Headcam workflow; it does not create body or glove data.')
    c.setFont('Helvetica-Oblique',7.3)
    c.drawCentredString(PAGE_W/2, 1.88*cm, 'Figure 3.2: Circuit-style view of the data acquisition setup and outputs.')
    c.restoreState()


def ingestion_diagram(c):
    c.saveState()
    c.setFillColor(INK); c.setFont('Helvetica-Bold', 13)
    c.drawCentredString(PAGE_W/2, PAGE_H-2.55*cm, 'FBX Ingestion and Storage Flow')
    y=PAGE_H-5.2*cm; x=LEFT; w=3.15*cm; h=1.65*cm; gap=0.38*cm
    items=[
      ('1. SELECT SOURCE',['Combined FBX','one gloss / take']),
      ('2. CAPTURE PAGE',['Preview channels','enter phase bounds']),
      ('3. VALIDATE',['FBX + skeleton','boundaries + size']),
      ('4. NORMALIZE',['Sample motion','canonical landmarks']),
      ('5. PERSIST',['FBX + JSON + SQLite','QC and provenance']),
    ]
    for i,(title,lines) in enumerate(items):
        xi=x+i*(w+gap)
        box(c,xi,y,w,h,title,lines, [PALE,GREEN,AMBER,PALE,GREEN][i])
        if i < len(items)-1: arrow(c,xi+w,y+h/2,xi+w+gap,y+h/2)
    # database split
    yy=PAGE_H-9.0*cm
    box(c,LEFT+1.0*cm,yy,5.1*cm,1.7*cm,'IMMUTABLE SOURCE STORE',['backend/data/uploads/<job-id>/<take>.fbx','Original upload retained for audit and re-processing'],PALE)
    box(c,LEFT+8.25*cm,yy,5.1*cm,1.7*cm,'MOTION ARTIFACT STORE',['backend/data/clips/<content-hash>.motion.json','Timestamped body, hand and facial landmarks'],GREEN)
    box(c,LEFT+4.6*cm,yy-3.0*cm,5.1*cm,1.7*cm,'SQLITE LIBRARY INDEX',['Gloss, take, duration, FPS, source path, clip path, phase QC, content hash and status'],AMBER)
    arrow(c,LEFT+7.75*cm,y,LEFT+3.55*cm,yy+1.7*cm)
    arrow(c,LEFT+7.75*cm,y,LEFT+10.8*cm,yy+1.7*cm)
    arrow(c,LEFT+3.55*cm,yy,LEFT+7.15*cm,yy-1.3*cm)
    arrow(c,LEFT+10.8*cm,yy,LEFT+7.15*cm,yy-1.3*cm)
    c.setFillColor(MUTED);c.setFont('Helvetica',7.1)
    c.drawCentredString(PAGE_W/2,2.25*cm,'A failed validation stays a documented ingest job; it is not registered as a playable library clip.')
    c.setFont('Helvetica-Oblique',7.3);c.drawCentredString(PAGE_W/2,1.85*cm,'Figure 3.3: From exported FBX to a traceable Signora motion-library item.')
    c.restoreState()


def build_insert():
    WORK.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle('body', parent=styles['BodyText'], fontName='Times-Roman', fontSize=10.15, leading=15.2, alignment=TA_JUSTIFY, textColor=INK, spaceAfter=7)
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], fontName='Times-Bold', fontSize=14, leading=17, textColor=INK, spaceBefore=4, spaceAfter=10)
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], fontName='Times-Bold', fontSize=11.5, leading=14, textColor=INK, spaceBefore=7, spaceAfter=6)
    caption = ParagraphStyle('cap', parent=body, fontName='Times-Italic', fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=MUTED, spaceBefore=4, spaceAfter=7)
    note = ParagraphStyle('note', parent=body, fontName='Helvetica', fontSize=8.3, leading=11.6, backColor=colors.HexColor('#F3F6F8'), borderColor=colors.HexColor('#CFD9E1'), borderWidth=.5, borderPadding=7, spaceBefore=6, spaceAfter=8)
    doc = SimpleDocTemplate(str(INSERT), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=2.15*cm, bottomMargin=1.75*cm)
    s=[]
    # 11
    s += [DiagramPage('architecture'), PageBreak()]
    # 12
    s += [para('3.1 Architecture Design',h1),
    para('The Signora system is organised as a traceable path from a recorded ISL performance to avatar playback. The design separates capture, preparation and presentation so that the motion used by the avatar can always be related to its source take. Figure 3.1 presents that path. The first column concerns the physical capture session; the second creates a reusable library item; and the third delivers the prepared motion to the viewer.',body),
    para('At capture time, the Smartsuit records body posture and limb movement, the Smartgloves record detailed hand articulation, and the Headcam workflow uses a phone camera to obtain head and facial information. Rokoko Studio records the paired inputs as one named take. The native recording is retained for review, and the selected take is exported as a combined FBX file. An FBX therefore enters SignSure as the source record for one gloss and take, rather than as a motion file created by the web application.',body),
    para('The Capture page is the gateway to the library. It previews the exported FBX, gathers the reviewed start-of-sign and end-of-sign timestamps, and sends the file to the backend. The ingestion service validates the supported skeleton and motion channels, snaps the phase boundaries to actual animation frames, and transforms the source into a standard landmark representation. It writes a content-addressed motion JSON artifact for frame playback while recording searchable information and quality-control status in SQLite. The original FBX remains separately stored, so the prepared clip can be audited or regenerated later.',body),
    para('At playback time, the composition layer selects a canonical take and applies its authored <i>Start</i>, <i>Sign</i> and <i>End</i> phases. It sends only the required prepared frames to the React player. The player schedules those frames and forwards canonical frame JSON to the Unity WebGL runtime. Unity validates and filters the stream before retargeting body, hands, head and facial blendshapes to the Signora avatar. Thus, the viewer sees a rendered avatar, while the underlying evidence remains a specific capture and stored motion artifact.',body),
    para('<b>Scope of this implementation.</b> The architecture also keeps an optional validation route separate from library playback. A reference video and the source FBX may be analysed together, but that comparison does not alter the recorded library clip. This distinction prevents later research analysis from being confused with the asset-creation pipeline described in this chapter.',note),
    para('The separation is useful in practice. New signs can be captured and ingested without changing Unity, and changes to the avatar runtime do not overwrite the capture source. It also makes the data hand-offs clear: devices feed Rokoko Studio; Rokoko Studio yields an exported FBX; ingestion yields normalized JSON and metadata; and the application finally streams that normalized motion to Unity.',body), PageBreak()]
    # 13 - acquisition diagram
    s += [DiagramPage('acquisition'), PageBreak()]
    # 14
    s += [para('3.2 Data Acquisition',h1),
    para('Data acquisition records one planned ISL performance as a named capture session. The purpose is to retain complementary motion layers: gross body movement, detailed finger articulation, head orientation and available facial expression. These layers are not interchangeable. Body movement alone cannot represent a handshape accurately, and hand data alone does not preserve the signer’s posture or non-manual cues. Figure 3.2 identifies the input and output of every component in the acquisition setup.',body),
    para('The <b>Rokoko Smartsuit Pro II</b> is worn by the signer and supplies body motion. Its inertial sensors capture the changing orientation and movement of the torso, shoulders, arms and other body segments. This stream is the basis for the avatar’s larger skeletal motion. The <b>Smartgloves</b> are worn on both hands. They supply finger articulation and hand pose, allowing the capture to retain fine movements that are essential when a sign differs by finger configuration, palm direction or relative hand position.',body),
    para('The <b>Headcam workflow</b> uses the paired phone camera to observe the signer’s face. The camera image is the input for face and head tracking; its resulting head pose and available facial-animation channels are supplied to the capture session. In other words, the phone camera contributes visual facial input to the Headcam workflow, not a duplicate body or hand signal. The <b>Coil Pro/session setup</b> is retained as a setup-related component of the capture arrangement. Its contribution is recorded with the session rather than treated as a separate sign source.',body),
    para('All devices are paired and checked before recording. The signer is positioned so the suit is secure, both gloves follow the fingers, and the phone camera has an unobstructed view of the face. The team records one sign at a time and names each take from the gloss and take number, for example <i>HELLO_02</i>. If a capture will later be compared with an independent reference, that video is retained as a separate item with its own provenance; it is not merged into the FBX capture.',body),
    para('During the take, Rokoko Studio is the collection point. It receives the available device streams, records them in one session and allows the recording to be reviewed. The immediate output is a native Rokoko take, not yet the asset uploaded to SignSure. Keeping this difference explicit avoids confusing acquisition with web ingestion: hardware produces a recorded performance first, while the website subsequently receives an exported file.',body), PageBreak()]
    # 15
    s += [para('3.2.1 From Recorded Take to Combined FBX',h2),
    para('After review, the selected native take is exported from Rokoko Studio as a <b>combined FBX</b>. This export preserves the animated skeleton over time and packages the available body, Smartglove and facial-animation channels in a format that the backend can parse. The project uses the Mixamo skeleton export profile at 60 frames per second. The export is configured with clip time beginning at zero; reference pose and extracted root motion are not included. A face channel can be used only if facial tracking was actually recorded during acquisition.',body),
    para('The team stores one exported FBX file for each sign and take. Its filename provides the library identity: <i>hello.fbx</i> and <i>hello_01.fbx</i> represent take 1 of HELLO, while <i>hello_02.fbx</i> represents take 2. This naming convention connects the recording session to the later library record without relying on a manually retyped gloss. The source FBX is retained after successful upload in an isolated upload folder, so a prepared motion artifact can be traced back to the original export.',body),
    para('The operator also reviews two timestamps: where the meaning-bearing sign begins and where it ends. They divide the performance into <i>Start</i>, <i>Sign</i> and <i>End</i> phases. The Start phase prepares the movement, Sign is the meaningful portion, and End completes it. The boundaries do not rewrite the recording; they describe how the library should use it. A single sign can play all three phases, whereas a sign within a sequence can use only the necessary segment and avoid repeated preparation or finishing motion.',body),
    para('<b>Acquisition output.</b> The completed acquisition step therefore produces four related records: (1) a named native take in Rokoko Studio, (2) a combined FBX export, (3) reviewed phase timestamps, and (4) optional session notes or an independent reference video. The next section explains how SignSure accepts these items and creates the two storage forms needed by the application.',note),
    para('This hand-off is intentionally controlled. Copying an FBX file into a storage directory is not an import. A file becomes a library item only when it has passed the Capture-page validation and the ingestion service has created its normalized motion representation and quality-control record.',body), PageBreak()]
    # 16 ingestion diagram
    s += [DiagramPage('ingestion'), PageBreak()]
    # 17
    s += [para('3.3 Data Ingestion',h1),
    para('Data ingestion converts an exported FBX from a reviewed capture into a reusable SignSure library item. The process begins on the Capture page, where a project member selects the combined FBX, previews its available channels and enters the start-of-sign and end-of-sign timestamps. The page does not treat an upload as immediately playable. It first sends the file and phase information to a capture endpoint, which creates an ingestion job and returns its status for review.',body),
    para('The upload service accepts only a non-empty combined <i>.fbx</i> file within the configured 100 MB size limit. Before accepting it, the backend parses the FBX and verifies that the source is compatible with the supported capture profile. It checks the skeleton and animation data, confirms that the requested phase boundaries are present or supplied, and snaps authored boundaries to the real animation frames. An invalid file, unsuitable boundaries or an empty upload are rejected with a specific error rather than silently appearing in the motion library.',body),
    para('For an accepted upload, the original FBX is written to an isolated source folder under <i>backend/data/uploads/</i>. The system then creates a background ingestion job. That job reads the FBX at its source timing, constructs the project’s landmark representation for body and both hands, retains available ARKit facial blendshapes, identifies unusable frames and prepares the motion for playback. It also records duration, source frame rate, source and output frame counts, dominant-hand travel, facial-channel coverage, phase information and warnings.',body),
    para('The normalized frame data is serialized as a content-addressed <i>.motion.json</i> artifact under <i>backend/data/clips/</i>. Each artifact carries timestamped motion values rather than a rendered video. Separately, SQLite stores the lightweight library index: gloss, take number, source path, artifact path, content hash, duration, frames per second, frame count and quality-control data. This two-part design lets the application find a sign efficiently while keeping the detailed motion stream available for composition and Unity playback.',body),
    para('If processing fails, the job records the failure state and error; no playable SignClip is registered. When it succeeds, the library can nominate one take as canonical for a gloss without discarding the source evidence or other takes. Consequently, later phase edits can regenerate the derived artifact while retaining the original capture.',body), PageBreak()]
    # 18
    s += [para('3.3.1 Operational Ingestion Sequence',h2),
    para('Figure 3.3 summarises the ingestion path. The essential principle is that the FBX is the immutable source record, while motion JSON is the standard data exchange format used by the SignSure application. The source is preserved for audit and re-processing; the JSON representation is optimized for selecting, composing and streaming frames.',body),
    Table([
      [para('<b>Stage</b>',body),para('<b>Input</b>',body),para('<b>Output / decision</b>',body)],
      [para('1. Capture preview',body),para('Combined FBX selected by operator',body),para('Channel preview and filename-derived gloss / take',body)],
      [para('2. Phase authoring',body),para('Start-of-sign and end-of-sign timestamps',body),para('Frame-snapped Start, Sign and End ranges',body)],
      [para('3. Validation',body),para('FBX bytes, skeleton, channels and boundaries',body),para('Accepted source or documented rejection',body)],
      [para('4. Background ingest',body),para('Accepted source and phase input',body),para('Normalized body, hand and available face landmarks; QC summary',body)],
      [para('5. Registration',body),para('Motion JSON plus provenance',body),para('SQLite SignClip record; eligible for canonical selection',body)],
    ], colWidths=[3.2*cm,6.0*cm,6.25*cm], style=TableStyle([
      ('BACKGROUND',(0,0),(-1,0),ACCENT),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#BAC8D4')),('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,1),(-1,-1),colors.white),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F6F9FB')]),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
    ])), Spacer(1,9),
    para('<b>Implementation boundary.</b> This chapter implements the capture, export and ingestion path only. It establishes the source data and motion-library artifacts on which later landmarking, composition, avatar playback and validation work can rely. It does not claim that export alone validates linguistic correctness or avatar fidelity; those questions require separate review and evaluation.',note),
    para('The next methodology section can therefore begin from a precise state: a capture has a known source FBX, known phase boundaries, a quality-controlled normalized artifact and a searchable library identity. That state is the correct input for downstream landmark-based motion processing rather than an unstructured file upload.',body), PageBreak()]
    # 19, 20 bridge preserve upcoming sections but clarify implementation scope
    s += [para('3.4 Handoff to Motion Processing',h1),
    para('Once ingestion has completed, the system has a traceable normalized motion artifact ready for downstream processing. The next stages operate on that artifact rather than directly on the recording equipment. Body, hand and available facial landmarks remain linked to their timestamps, the source FBX and the reviewed sign-phase boundaries. This continuity permits later operations to select frames without losing the provenance established during capture.',body),
    para('For a single sign, the full Start-Sign-End sequence can be prepared for playback. For a sequence, the composition stage can select an initial preparation, the meaning-bearing sign interval and a final completion while avoiding repeated neutral returns. The avatar runtime receives the resulting canonical frames and retargets them to the Signora rig. These later stages do not change the acquisition record described in Sections 3.2 and 3.3.',body),
    para('The following sections retain the broader motion-data preparation, blending, browser playback and validation methodology. They should be read as downstream consumers of the capture and ingest outputs defined above.',body), PageBreak(),
    para('3.4.1 Data Ready for Landmark-Based Processing',h2),
    para('The ingestion result contains time-ordered body landmarks, left- and right-hand landmarks and available facial blendshape information. Each item can be related to its original source file, content hash, phase configuration and quality-control report. This is the data contract used by subsequent motion preparation and by the website when it requests a library item.',body),
    para('A downstream landmarking or retargeting stage should preserve that relationship. It may derive additional features, smooth a presentation stream or create a transition artifact, but it should retain the identity of the source take and the selected phase boundaries. Doing so makes a visual issue in avatar playback investigable: the team can determine whether it began in acquisition, FBX export, ingestion, normalization or the later runtime.',body),
    para('This completes the currently implemented capture-to-ingestion portion of the system methodology.',note)]
    doc.build(s, onFirstPage=header_footer, onLaterPages=header_footer)


def merge():
    reader = PdfReader(str(SOURCE))
    replacement = PdfReader(str(INSERT))
    if len(replacement.pages) != 10:
        raise RuntimeError(f'Expected 10 replacement pages, got {len(replacement.pages)}')
    writer = PdfWriter()
    for page in reader.pages[:18]: writer.add_page(page)
    for page in replacement.pages: writer.add_page(page)
    for page in reader.pages[28:]: writer.add_page(page)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('wb') as fh: writer.write(fh)


if __name__ == '__main__':
    build_insert()
    merge()
    print(OUTPUT)
