"""Build the editable hackathon deck using standard Office Open XML only."""
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
import json
import html

ROOT = Path(__file__).resolve().parent
DEMO = 'https://guardian-dashboard-v8ev.onrender.com'
SLIDES = [
    ('Guardian', 'Voice-first scam response and recovery assistant', [
        'A voice conversation becomes an inspectable response plan, approved actions and verified outcomes.',
        'Hackathon theme: From Conversations to Autonomous Action',
        DEMO], 'Project description. Implementation: backend/app/services/incidents.py, backend/app/tools.py. Demo link is a deployed prototype, not a recording.'),
    ('Selected problem statement', 'Helping a person act safely during an impersonation scam', [
        'A caller posing as police threatens the user and demands INR 35,000. The user may have exposed banking information.',
        'The user needs calm clarification, relevant account context and a clear sequence of next steps.',
        'Guardian coordinates protective sandbox actions and optional authorized Google follow-up. Financial actions affect synthetic accounts only.'], 'Selected project framing under the supplied hackathon theme. No official problem-statement ID was supplied. Scenario: AGENTS.md, Required user journey and demo.'),
    ('The complete user journey', 'Support before, during and after the conversation', [
        'Before: sign in, retrieve account context, recent synthetic transactions and prior incidents.',
        'During: clarify caller claims, recognize suspicious activity and build a response plan.',
        'Action and confirmation: request dashboard approval, execute each permitted action and verify state.',
        'After: retain incident history, produce a report and track follow-up reminders.'], 'Sources: backend/app/tools.py, backend/app/services/incidents.py, backend/app/agent/plan.py, backend/app/agent/followups.py.'),
    ('Application architecture', 'Separate voice, policy and external services', [
        'React dashboard: microphone, Agora RTC/RTM connection, incident plan and approval controls.',
        'FastAPI backend: account sessions, tool allowlist, approval gates and per-user SQLite storage.',
        'Agora Conversational AI: speech recognition, managed language model, tool requests and speech pipeline.',
        'Adapters: Murf Falcon output, a separate synthetic bank, and per-user Google OAuth for Gmail and Calendar.'], 'Sources: frontend/src/hooks/useVoice.ts, backend/app/main.py, backend/app/services/voice.py, backend/app/adapters/. Murf runs in the Agora voice pipeline, not as a separate Guardian speech server.'),
    ('Agora Conversational AI integration', 'Real-time voice with a backend-controlled lifecycle', [
        'The authenticated backend prepares a channel, user ID and time-limited RTC/RTM token.',
        'The browser joins RTC, publishes the microphone, subscribes to remote audio and connects RTM.',
        'The backend configures the saved agent and starts its session. Status and stop endpoints track the lifecycle.',
        'Agent settings use Deepgram Nova-3 ASR and Agora-managed OpenAI gpt-4o-mini. The public HTTPS tool URL reaches Guardian.'], 'Sources: backend/app/services/voice.py (prepare_voice_session, start_voice_session, voice_session_status, stop_voice_session), frontend/src/hooks/useVoice.ts, backend/app/voice_config.py. Agora SDK pin: backend/requirements.txt. Session parameters: 60-second idle timeout, 3,600-second maximum duration. No measured latency claim.'),
    ('Agora tool calling', 'Typed proposals meet application policy', [
        'Saved-agent function definitions map camelCase Agora tool names to eight registered Guardian tools.',
        'Agora sends authenticated HTTPS POST requests to /api/agent-tools/{name}. Registered accounts have separate tool credentials.',
        'Pydantic validates arguments. The authenticated account selects the permitted storage scope.',
        'Voice confirmation cannot grant approval. Sensitive tools return the pending action until the dashboard authorizes execution.'], 'Sources: backend/app/tools.py (agora_tool_definitions, CONTRACTS, execute), backend/app/api/tools.py, backend/app/database.py (tool_token). Server timeout in tool definitions: 10,000 ms. Voice-triggered end-to-end tool verification remains pending.'),
    ('Murf AI Falcon TTS integration', 'Guardian speech uses the Agora Murf pipeline', [
        'The saved agent uses MurfTTS with model FALCON and 24 kHz output.',
        'Murf streaming endpoint: wss://global.api.murf.ai/v1/speech/stream-input',
        'The backend holds MURF_API_KEY in an Agora project secret reference. The browser receives the remote audio track.',
        'Default speech is English with Natalie, locale en-US. A profile fixes the voice and locale when the session starts.'], 'Source: backend/app/voice_config.py (build_guardian_agent). Fields: key=secret_ref(secret_name, "murf"), model="FALCON", sample_rate=24000, rate=0, pitch=0. backend/app/services/voice.py updates the secret and saved agent. Credentials never belong in slides or frontend environment variables. Previously user-confirmed speech is evidence, not a new live speech test.'),
    ('Voice and language selection', 'A shorter picker with Indian language coverage', [
        'Local update: six English choices across US, UK and Indian accents.',
        'All native catalog voices remain selectable for Bangla, Gujarati, Hindi, Kannada, Malayalam, Marathi, Punjabi and Tamil.',
        'Other languages show one male and one female voice wherever both are available. Some catalog languages offer only one gender.',
        'Auto-detect recognizes multilingual input while retaining the chosen reply voice. The latest picker is local and awaits deployment.'], 'Sources: backend/app/voice_config.py (dropdown_profiles), backend/app/murf_voices.json. Catalog snapshot: 2026-11-21. Output locale support does not prove ASR coverage. All original profiles remain resolvable for saved sessions.'),
    ('Registered Guardian tools', 'Eight narrow contracts support the workflow', [
        'Context: get_user_context, get_recent_transactions, get_incident_history.',
        'Planning: create_incident persists the situation, assessment, dependency-aware plan and approval requests.',
        'Actions: freeze_demo_card, notify_trusted_contact, schedule_followup expose approved execution outcomes.',
        'Outcome: generate_report produces a downloadable incident summary. Each invocation records audit and tool-log events.'], 'Sources: backend/app/tools.py, backend/app/api/tools.py. Tools do not expose arbitrary SQL, shell or unrestricted HTTP access. freeze_demo_card/notify_trusted_contact read approval and outcome state. The authenticated approval endpoint executes the side effect.'),
    ('Agentic workflow and actions', 'A multi-step response to the INR 35,000 scenario', [
        '1. Retrieve user context and transactions. Clarify whether the user recognizes the flagged synthetic payment.',
        '2. Create a persistent incident and explain the protective plan. Ask for approval in the dashboard.',
        '3. Approve a sandbox card freeze. Guardian calls the separate bank and reads account state back.',
        '4. With separate approval, send a Google-authorized contact email and create the follow-up series. Read the results and generate a report.'], 'Sources: backend/app/tools.py, backend/app/services/incidents.py, backend/app/services/external.py. At least two coordinated API calls: POST mock-bank /card/freeze then GET /account to verify card_frozen. Gmail and Calendar are real external actions only in Google mode after account connection and approval. They remain pending live acceptance.'),
    ('Approval, verification and recovery', 'Success requires evidence from the resulting state', [
        'Approvals name the action and expire after 20 minutes. Authenticated sessions and CSRF checks protect decisions.',
        'Sandbox freeze: an idempotency key prevents replay, then a bank snapshot verifies the card state.',
        'Gmail: read-back checks SENT status. Calendar: stable event IDs and read-back verify the approved time.',
        'Partial calendar failures preserve verified events. Ambiguous failures stop automatic resend and remain visible.'], 'Sources: backend/app/services/incidents.py (approve_action), backend/app/services/external.py, backend/app/adapters/bank.py, backend/app/adapters/google.py. Gmail SENT status proves acceptance into the sent mailbox, not recipient delivery. No automatic safe replay of an ambiguous external send.'),
    ('Working prototype and demo', 'A repeatable walkthrough for judges', [
        DEMO,
        'Create an account or sign in. Connect Google and save a trusted-contact email for the external-action demonstration.',
        'Start voice and say: A caller claiming to be police demanded INR 35,000. Please review my demo transactions and help me plan the next steps.',
        'Inspect approvals, authorize intended actions, verify the frozen synthetic card and external outcomes, then download the report.'], 'Demo: '+DEMO+'\nAPI health: https://guardian-api-j55w.onrender.com/health\nBank health: https://guardian-mock-bank.onrender.com/health\nRunbook: docs/demo-runbook.md. Use synthetic information and your own authorized Google account. Free Render services can take time to wake.'),
    ('Evidence and remaining live checks', 'Implemented behavior and verified results', [
        'Previously verified on Render: account login, user isolation, bank tools, approved sandbox freeze, duplicate prevention, report generation and logout.',
        'The user previously confirmed a spoken Agora/Murf conversation. The updated Google authorization redirect uses the deployment client.',
        'Still pending: a fresh voice-to-tools demonstration with real Gmail and Calendar outcomes, verified by the user.',
        'Local changes awaiting deployment: registration consent/profile privacy and the curated voice picker. Free Render SQLite storage remains temporary.'], 'Evidence: deployment checks performed in this session against commit 34d2d39834d0a119bc631e73c3f62fac54abc48c. Do not describe unit tests as live provider tests. The local working tree contains later changes. Actual audio, Google consent and external outcomes require explicit live verification.'),
]

NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
def rels(items):
    return '<Relationships xmlns="'+REL+'">'+''.join(f'<Relationship Id="rId{i}" Type="{R}/{kind}" Target="{target}"/>' for i,kind,target in items)+'</Relationships>'
def shape(i, x, y, w, h, text, size, color, bold=False):
    paragraphs = ''.join(f'<a:p><a:pPr/><a:r><a:rPr lang="en-US" sz="{size*100}" b="{int(bold)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Aptos"/></a:rPr><a:t>{escape(line)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size*100}"/></a:p>' for line in text.split('\n'))
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Text {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{int(x*914400)}" y="{int(y*914400)}"/><a:ext cx="{int(w*914400)}" cy="{int(h*914400)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>'
GROUP = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
def slide_xml(shapes, dark=False):
    return f'<p:sld xmlns:p="{NS}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{"102D27" if dark else "F7F9F6"}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{GROUP}{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'

def build():
    files = {}
    def add(path, text): files[path] = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+text
    add('_rels/.rels', rels([(1,'officeDocument','ppt/presentation.xml')]))
    add('ppt/presentation.xml', f'<p:presentation xmlns:p="{NS}" xmlns:a="{A}" xmlns:r="{R}"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{256+i}" r:id="rId{i+2}"/>' for i in range(len(SLIDES)))+'</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    add('ppt/_rels/presentation.xml.rels', rels([(1,'slideMaster','slideMasters/slideMaster1.xml')]+[(i+2,'slide',f'slides/slide{i+1}.xml') for i in range(len(SLIDES))]))
    clr='<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'
    add('ppt/slideMasters/slideMaster1.xml',f'<p:sldMaster xmlns:p="{NS}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>{clr}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
    add('ppt/slideMasters/_rels/slideMaster1.xml.rels',rels([(1,'slideLayout','../slideLayouts/slideLayout1.xml'),(2,'theme','../theme/theme1.xml')]))
    add('ppt/slideLayouts/slideLayout1.xml',f'<p:sldLayout xmlns:p="{NS}" xmlns:a="{A}" xmlns:r="{R}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    add('ppt/slideLayouts/_rels/slideLayout1.xml.rels',rels([(1,'slideMaster','../slideMasters/slideMaster1.xml')]))
    colors={'dk1':'102D27','lt1':'FFFFFF','dk2':'244B3A','lt2':'F7F9F6','accent1':'326850','accent2':'87BDA2','accent3':'D2A65A','accent4':'587F99','accent5':'826B99','accent6':'B86957','hlink':'256A99','folHlink':'826B99'}
    add('ppt/theme/theme1.xml',f'<a:theme xmlns:a="{A}" name="Guardian"><a:themeElements><a:clrScheme name="Guardian">'+''.join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k,v in colors.items())+'</a:clrScheme><a:fontScheme name="Aptos"><a:majorFont><a:latin typeface="Aptos"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Guardian"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    theme = files['ppt/theme/theme1.xml']
    for tag in ('fillStyleLst', 'lnStyleLst', 'effectStyleLst', 'bgFillStyleLst'):
        start = theme.index('<a:'+tag+'>') + len('<a:'+tag+'>')
        end = theme.index('</a:'+tag+'>', start)
        theme = theme[:start] + theme[start:end] * 3 + theme[end:]
    files['ppt/theme/theme1.xml'] = theme
    preview=[]
    for n,(title,subtitle,body,notes) in enumerate(SLIDES,1):
        dark=n in (1,10,14)
        fg='FFFFFF' if dark else '102D27';muted='B8D9C8' if dark else '326850'
        shapes=shape(2,.7,.55,11.9,.95,title,44 if n==1 else 32,fg,True)
        shapes+=shape(3,.7,1.52,11.9,.6,subtitle,21,muted)
        for j,line in enumerate(body):shapes+=shape(j+4,.7,2.5+j*.94,11.8,.83,line,19,fg)
        shapes+=shape(20,.7,7.02,11.8,.25,f'Guardian   /   Hackathon submission   /   {n:02d}',10,muted)
        add(f'ppt/slides/slide{n}.xml',slide_xml(shapes,dark))
        add(f'ppt/slides/_rels/slide{n}.xml.rels',rels([(1,'slideLayout','../slideLayouts/slideLayout1.xml'),(2,'notesSlide',f'../notesSlides/notesSlide{n}.xml')]))
        add(f'ppt/notesSlides/notesSlide{n}.xml',f'<p:notes xmlns:p="{NS}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>{GROUP}'+shape(2,.5,.5,6,8,notes,12,'102D27').replace('<p:nvPr/>', '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr>')+'</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
        add(f'ppt/notesSlides/_rels/notesSlide{n}.xml.rels',rels([(1,'slide',f'../slides/slide{n}.xml')]))
        preview.append(f'<section class="slide {"dark" if dark else ""}"><h1>{html.escape(title)}</h1><h2>{html.escape(subtitle)}</h2>'+''.join(f'<p>{html.escape(t)}</p>' for t in body)+f'<footer>Guardian / {n:02d}</footer></section>')
    overrides={'ppt/presentation.xml':'presentation.main','ppt/slideMasters/slideMaster1.xml':'slideMaster','ppt/slideLayouts/slideLayout1.xml':'slideLayout','ppt/theme/theme1.xml':'theme'}
    for i in range(1,len(SLIDES)+1):
        overrides[f'ppt/slides/slide{i}.xml']='slide';overrides[f'ppt/notesSlides/notesSlide{i}.xml']='notesSlide'
    add('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.{"theme+xml" if kind=="theme" else "presentationml."+kind+"+xml"}"/>' for path,kind in overrides.items())+'</Types>')
    with ZipFile(ROOT/'Guardian-Hackathon.pptx','w',ZIP_DEFLATED) as z:
        for name,xml in files.items():z.writestr(name,xml)
    (ROOT/'slides-preview.html').write_text('<!doctype html><html><meta charset="utf-8"><title>Guardian submission slides</title><style>body{margin:0;background:#ddd;font-family:Aptos,Arial,sans-serif}.slide{width:1146px;height:592px;padding:64px 67px;background:#F7F9F6;color:#102D27;position:relative;page-break-after:always;margin-bottom:16px}.dark{background:#102D27;color:white}h1{font-size:43px;margin:0 0 22px}h2{font-size:28px;font-weight:400;color:#326850;margin-bottom:34px}.dark h2{color:#B8D9C8}p{font-size:25px;line-height:1.3;height:65px;margin:0 0 25px}footer{position:absolute;bottom:22px;font-size:14px}@media print{body{background:white}.slide{margin:0}@page{size:1280px 720px;margin:0}}</style>'+''.join(preview)+'''<script>const n=Number(new URLSearchParams(location.search).get('slide'));if(n)document.querySelectorAll('.slide').forEach((s,i)=>{if(i!==n-1)s.style.display='none'});</script></html>''',encoding='utf-8')
    (ROOT/'slide-content.json').write_text(json.dumps(SLIDES,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Created {len(SLIDES)} editable slides in {ROOT}')

if __name__=='__main__':build()
