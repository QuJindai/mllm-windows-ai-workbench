import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AnimeProfileLibrary } from './AnimeProfileLibrary';
import { useAnimeProfiles } from './useAnimeProfiles';
import { FacePolishControls } from './FacePolishControls';
import { identityDefaults } from '../../../domain/identity';
import type { AnimeProfile } from '../../../domain/identity';

const parent={id:'person-a',name:'Example-素颜',state:'ready' as const,referenceId:'ref-a',faceIndex:0,defaults:{},error:null,createdAt:'',updatedAt:''};
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

function Demo() {
  const library=useAnimeProfiles(true);
  return <><AnimeProfileLibrary profiles={library.profiles} profile={parent} jobs={[]}
    pending={library.pending} error={library.error} onCreate={library.create} onImport={library.importImage}/>
    <FacePolishControls value={identityDefaults} onChange={()=>{}} allowAnime capability={{ready:true,message:'可用'}}
      animeCapability={{ready:true,message:'可用'}} animeProfiles={library.profiles}/></>;
}

it('imports an external portrait without a generation job and reads back a selectable anime archive', async()=>{
  let rows: AnimeProfile[]=[];
  const submissions: unknown[]=[];
  vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
    if(url==='/api/identity/anime-profiles/import') {
      const body=JSON.parse(String(init?.body));submissions.push(body);
      rows=[{id:'anime-imported',name:body.name,profileId:body.profileId,referenceId:'ref-a',faceIndex:0,
        sourceKind:'upload',sourceJobId:null,sourceLabel:body.sourceLabel,sourceName:body.sourceName,
        state:'ready',imageUrl:'/imported.png',error:null}];
      return Response.json(rows[0]);
    }
    if(url==='/api/identity/anime-profiles') return Response.json(rows);
    throw new Error(`Unexpected request ${url}`);
  });
  render(<Demo/>);
  fireEvent.change(screen.getByLabelText('动漫档案名称'),{target:{value:'Example-动漫-GPT'}});
  fireEvent.click(screen.getByLabelText('导入外部图片'));
  fireEvent.change(screen.getByLabelText('图片来源说明'),{target:{value:'GPT'}});
  fireEvent.change(screen.getByLabelText('选择动漫底图'),{target:{files:[new File(['portrait'],'Example-04.png',{type:'image/png'})]}});
  await waitFor(()=>expect(screen.getByAltText('待导入动漫底图')).toHaveAttribute('src','data:image/png;base64,cG9ydHJhaXQ='));
  fireEvent.click(screen.getByRole('button',{name:'导入并建立动漫档案'}));
  await screen.findByRole('option',{name:'Example-动漫-GPT · 动漫局部重绘'});
  expect(submissions).toEqual([{name:'Example-动漫-GPT',profileId:'person-a',sourceName:'Example-04.png',sourceLabel:'GPT',imageBase64:'cG9ydHJhaXQ='}]);
  expect(screen.getByText(/可用于修脸/)).toBeInTheDocument();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});

it('shows import errors and does not pretend the archive was created', async()=>{
  vi.stubGlobal('fetch',async(url:string)=>url.endsWith('/import')
    ? Response.json({message:'此动漫档案名称已存在'},{status:409}) : Response.json([]));
  render(<Demo/>);
  fireEvent.change(screen.getByLabelText('动漫档案名称'),{target:{value:'Example-动漫'}});
  fireEvent.click(screen.getByLabelText('导入外部图片'));
  fireEvent.change(screen.getByLabelText('选择动漫底图'),{target:{files:[new File(['portrait'],'image.png',{type:'image/png'})]}});
  await screen.findByAltText('待导入动漫底图');
  fireEvent.click(screen.getByRole('button',{name:'导入并建立动漫档案'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('此动漫档案名称已存在');
  expect(screen.queryByRole('option',{name:'Example-动漫 · 动漫局部重绘'})).not.toBeInTheDocument();
});

it('rejects unsupported uploads and clears a previously selected image', async()=>{
  render(<AnimeProfileLibrary profiles={[]} profile={parent} jobs={[]} pending={false} error={null}
    onCreate={async()=>{}} onImport={async()=>{}}/>);
  fireEvent.change(screen.getByLabelText('动漫档案名称'),{target:{value:'新档案'}});
  fireEvent.click(screen.getByLabelText('导入外部图片'));
  fireEvent.change(screen.getByLabelText('选择动漫底图'),{target:{files:[new File(['portrait'],'image.png',{type:'image/png'})]}});
  await screen.findByAltText('待导入动漫底图');
  fireEvent.change(screen.getByLabelText('选择动漫底图'),{target:{files:[new File(['<svg/>'],'image.svg',{type:'image/svg+xml'})]}});
  expect(await screen.findByRole('alert')).toHaveTextContent('PNG');
  expect(screen.queryByAltText('待导入动漫底图')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'导入并建立动漫档案'})).toBeDisabled();
});
