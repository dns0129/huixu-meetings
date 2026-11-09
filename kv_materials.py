"""Render the variable meeting fields on top of an unchanged supplied KV."""
from __future__ import annotations

import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from materials import font, fit, wrap


def a4_kv(path, width=1240):
    if not path or not Path(path).is_file():
        raise ValueError('请先在 KV 库中上传并选择对应的底图。')
    height=round(width*297/210)
    with Image.open(path) as src:
        bg=ImageOps.contain(src.convert('RGB'),(width,height),Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(width,height),'white')
    canvas.paste(bg,((width-bg.width)//2,(height-bg.height)//2))
    return canvas


def brand(img, data, logo_path, x, y, w, h):
    draw=ImageDraw.Draw(img); gap=int(w*.012); text_x=x
    if logo_path and Path(logo_path).is_file():
        with Image.open(logo_path) as source: logo=source.convert('RGBA')
        logo.thumbnail((int(w*.065),int(h*.85)),Image.Resampling.LANCZOS)
        img.paste(logo,(int(x),int(y+(h-logo.height)/2)),logo)
        text_x=x+logo.width+gap
    project=str(data.get('project_name','')).strip()
    if project:
        ft,lines,leading=fit(draw,project,'hei',h*.30,h*.18,w-(text_x-x),h*.8,max_lines=2)
        yy=y+(h-len(lines)*leading)/2
        for line in lines:
            draw.text((text_x,yy),line,font=ft,fill='#171322'); yy+=leading


def centered(draw,text,box,font_obj,fill):
    x0,y0,x1,y1=box
    draw.text(((x0+x1-draw.textlength(text,font=font_obj))/2,y0),text,font=font_obj,fill=fill)


def _image_output(img,fmt,dpi=150):
    out=io.BytesIO()
    if fmt=='pdf': img.save(out,'PDF',resolution=dpi)
    else: img.save(out,'PNG',dpi=(dpi,dpi))
    out.seek(0); return out


def agenda_kv(title,data,kv_path,logo_path=None,fmt='png'):
    img=a4_kv(kv_path); w,h=img.size; draw=ImageDraw.Draw(img)
    brand(img,data,logo_path,int(w*.026),int(h*.01),int(w*.94),int(h*.052))
    draw=ImageDraw.Draw(img); ink='#704ac2'; strong='#462187'
    heading=font('hei',w*.056)
    centered(draw,'会议日程',(0,h*.257,w,h*.31),heading,strong)
    label_font=font('hei',w*.019); value_font=font('hei',w*.020)
    for row,(label,value) in enumerate((('会议日期','  '.join(filter(None,[data.get('date'),data.get('time')]))),('会议地点',data.get('location','')))):
        yy=int(h*(.318+row*.027)); draw.rounded_rectangle((w*.055,yy,w*.155,yy+h*.022),radius=4,fill='#784dc1')
        centered(draw,label,(w*.055,yy+h*.001,w*.155,yy+h*.022),label_font,'white')
        ft,lines,lead=fit(draw,str(value or '待确认'),'hei',w*.020,w*.013,w*.77,h*.023,max_lines=1)
        draw.text((w*.17,yy),lines[0],font=ft,fill=ink)
    rows=[r for r in data.get('agenda',[]) if any(str(r.get(k,'')).strip() for k in ('time','item','speaker','note'))]
    if not rows: raise ValueError('请先填写会议日程。')
    x=[int(w*f) for f in (.026,.19,.72,.975)]; table_top=int(h*.38); bottom=int(h*.945); head=int(h*.030)
    draw.rectangle((x[0],table_top,x[-1],table_top+head),fill='#5a289c')
    hf=font('hei',w*.021)
    for i,label in enumerate(('时间','议程','讲者 / 主持人')):
        centered(draw,label,(x[i],table_top+head*.08,x[i+1],table_top+head),hf,'white')
        if i: draw.line((x[i],table_top,x[i],table_top+head),fill='white',width=2)
    available=bottom-(table_top+head); layout=None
    for size in range(int(w*.021),int(w*.012)-1,-1):
        ft=font('hei',size); lh=size*1.22; specs=[]
        for row in rows:
            item=str(row.get('item','')).strip()
            note=str(row.get('note','')).strip()
            if note and note not in item: item+='\n'+note
            vals=[str(row.get('time','')).strip(),item,str(row.get('speaker','')).strip()]
            lines=[wrap(draw,v,ft,x[i+1]-x[i]-int(w*.015)) for i,v in enumerate(vals)]
            height=max(size*1.85,max(len(v) for v in lines)*lh+size*.55)
            specs.append((lines,height))
        if sum(s[1] for s in specs)<=available:
            layout=(ft,lh,specs); break
    if not layout: raise ValueError('日程内容超出一页可读范围，请缩短内容或拆分日程。')
    ft,lh,specs=layout; y=table_top+head
    for lines,height in specs:
        for i,column in enumerate(lines):
            yy=y+(height-len(column)*lh)/2
            for line in column:
                if i==1: xx=x[i]+w*.008
                else: xx=(x[i]+x[i+1]-draw.textlength(line,font=ft))/2
                draw.text((xx,yy),line,font=ft,fill=ink); yy+=lh
        y+=height
        draw.line((x[0],y,x[-1],y),fill=ink,width=2)
    return _image_output(img,fmt)


def folded_cards(data,kv_path,logo_path=None,fmt='pdf'):
    names=[n.strip() for n in str(data.get('guests','')).splitlines() if n.strip()]
    if not names: raise ValueError('请先核对并填写最终日程中的老师名单。')
    if len(names)>100: raise ValueError('单次最多生成 100 张席卡。')
    images=[]
    for name in names:
        img=a4_kv(kv_path,width=2480); w,h=img.size
        face=Image.new('RGBA',(w,h//3),(0,0,0,0)); draw=ImageDraw.Draw(face)
        # Add the same branding and name to both faces; the upper face is rotated.
        brand(face,data,logo_path,int(w*.025),int(h*.674-h*2/3),int(w*.72),int(h*.038))
        draw=ImageDraw.Draw(face)
        display='　'.join(name) if len(name)==2 else name
        ft,lines,lh=fit(draw,display,'hei',w*.16,w*.075,w*.8,face.height*.5,max_lines=1)
        y=(face.height-lh)*.46
        centered(draw,lines[0],(0,y,w,y+lh),ft,'#8d70c6')
        img.paste(face,(0,h*2//3),face)
        upper=face.rotate(180)
        img.paste(upper,(0,h//3),upper)
        images.append(img)
    if fmt!='pdf': return images
    out=io.BytesIO(); images[0].save(out,'PDF',save_all=True,append_images=images[1:],resolution=300)
    out.seek(0); return out
