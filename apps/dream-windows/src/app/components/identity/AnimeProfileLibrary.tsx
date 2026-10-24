import { useEffect, useId, useRef, useState } from 'react';
import { ILLUSTRIOUS_IDENTITY_MODEL_ID } from '../../../domain/identity';
import type { AnimeProfile, AnimeProfileImport, IdentityJob, IdentityProfile } from '../../../domain/identity';
import { readReferenceFile } from '../../../providers/identity-api';
import { useDeletedImageIds } from '../../image-deletion';

export function AnimeProfileLibrary({profiles,profile,jobs,pending,error,onCreate,onImport}: {
  profiles:AnimeProfile[]; profile:IdentityProfile|null; jobs:IdentityJob[]; pending:boolean; error:string|null;
  onCreate:(body:{name:string;profileId:string;jobId:string})=>Promise<void>;
  onImport:(body:AnimeProfileImport)=>Promise<void>;
}) {
  const [name,setName]=useState('');
  const [selected,setSelected]=useState('');
  const [mode,setMode]=useState<'local-job'|'upload'>('local-job');
  const [sourceLabel,setSourceLabel]=useState('外部图片');
  const [upload,setUpload]=useState<{name:string;base64:string;preview:string}|null>(null);
  const [fileError,setFileError]=useState<string|null>(null);
  const [reading,setReading]=useState(false);
  const revision=useRef(0), group=useId();
  useEffect(()=>()=>{revision.current++;},[]);
  const selectFile=async(file?:File)=>{
    const version=++revision.current;
    setUpload(null);setFileError(null);setReading(!!file);
    if(!file) return;
    try {
      const base64=await readReferenceFile(file);
      if(version===revision.current) setUpload({name:file.name,base64,preview:`data:${file.type};base64,${base64}`});
    } catch(e) {if(version===revision.current) setFileError(e instanceof Error ? e.message : '动漫底图读取失败');}
    finally {if(version===revision.current) setReading(false);}
  };
  const deleted=useDeletedImageIds();
  const candidates=jobs.filter(j=>j.state==='complete' && !j.resultDeleted && !j.historyDeleted && !deleted.has(j.id) && j.result
    && j.request.modelId===ILLUSTRIOUS_IDENTITY_MODEL_ID && j.request.referenceId===profile?.referenceId && j.request.faceIndex===profile?.faceIndex);
  const source=candidates.find(j=>j.id===selected) ?? candidates[0];
  return <section className="identity-anime-library" aria-label="动漫形象档案">
    <h2>动漫形象档案</h2>
    <p className="identity-note">选择本机作品，或导入 GPT 等工具生成的单人动漫底图。关联当前真人档案，单独提取动漫特征；不覆盖已有档案，之后可在“修脸参考”中复用。</p>
    <p className="identity-note">关联人物：{profile?.name ?? '请先选择人物档案'}。修脸仍需手动开启。</p>
    <label>动漫档案名称<input value={name} maxLength={120} placeholder={profile ? `${profile.name}-动漫` : '如 示例人物-动漫'} onChange={e=>setName(e.target.value)}/></label>
    <fieldset className="identity-anime-source"><legend>建档来源</legend>
      <label><input type="radio" name={group} checked={mode==='local-job'} disabled={pending} onChange={()=>setMode('local-job')}/>本机已完成作品</label>
      <label><input type="radio" name={group} checked={mode==='upload'} disabled={pending} onChange={()=>setMode('upload')}/>导入外部图片</label>
    </fieldset>
    {mode==='local-job' ? <><label>建档来源作品<select value={source?.id ?? ''} onChange={e=>setSelected(e.target.value)}>
      {!candidates.length && <option value="">请先选择人物档案并生成单人动漫图</option>}
      {candidates.map(j=><option key={j.id} value={j.id}>{j.request.prompt.slice(0,30)} · {j.id.slice(-8)}</option>)}
    </select></label>
    {source?.result && <img className="identity-anime-thumb" src={source.result.metadata.facePolish?.originalImageUrl ?? source.result.imageUrl} alt="动漫建档来源作品"/>}
    <button type="button" className="secondary-button" disabled={pending || profile?.state!=='ready' || !source || !name.trim()}
      onClick={()=>{if(profile && source) void onCreate({name:name.trim(),profileId:profile.id,jobId:source.id});}}>{pending ? '正在保存…' : '保存为动漫档案'}</button></> : <>
      <label>选择动漫底图<input type="file" accept="image/png,image/jpeg,image/webp" disabled={pending || profile?.state!=='ready'} onChange={e=>void selectFile(e.target.files?.[0])}/></label>
      <p className="identity-note">PNG / JPEG / WebP，最多 10 MiB、1600 万像素；仅上传到本机。透明区域统一使用白底，与下方预览一致。请使用已确认的清晰单人动漫头像。</p>
      <label>图片来源说明<input value={sourceLabel} maxLength={80} placeholder="如 GPT" disabled={pending} onChange={e=>setSourceLabel(e.target.value)}/></label>
      {upload && <img className="identity-anime-thumb identity-anime-upload-preview" src={upload.preview} alt="待导入动漫底图"/>}
      {fileError && <p role="alert" className="identity-error">{fileError}</p>}
      <button type="button" className="secondary-button" disabled={pending || reading || profile?.state!=='ready' || !upload || !name.trim() || !sourceLabel.trim()}
        onClick={()=>{if(profile && upload) void onImport({name:name.trim(),profileId:profile.id,sourceName:upload.name,sourceLabel:sourceLabel.trim(),imageBase64:upload.base64});}}>
        {pending ? '正在导入…' : reading ? '正在读取图片…' : '导入并建立动漫档案'}</button>
    </>}
    {error && <p role="alert" className="identity-error">{error}</p>}
    <ul>{profiles.map(p=><li key={p.id}>{p.name} · {p.state==='ready' ? '可用于修脸' : p.state==='preparing' ? '正在提取动漫特征…' : '建档失败'}{p.sourceKind==='upload' && <span> · 外部导入（{p.sourceLabel}）</span>}{p.error && <p role="alert">{p.error}</p>}</li>)}</ul>
  </section>;
}
