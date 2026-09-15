#!/usr/bin/env python3
import os, subprocess
from PIL import Image, ImageDraw, ImageFont
W,H,N = 1552,992,414
OUT = "/home/shiva/projects/backstop/demo.gif"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BG=(0,43,54); DIV=(30,74,84); BOLD=(232,238,240); DIM=(124,154,161)
TH=(138,165,173); RUN=(224,151,78); ERR=(200,90,84); GRN=(63,163,77)
COR=(230,111,77); PRM=(157,180,186); WHT=(245,242,245); HL=(42,63,69); CUR=(131,148,155)
F = lambda p,s: ImageFont.truetype(p,s)
fT=F(FB,30); fM=F(FR,26); fP=F(FB,30); fB=F(FB,28); fD=F(FR,24); fS=F(FR,24); fG=F(FB,64)
WP = Image.new("RGB",(W,H))
_d = ImageDraw.Draw(WP)
for x in range(W):
    t=x/W
    r=int(74*(1-t)+8*t); g=int(46*(1-t)+109*t); b=int(30*(1-t)+194*t)
    if ((x*2654435761) & 7)==0:
        r=min(255,r+2); g=min(255,g+2); b=min(255,b+2)
    _d.line([(x,0),(x,H)],fill=(r,g,b))
WP = Image.blend(WP, Image.new("RGB",(W,H),(10,20,28)), 0.55)
MASK = Image.new("L",(1458,842),0)
ImageDraw.Draw(MASK).rounded_rectangle([0,0,1457,841],radius=28,fill=255)
PILLS={18:"->|",19:"->|",74:"<-",75:"<-",189:"->|",190:"->|",252:"<-",253:"<-"}
PILL_BOX=[601,650,951,810]
def step(f):
    if f<21: return "1-8"
    if f<75: return "2-8"
    if f<144: return "3-8"
    if f<196: return "4-8"
    if f<253: return "5-8"
    if f<341: return "6-8"
    if f<380: return "7-8"
    return "8-8"
RD=[("b","o Read(task.yaml)"),("d","  L 4 lines - 3 runners x claude-sonnet-4"),("t",".. Thought for 4s (ctrl+o to show thinking)"),("b","o Wrap(R0 - budget 20,000 - own kill-switch)"),("d","  L isolated transport - no shared history"),("b","o Wrap(R1 - budget 20,000 - own kill-switch)"),("d","  L isolated transport - no shared history"),("b","o Wrap(R2 - budget 20,000 - own kill-switch)"),("d","  L isolated transport - no shared history"),("t",".. Thought for 6s (ctrl+o to show thinking)"),("r","* Running 3 isolated runners... (esc to interrupt)"),("d","  L Next: collect patches + token budgets"),("b","o Bash(R0 - refactor main.py to class)"),("d","  L Running... class Main keeps CLI shape"),("b","o Bash(R1 - refactor main.py to class)"),("d","  L Running... class Main keeps CLI shape"),("b","o Bash(R2 - refactor main.py to class)"),("d","  L Running... extra helper module"),("b",'o Search(class Main - def main)'),("d","  L Found 3 patches (ctrl+o to expand)"),("r","* Running tests with coverage... (esc to interrupt)"),("d","  L Next: pytest per runner - 60s timeout"),("b","o Bash(pytest tests/ - R0 R1)"),("d","  L 2 passed - 0.8s - budgets on track"),("e","o Bash(pytest tests/ - R2)"),("e","  L Error: 1 failed - assert CLI shape"),("t",".. Thought for 9s (ctrl+o to show thinking)"),("b","o Read(patch R0 - +42 -18)"),("d","  L class Main - keeps CLI - tests pass"),("b","o Read(patch R1 - +39 -17)"),("d","  L class Main - keeps CLI - tests pass"),("b","o Read(patch R2 - +51 -22 retry ok)"),("d","  L class Main + helper - tests pass"),("b","o Search(similarity - difflib hunks)"),("d","  L Found 92 hunks (ctrl+o to expand)"),("t",".. Thought for 7s - convergence scoring"),("b","o Budget(R0 1,842 - R1 1,910 - R2 2,305)"),("d","  L all under 20,000 - 0 blocked - 0 tripped"),("r","* Scoring convergence... (esc to interrupt)"),("d","  L Next: converge / partial / diverge"),("b","o Report(main.py - PARTIAL sim=0.98)"),("d","  L 2/3 converge - 3/3 tests pass"),("b","o Write(wedge_report.md)"),("d","  L side-by-side diffs + per-runner budgets")]
AF=[24+int(i*324/(len(RD)-1)) for i in range(len(RD))]
print("rows",len(RD),flush=True)
def render(f):
    base = WP.copy()
    # 1px shimmer keeps every full-canvas frame byte-distinct so the GIF
    # encoder cannot merge static beats into long single-frame holds.
    px = base.load()
    v = (f * 7) & 3
    px[f % W, (f * 13) % H] = (10+v, 20+v, 28+v)
    win = Image.new("RGB",(1458,842),BG)
    d = ImageDraw.Draw(win)
    for cx,c in ((67,(251,96,91)),(109,(254,188,47)),(151,(39,200,64))):
        d.ellipse([cx-14,16,cx+14,44],fill=c)
    d.text((729,30),"Wedge multi-agent diff",font=fT,fill=WHT,anchor="mm")
    d.text((1434,30),step(f),font=fT,fill=WHT,anchor="rm")
    d.rounded_rectangle([20,62,110,142],radius=12,fill=COR)
    d.rectangle([38,92,52,112],fill=(0,0,0))
    d.rectangle([78,92,92,112],fill=(0,0,0))
    d.text((130,72),"backstop v0.5.0",font=fT,fill=(159,179,184))
    d.text((130,106),"claude-sonnet-4 - 3 runners x 20k budget",font=fM,fill=DIM)
    d.text((130,134),"~/projects/backstop",font=fM,fill=DIM)
    d.line([(20,214),(1438,214)],fill=DIV,width=2)
    pr = "> wedge run task.yaml"
    pw = 24 + d.textlength(pr,font=fP) + 8 + 18 + 16
    if f >= 20:
        d.rectangle([20,226,pw,268],fill=HL)
    d.text((24,232),pr,font=fP,fill=PRM)
    pcx = 24 + d.textlength(pr,font=fP) + 8
    d.rectangle([pcx,232,pcx+18,264],fill=CUR)
    d.line([(20,290),(1438,290)],fill=DIV,width=2)
    sx = 24
    d.text((sx,300),"main ",font=fS,fill=DIM)
    sx = sx + d.textlength("main ",font=fS)
    d.text((sx,300),"(backstop)",font=fS,fill=ERR)
    rl = "/wedge for Claude" if f < 20 else "Thinking on (tab to toggle)"
    d.text((1434,300),rl,font=fS,fill=DIM,anchor="rm")
    y = 340
    vis = []
    idx = 0
    while idx < len(RD):
        if AF[idx] <= f:
            vis.append(RD[idx])
        idx = idx + 1
    vis = vis[-11:]
    for k,t in vis:
        if k == "b":
            d.text((24,y),"o ",font=fB,fill=GRN)
            ox = 24 + d.textlength("o ",font=fB)
            d.text((ox,y),t[2:],font=fB,fill=BOLD)
        elif k == "r":
            d.text((24,y),t,font=fB,fill=RUN)
        elif k == "e":
            ff = fB if t.startswith("o ") else fD
            d.text((24,y),t,font=ff,fill=ERR)
        elif k == "t":
            d.text((24,y),t,font=fD,fill=TH)
        else:
            d.text((24,y),t,font=fD,fill=DIM)
        y = y + 37
    d.text((24,750),">",font=fP,fill=PRM)
    d.rectangle([52,750,70,782],fill=CUR)
    bx = 24
    d.text((bx,786),"main ",font=fS,fill=DIM)
    bx = bx + d.textlength("main ",font=fS)
    d.text((bx,786),"(backstop)",font=fS,fill=ERR)
    d.text((1434,786),"wedge - 3 runners",font=fS,fill=DIM,anchor="rm")
    if f in PILLS:
        d.rounded_rectangle(PILL_BOX,radius=48,fill=(20,24,29))
        d.text(((PILL_BOX[0]+PILL_BOX[2])//2,(PILL_BOX[1]+PILL_BOX[3])//2),PILLS[f],font=fG,fill=(255,255,255),anchor="mm")
    base.paste(win,(45,108),MASK)
    return base
DUR=[100]*N
DUR[2]=400; DUR[13]=400; DUR[74]=200; DUR[189]=200; DUR[195]=200; DUR[252]=200
if __name__=="__main__":
    # Spec export: 414 full-canvas frames, delay map DUR, single-play.
    # PNG frames -> ffmpeg concat at 10fps + paletteuse -> gifsicle normalize.
    # Long holds are realized by duplicating that PNG K times at 100ms, so
    # every emitted delay is exactly 100ms and the total runtime stays exact.
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="dgpng_")
    rep = [max(1,int(round(DUR[i]/100.0))) for i in range(N)]
    order = []
    i=0
    while i<N:
        order.extend([i]*rep[i])
        i=i+1
    # Expanded count: 414 slots + 10 extra hold ticks = 424 frames, 42.4s.
    print("expanded %d/414" % len(order),flush=True)
    f=0
    while f<N:
        render(f).save("%s/f%04d.png" % (tmp,f))
        f=f+1
        if f%60==0 or f==N:
            print("rendered %d/%d" % (f,N),flush=True)
    print("png dir %s" % tmp,flush=True)
    lst = os.path.join(tmp,"list.txt")
    fd = open(lst,"w")
    j=0
    while j<len(order):
        fd.write("file '%s/f%04d.png'\n" % (tmp,order[j]))
        j=j+1
    fd.close()
    r = subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-r","10","-i",lst,"-vf","palettegen=max_colors=256","/tmp/dg_pal.png"],capture_output=True,text=True)
    print((r.stdout or "")[-500:],flush=True)
    print((r.stderr or "")[-2000:],flush=True)
    r2 = subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-i","/tmp/dg_pal.png","-lavfi","paletteuse","-gifflags","-offsetting",OUT],capture_output=True,text=True)
    print((r2.stderr or "")[-2000:],flush=True)
    # Normalize: single-play (disposal=1 do-not-dispose per reference spec).
    subprocess.run(["gifsicle","--disposal=asis","--no-loopcount","--no-extensions",OUT,"-o",OUT+".fix"],check=True)
    os.replace(OUT+".fix",OUT)
    shutil.rmtree(tmp,ignore_errors=True)
    mb=os.path.getsize(OUT)/1e6
    print("saved %.2f MB" % mb,flush=True)
    if mb>13:
        subprocess.run(["gifsicle","-O3","--colors","256",OUT,"-o",OUT+".o"],check=True)
        os.replace(OUT+".o",OUT)
        print("opt %.2f MB" % (os.path.getsize(OUT)/1e6),flush=True)
    im=Image.open(OUT); n=getattr(im,"n_frames",1)
    im2=Image.open(OUT); hh={}; i=0
    while i<n:
        im2.seek(i); k=im2.info.get("duration"); hh[k]=hh.get(k,0)+1; i=i+1
    raw=open(OUT,"rb").read()
    print("VALIDATE frames=%d size=%dx%d MB=%.2f loop=%s delays=%s" % (n,im.size[0],im.size[1],len(raw)/1e6,"NETSCAPE" in str(raw[:4000]),hh),flush=True)
