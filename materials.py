from __future__ import annotations

import io
import math
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml.ns import qn

FONTS = {
    'hei': '/System/Library/Fonts/Hiragino Sans GB.ttc',
    'song': '/System/Library/Fonts/Supplemental/Songti.ttc',
    'round': '/System/Library/Fonts/STHeiti Medium.ttc',
}
COLORS = {
    'blue': ('#102a4b','#235b8e','#9ed2ed','#f5f8fc'),
    'forest': ('#173f37','#2f705c','#c4e8ce','#f7fbf8'),
    'wine': ('#51293e','#8c455b','#f0c9ce','#fdf7f7'),
}


def missing_questions(title, d):
    checks = [
        ('date','会议在哪一天举行？','所有物料'),
        ('time','会议从几点开始？','日程、海报、易拉宝'),
        ('location','会议地点和具体地址是什么？','海报、易拉宝、日程'),
        ('organizer','主办方名称是什么？','海报、易拉宝'),
        ('host','主持人是谁？','主持串词'),
        ('guests','需要制作桌卡的嘉宾有哪些？每行填写一位。','桌卡'),
    ]
    out=[{'field':key,'question':question,'applies_to':applies} for key,question,applies in checks if not str(d.get(key,'')).strip()]
    if not any(str(row.get('item','')).strip() for row in d.get('agenda',[])):
        out.append({'field':'agenda','question':'会议有哪些环节？请补充每个环节的时间、内容和发言人。','applies_to':'日程、主持串词'})
    else:
        for index,row in enumerate(d.get('agenda',[]),1):
            if str(row.get('item','')).strip() and not str(row.get('time','')).strip():
                out.append({'field':'agenda','question':f'第 {index} 个议程环节的时间是什么？','applies_to':'日程、主持串词'})
    return out


def agenda_people(d):
    """Suggest named people in agenda order; leave ambiguous labels for review."""
    found=[]; unresolved=[]
    generic={'全体','与会嘉宾','现场工作人员','工作人员','嘉宾','主持人','全体人员','参会人员','听众','与会人员'}
    host=str(d.get('host','')).strip()
    def add(raw):
        text=re.sub(r'^(?:主持人|主持|讲者|发言人|主席)\s*[:：]?\s*','',str(raw).strip())
        if not text or text in generic: return
        prefix=re.split(r'教授|老师|主任|医师|医生|博士|讲师|研究员|顾问|先生|女士|总经理|创始人|[（(]',text,maxsplit=1)[0].strip()
        words=prefix.split()
        candidate=''.join(words) if words and all(len(x)==1 for x in words) else (words[-1] if words else '')
        if re.fullmatch(r'[\u4e00-\u9fff·]{2,6}',candidate) and candidate not in generic:
            if candidate not in found: found.append(candidate)
        elif text not in unresolved:
            unresolved.append(text)
    for row in d.get('agenda',[]):
        speaker=str(row.get('speaker','')).strip()
        for part in re.split(r'[,，、;；/\n]+',speaker): add(part)
        item=str(row.get('item','')).strip(); note=str(row.get('note','')).strip()
        if re.match(r'^主持人\s*[:：]',item): add(item)
        for line in note.splitlines():
            match=re.match(r'^(?:主持人|讨论嘉宾|讨论专家|讲者|发言人)\s*[:：]\s*(.+)',line.strip())
            if match:
                for part in re.split(r'[,，、;；/]+',match.group(1)): add(part)
        if host and host in item+' '+note+' '+speaker: add(host)
    return {'names':found,'unresolved':unresolved}


def safe_excel(v):
    s=str(v or '')
    return "'"+s if s.startswith(('=','+','-','@')) else s


def agenda_excel(title,d):
    wb=Workbook(); ws=wb.active; ws.title='会议日程'
    ws.merge_cells('A1:D1'); ws['A1']=safe_excel(title+'｜会议日程')
    ws['A1'].font=Font(name='微软雅黑',size=18,bold=True,color='FFFFFF'); ws['A1'].fill=PatternFill('solid',fgColor='173C61'); ws['A1'].alignment=Alignment(vertical='center'); ws.row_dimensions[1].height=38
    ws.merge_cells('A2:D2'); ws['A2']=safe_excel('  '.join(filter(None,[d.get('date'),d.get('time'),d.get('location')])))
    ws['A2'].font=Font(name='微软雅黑',size=10,color='496278'); ws.row_dimensions[2].height=26
    for col,name in enumerate(('时间','议程内容','发言人','备注'),1):
        c=ws.cell(4,col,name); c.fill=PatternFill('solid',fgColor='EAF1F7'); c.font=Font(name='微软雅黑',bold=True,color='173C61'); c.alignment=Alignment(vertical='center')
    ws.row_dimensions[4].height=25
    rows=d.get('agenda') or []
    if not rows: rows=[{'time':'待确认','item':'待补充','speaker':'','note':''}]
    for ri,row in enumerate(rows,5):
        for ci,k in enumerate(('time','item','speaker','note'),1):
            c=ws.cell(ri,ci,safe_excel(row.get(k,''))); c.font=Font(name='微软雅黑',size=10,color='24384B'); c.alignment=Alignment(wrap_text=True,vertical='center'); c.border=Border(bottom=Side(style='hair',color='D9E4ED'))
        ws.row_dimensions[ri].height=31
    for i,w in enumerate((20,48,22,36),1): ws.column_dimensions[get_column_letter(i)].width=w
    ws.freeze_panes='B5'; ws.sheet_properties.pageSetUpPr.fitToPage=True; ws.page_setup.fitToWidth=1
    out=io.BytesIO(); wb.save(out); out.seek(0); return out


def setup_doc(doc):
    sec=doc.sections[0]; sec.top_margin=Cm(2.2); sec.bottom_margin=Cm(2.2); sec.left_margin=Cm(2.4); sec.right_margin=Cm(2.4)
    # Use an installed CJK font explicitly so macOS/LibreOffice do not substitute
    # incompatible glyph metrics and overlap Chinese text in exported Word files.
    font_name='Arial Unicode MS' if Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf').is_file() else 'Microsoft YaHei'
    for name in ('Normal','Title','Subtitle'):
        style=doc.styles[name]
        style.font.name=font_name
        fonts=style._element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ('ascii','hAnsi','eastAsia'):
            fonts.set(qn('w:'+attr),font_name)
    style=doc.styles['Normal']; style.font.size=Pt(10.5)
    style.paragraph_format.line_spacing=1.25
    style.paragraph_format.space_after=Pt(4)


def agenda_word(title,d):
    doc=Document(); setup_doc(doc)
    doc.add_heading(title,0); doc.add_paragraph('会议日程',style='Subtitle')
    doc.add_paragraph('日期：'+(d.get('date') or '待确认')+'    时间：'+(d.get('time') or '待确认'))
    doc.add_paragraph('地点：'+(d.get('location') or '待确认')+'    主办：'+(d.get('organizer') or '待确认'))
    table=doc.add_table(rows=1,cols=4); table.style='Light Shading Accent 1'
    for cell,s in zip(table.rows[0].cells,('时间','议程内容','发言人','备注')): cell.text=s
    rows=d.get('agenda') or [{'item':'待补充'}]
    for row in rows:
        cells=table.add_row().cells
        for cell,key in zip(cells,('time','item','speaker','note')): cell.text=str(row.get(key,'') or '')
    out=io.BytesIO(); doc.save(out); out.seek(0); return out


def script_word(title,d):
    doc=Document(); setup_doc(doc); doc.add_heading(title,0); doc.add_paragraph('主持串词',style='Subtitle')
    text=d.get('script','').strip() or make_script(title,d)
    for line in text.splitlines():
        if line.strip(): doc.add_paragraph(line.strip())
    out=io.BytesIO(); doc.save(out); out.seek(0); return out


def make_script(title,d):
    host=d.get('host') or '主持人待确认'; org=d.get('organizer') or '主办方待确认'
    lines=['【开场】',f'各位来宾，大家好！欢迎参加{title}。我是今天的主持人{host}。',f'感谢各位出席本次由{org}举办的会议。接下来，我们将按照会议日程依次进行。','']
    items=[x for x in d.get('agenda',[]) if str(x.get('item','')).strip()]
    if not items: lines.extend(['【会议环节】','会议环节及嘉宾信息待补充。',''])
    for i,row in enumerate(items,1):
        item=row.get('item',''); speaker=row.get('speaker','').strip(); tm=row.get('time','').strip()
        lines.append(f'【环节 {i}｜{item}】')
        lead=(f'接下来是{item}' if i>1 else f'首先进入{item}')
        if tm: lead+=f'，计划时间为{tm}'
        lines.append(lead+'。'+(f'让我们有请{speaker}。' if speaker else '相关嘉宾信息待确认。'))
        lines.append('感谢这一环节的分享，让我们继续接下来的议程。'); lines.append('')
    lines.extend(['【结束】',f'{title}的日程到此结束。感谢各位嘉宾与朋友的参与，祝大家一切顺利！'])
    return '\n'.join(lines)


def font(kind,size):
    path=FONTS.get(kind,kind if Path(str(kind)).is_file() else FONTS['hei'])
    if not Path(path).exists(): path='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
    return ImageFont.truetype(path,max(9,int(size)))


def wrap(draw,text,font_obj,max_width):
    output=[]
    for para in str(text).split('\n'):
        line=''
        for ch in para:
            trial=line+ch
            if line and draw.textlength(trial,font=font_obj)>max_width:
                output.append(line); line=ch
            else: line=trial
        output.append(line)
    return output or ['']


def fit(draw,text,font_key,start,min_size,max_width,max_height,leading=1.28,max_lines=10):
    size=int(start)
    while size >= min_size:
        f=font(font_key,size); lines=wrap(draw,text,f,max_width)
        if len(lines)<=max_lines and len(lines)*size*leading<=max_height: return f,lines,size*leading
        size-=max(1,int(start/45))
    raise ValueError('文字过长，当前尺寸无法完整排版；请缩短文字或增大物料尺寸。')


def line_text(draw,xy,text,font_obj,fill,max_width=None):
    if max_width and draw.textlength(text,font=font_obj)>max_width:
        while text and draw.textlength(text+'…',font=font_obj)>max_width: text=text[:-1]
        text+='…'
    draw.text(xy,text,font=font_obj,fill=fill)


def material_dimensions(d,kind):
    defaults={'poster':(210,297),'banner':(800,2000),'card':(210,100)}
    opts=d.get('design',{}).get(kind,{})
    return float(opts.get('width',defaults[kind][0])),float(opts.get('height',defaults[kind][1]))


def material_size(d,kind,preview=False):
    wm,hm=material_dimensions(d,kind)
    w=float(wm)/25.4*150; h=float(hm)/25.4*150
    limit=1000 if preview else 5000
    maxarea=1_000_000 if preview else 20_000_000
    scale=min(1,limit/max(w,h),math.sqrt(maxarea/(w*h)))
    w=max(64,int(w*scale)); h=max(64,int(h*scale))
    dpi=w/float(wm)*25.4
    return w,h,dpi


def render_editor(d,kind,logo_path,bg_path,fmt,preview,name,font_path):
    w,h,dpi=material_size(d,kind,preview)
    opt=d['design'][kind]; img=Image.new('RGB',(w,h),'white')
    if bg_path and Path(bg_path).exists():
        with Image.open(bg_path) as src: bg=ImageOps.contain(src.convert('RGB'),(w,h),Image.Resampling.LANCZOS)
        img.paste(bg,((w-bg.width)//2,(h-bg.height)//2))
    draw=ImageDraw.Draw(img)
    fkey=str(font_path) if opt.get('font')=='custom' and font_path else opt.get('font','hei')
    for layer in opt['elements']:
        x,y,lw,lh=(int(layer[k]*v) for k,v in (('x',w),('y',h),('w',w),('h',h)))
        if layer['type']=='logo':
            if logo_path and Path(logo_path).exists():
                with Image.open(logo_path) as src: logo=src.convert('RGBA')
                logo.thumbnail((max(1,lw),max(1,lh)),Image.Resampling.LANCZOS)
                img.paste(logo,(x+(lw-logo.width)//2,y+(lh-logo.height)//2),logo); draw=ImageDraw.Draw(img)
            continue
        text=name if layer.get('bind')=='guest' and name else (next((s.strip() for s in str(d.get('guests','')).splitlines() if s.strip()),'嘉宾姓名') if layer.get('bind')=='guest' else layer.get('text',''))
        if not text: continue
        size=max(9,int(layer['size']*w)); ft=font(fkey,size); lines=wrap(draw,text,ft,max(1,lw-4)); lead=size*1.2
        if len(lines)*lead>lh+size*.3: raise ValueError('文字超出边框，请拖大边框或缩小字号。')
        yy=y
        for line in lines:
            tw=draw.textlength(line,font=ft); align=layer.get('align','center')
            xx=x if align=='left' else x+lw-tw if align=='right' else x+(lw-tw)/2
            draw.text((xx,yy),line,font=ft,fill=layer.get('color','#222222')); yy+=lead
    out=io.BytesIO()
    if fmt=='pdf': img.save(out,'PDF',resolution=dpi)
    else: img.save(out,'PNG',dpi=(dpi,dpi),optimize=True)
    out.seek(0); return out


def render_material(title,d,kind,logo_path=None,bg_path=None,fmt='png',preview=False,name='',font_path=None):
    if 'elements' in d.get('design',{}).get(kind,{}):
        return render_editor(d,kind,logo_path,bg_path,fmt,preview,name,font_path)
    w,h,dpi=material_size(d,kind,preview)
    opt=d.get('design',{}).get(kind,{}); fkey=opt.get('font','hei')
    if fkey=='custom':
        if not font_path or not Path(font_path).is_file(): raise ValueError('请先上传自定义字体文件。')
        fkey=str(font_path)
    base,accent,soft,paper=COLORS.get(opt.get('palette','blue'),COLORS['blue'])
    img=Image.new('RGB',(w,h),base); draw=ImageDraw.Draw(img)
    unit=min(w,h); pad=max(12,int(unit*.085))
    if bg_path and Path(bg_path).exists():
        with Image.open(bg_path) as src:
            bg=ImageOps.fit(src.convert('RGB'),(w,h),method=Image.Resampling.LANCZOS)
        img=Image.blend(bg,Image.new('RGB',(w,h),base),0.62); draw=ImageDraw.Draw(img)
    else:
        draw.ellipse((int(w*.52),-int(w*.31),int(w*1.36),int(w*.53)),fill=accent)
        draw.ellipse((int(w*.77),int(h*.56),int(w*1.26),int(h*.56+w*.49)),outline=soft,width=max(1,int(unit*.003)))
        draw.line((int(w*.74),0,int(w*.31),h),fill=accent,width=max(1,int(unit*.002)))
    if kind=='card':
        if logo_path and Path(logo_path).exists():
            with Image.open(logo_path) as source: logo=source.convert('RGBA')
            logo.thumbnail((int(w*.16),int(h*.16)),Image.Resampling.LANCZOS)
            img.paste(logo,(int(pad*1.35),int(pad*1.3)),logo); draw=ImageDraw.Draw(img)
        draw.rounded_rectangle((pad,pad,w-pad,h-pad),radius=int(unit*.035),outline=soft,width=max(1,int(unit*.004)))
        person=name.strip() or next((x.strip() for x in str(d.get('guests','')).splitlines() if x.strip()),'嘉宾姓名待确认')
        f,lines,lead=fit(draw,person,fkey,unit*.25,unit*.07,w-4*pad,h*.47,max_lines=2)
        y=(h-len(lines)*lead)*.5
        for line in lines:
            x=(w-draw.textlength(line,font=f))/2; draw.text((x,y),line,font=f,fill=paper); y+=lead
        small=font(fkey,unit*.052); bottom=title
        if draw.textlength(bottom,font=small)>w-4*pad: bottom=bottom[:30]+'…'
        line_text(draw,((w-draw.textlength(bottom,font=small))/2,h-pad-unit*.09),bottom,small,soft)
    else:
        if logo_path and Path(logo_path).exists():
            with Image.open(logo_path) as source: logo=source.convert('RGBA')
            logo.thumbnail((int(w*.3),int(h*.095)),Image.Resampling.LANCZOS)
            img.paste(logo,(pad,pad),logo); draw=ImageDraw.Draw(img)
        else:
            draw.rectangle((pad,pad,pad+unit*.035,pad+unit*.035),fill=soft)
            line_text(draw,(pad+unit*.05,pad-unit*.006),d.get('organizer') or '会议活动',font(fkey,unit*.037),paper,w-pad*2)
        top= h*(.23 if kind=='poster' else .255)
        line_text(draw,(pad,top-unit*.075),'会 议 邀 请',font(fkey,unit*.035),soft,w-pad*2)
        title_h=h*(.25 if kind=='poster' else .22)
        f,lines,lead=fit(draw,title,fkey,unit*.115,unit*.035,w-2*pad,title_h,max_lines=5)
        y=top
        for line in lines: draw.text((pad,y),line,font=f,fill=paper); y+=lead
        subtitle=(d.get('subtitle') or '').strip()
        if subtitle:
            sf,slines,slead=fit(draw,subtitle,fkey,unit*.047,unit*.025,w-2*pad,h*.12,max_lines=3)
            y+=unit*.025
            for line in slines: draw.text((pad,y),line,font=sf,fill=soft); y+=slead
        y=max(y+unit*.11,h*(.70 if kind=='poster' else .68))
        draw.line((pad,y,w-pad,y),fill=soft,width=max(1,int(unit*.002)))
        y+=unit*.05
        details=[('时间',' '.join(filter(None,[d.get('date'),d.get('time')])) or '待确认'),('地点',d.get('location') or '待确认'),('主办',d.get('organizer') or '待确认')]
        detail_font=font(fkey,unit*.036); label_font=font(fkey,unit*.028)
        for label,value in details:
            line_text(draw,(pad,y),label,label_font,soft)
            vf,vs,vl=fit(draw,value,fkey,unit*.036,unit*.019,w-pad*2-unit*.12,unit*.085,max_lines=2)
            vy=y
            for item in vs: draw.text((pad+unit*.12,vy),item,font=vf,fill=paper); vy+=vl
            y+=unit*.085
        line_text(draw,(pad,h-pad-unit*.02),'MEETING  /  '+str(d.get('date') or 'DATE TO BE CONFIRMED'),font(fkey,unit*.022),soft,w-pad*2)
    out=io.BytesIO()
    if fmt=='pdf': img.save(out,'PDF',resolution=dpi)
    else: img.save(out,'PNG',dpi=(dpi,dpi),optimize=True)
    out.seek(0); return out


def card_archive(title,d,logo_path=None,bg_path=None,font_path=None):
    names=[x.strip() for x in str(d.get('guests','')).splitlines() if x.strip()]
    if not names: raise ValueError('请先填写桌卡嘉宾名单，每行一位。')
    if len(names)>200: raise ValueError('一次最多导出 200 张桌卡。')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for i,name in enumerate(names,1):
            safe=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',name)[:60] or '嘉宾'
            image=render_material(title,d,'card',logo_path,bg_path,name=name,font_path=font_path)
            archive.writestr(f'{i:03d}-{safe}.png',image.getvalue())
    out.seek(0); return out
