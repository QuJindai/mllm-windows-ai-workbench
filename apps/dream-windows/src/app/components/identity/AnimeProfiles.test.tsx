import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { AnimeProfileLibrary } from './AnimeProfileLibrary';
import { FacePolishControls } from './FacePolishControls';
import { identityDefaults, identityFacePolishOptions } from '../../../domain/identity';

const anime = {id:'anime-'+'a'.repeat(24),name:'Example-动漫',profileId:'person-a',referenceId:'ref-a',faceIndex:0,
  sourceJobId:'job-a',state:'ready' as const,imageUrl:'/api/identity/anime-profiles/anime-a/image',error:null};
afterEach(() => {cleanup();vi.restoreAllMocks();});

it('selects anime without opting into polish, then exposes anime-only strength', () => {
  function Demo() {
    const [value,setValue]=useState({...identityDefaults});
    return <FacePolishControls value={value} onChange={v=>setValue({...value,...v})}
      capability={{ready:false,message:'真人修脸未配置'}} animeCapability={{ready:true,message:'动漫已就绪'}}
      animeProfiles={[anime]} allowAnime />;
  }
  render(<Demo/>);
  fireEvent.change(screen.getByLabelText('修脸参考'),{target:{value:anime.id}});
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByAltText('动漫修脸参考：Example-动漫')).toHaveAttribute('src',anime.imageUrl);
  fireEvent.click(screen.getByRole('checkbox'));
  expect(screen.getByLabelText('动漫局部重绘强度')).toHaveValue(.35);
  expect(screen.queryByLabelText('面部细节修复强度')).not.toBeInTheDocument();
});

it('keeps anime ID and bounded strength in draft/history options', () => {
  expect(identityFacePolishOptions({facePolish:true,animeProfileId:anime.id,animeDenoiseStrength:.4})).toMatchObject({
    facePolish:true,animeProfileId:anime.id,animeDenoiseStrength:.4});
});

it('creates from the explicitly selected completed result, with parent binding', async () => {
  const create=vi.fn(async()=>undefined);
  render(<AnimeProfileLibrary profiles={[]} profile={{id:'person-a',name:'Example',state:'ready',referenceId:'ref-a',faceIndex:0,defaults:{},error:null,createdAt:'',updatedAt:''}}
    jobs={[{id:'job-a',state:'complete',request:{...identityDefaults,modelId:'illustrious-xl-v2.0-faceid',referenceId:'ref-a',faceIndex:0},progress:100,message:'完成',error:null,result:{imageUrl:'/source.png',metadata:{}}}]}
    pending={false} error={null} onCreate={create} onImport={async()=>{}}/>);
  fireEvent.change(screen.getByLabelText('动漫档案名称'),{target:{value:'Example-动漫'}});
  fireEvent.click(screen.getByRole('button',{name:'保存为动漫档案'}));
  await waitFor(()=>expect(create).toHaveBeenCalledWith({name:'Example-动漫',profileId:'person-a',jobId:'job-a'}));
});
