import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

// Artifact Tool is bundled with the local Codex runtime. An explicit path can
// also be supplied when the application is installed in a different location.
const modulePath=process.env.MEETING_ARTIFACT_MODULE || path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs');
const {Presentation,PresentationFile}=await import(pathToFileURL(modulePath).href);
let input=''; for await (const chunk of process.stdin) input+=chunk;
const data=JSON.parse(input);
const {meeting, slideBackground, coverBackground, bioBackground, profileImages={}, logo, divider, output}=data;
const rows=(meeting.data.agenda||[]).filter(r=>String(r.item||'').trim());
if (!slideBackground || !rows.length) throw Error('请先选择串场 KV 并填写日程。');
const presentation=Presentation.create({slideSize:{width:1280,height:720}});
const blobs={};
for(const file of new Set([slideBackground,coverBackground,bioBackground,logo,divider,...Object.values(profileImages)].filter(Boolean))){
  const ext=path.extname(file).toLowerCase();
  blobs[file]={blob:new Uint8Array(await fs.readFile(file)),contentType:ext==='.png'?'image/png':ext==='.webp'?'image/webp':'image/jpeg'};
}

function text(slide,value,position,size,{bold=false,align='center',color='#111111'}={}){
  const shape=slide.shapes.add({geometry:'textbox',position,fill:'none',line:{style:'solid',fill:'none',width:0}});
  shape.text=String(value);
  shape.text.style={typeface:'Arial Unicode MS',fontSize:size,bold,color,alignment:align,verticalAlignment:'middle',autoFit:'shrinkText',wrap:'square',insets:0};
  return shape;
}
function base(imagePath){
  const slide=presentation.slides.add();
  slide.background.fill='#ffffff';
  slide.images.add({...blobs[imagePath],fit:'contain',position:{left:0,top:0,width:1280,height:720}});
  let left=26;
  if(logo){slide.images.add({...blobs[logo],fit:'contain',position:{left:22,top:14,width:54,height:55}});left=85}
  if(meeting.data.project_name) text(slide,meeting.data.project_name,{left,top:17,width:720,height:52},22,{bold:true,align:'left'});
  return slide;
}
function chunks(value,max){
  const chars=Array.from(String(value||'').trim());const out=[];
  while(chars.length) out.push(chars.splice(0,max).join(''));
  return out.length?out:[''];
}

const cover=base(coverBackground||slideBackground);
if(!coverBackground) text(cover,meeting.title,{left:110,top:228,width:1060,height:210},62,{bold:true});
const emitted=new Set();
for(const row of rows){
  for(const part of chunks(row.item,38)){
    const slide=base(slideBackground);
    text(slide,part,{left:175,top:205,width:930,height:150},part.length>25?43:55,{bold:true});
    if(divider) slide.images.add({...blobs[divider],fit:'contain',position:{left:178,top:357,width:924,height:10}});
    if(row.speaker) text(slide,row.speaker,{left:200,top:385,width:880,height:70},30,{bold:true});
  }
  const peopleText=[row.speaker,row.item,row.note].join('').replace(/\s/g,'');
  for(const profile of meeting.data.profiles||[]){
    const name=String(profile.name||'').trim();
    if(!name||emitted.has(name)||!peopleText.includes(name.replace(/\s/g,'')))continue;
    const photo=profileImages[String(profile.photo_file_id||'')];
    if(!photo&&!String(profile.bio||'').trim()&&!String(profile.organization||'').trim())continue;
    emitted.add(name);
    const biography=chunks(profile.bio||'',150);
    for(const part of biography){
      const slide=base(bioBackground||slideBackground);
      if(photo)slide.images.add({...blobs[photo],fit:'cover',geometry:'ellipse',position:{left:130,top:150,width:250,height:250}});
      text(slide,name,{left:95,top:420,width:320,height:52},30,{bold:true});
      if(profile.organization)text(slide,profile.organization,{left:70,top:473,width:370,height:68},23,{bold:true});
      if(part)text(slide,part,{left:490,top:160,width:650,height:390},25,{align:'left'});
    }
  }
  if(/讨论|问答|圆桌/.test(row.item||'') && String(row.note||'').trim()){
    for(const part of chunks(row.note,150)){
      const slide=base(slideBackground);
      text(slide,row.item,{left:120,top:155,width:1040,height:60},36,{bold:true,align:'left'});
      text(slide,part,{left:120,top:235,width:1040,height:330},29,{align:'left'});
    }
  }
}
const pptx=await PresentationFile.exportPptx(presentation);
await pptx.save(output);
