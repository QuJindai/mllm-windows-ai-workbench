import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnimeProfile, AnimeProfileImport } from '../../../domain/identity';
import { identityApi } from '../../../providers/identity-api';

export function useAnimeProfiles(enabled:boolean) {
  const [profiles,setProfiles]=useState<AnimeProfile[]>([]);
  const [error,setError]=useState<string|null>(null);
  const [pending,setPending]=useState(false);
  const mounted=useRef(false),writing=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const refresh=useCallback(async(signal?:AbortSignal)=>{
    try {
      const rows=await identityApi.animeProfiles(signal);
      if(mounted.current && !signal?.aborted) {setProfiles(rows);setError(null);}
    } catch(e) {if(mounted.current && !signal?.aborted) setError(e instanceof Error ? e.message : '动漫档案读取失败');}
  },[]);
  const preparing=profiles.some(p=>p.state==='preparing');
  useEffect(()=>{
    if(!enabled) return;
    const controller=new AbortController();
    void refresh(controller.signal);
    const timer=preparing ? setInterval(()=>void refresh(controller.signal),2000) : undefined;
    return()=>{controller.abort();if(timer) clearInterval(timer);};
  },[enabled,preparing,refresh]);
  const write=useCallback(async(operation:()=>Promise<AnimeProfile>)=>{
    if(writing.current) return;
    writing.current=true;setPending(true);setError(null);
    try {
      await operation();
      await refresh();
    } catch(e) {if(mounted.current) setError(e instanceof Error ? e.message : '动漫建档失败');}
    finally {writing.current=false;if(mounted.current) setPending(false);}
  },[refresh]);
  const create=useCallback((body:{name:string;profileId:string;jobId:string})=>write(()=>identityApi.createAnimeProfile(body)),[write]);
  const importImage=useCallback((body:AnimeProfileImport)=>write(()=>identityApi.importAnimeProfile(body)),[write]);
  return {profiles,error,pending,create,importImage,refresh};
}
