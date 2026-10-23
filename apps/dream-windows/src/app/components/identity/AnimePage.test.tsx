import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IdentityPage} from '../../pages/IdentityPage';
import {identityDefaults,IDENTITY_MODEL_ID,ILLUSTRIOUS_IDENTITY_MODEL_ID} from '../../../domain/identity';

const animeId='anime-'+'a'.repeat(24);
const anime={id:animeId,name:'Example-动漫',profileId:'person-a',referenceId:'ref-a',faceIndex:0,state:'ready',imageUrl:'/anime.png'};
const profile={id:'person-a',name:'Example',referenceId:'ref-a',faceIndex:0,state:'ready',defaults:{...identityDefaults,prompt:'anime portrait'},error:null};
const json=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});
let writes:Array<{url:string;body:any}>=[];
let batch:any=null;
beforeEach(()=>{
  localStorage.clear();writes=[];batch=null;
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input),body=init?.body ? JSON.parse(String(init.body)) : null;
    if(init?.method==='POST') writes.push({url,body});
    if(url.endsWith('/status')) return json({ready:true,modelName:'RV',loras:[],message:'ready',facePolish:{ready:false,message:'no real repair'},animePolish:{ready:true,message:'动漫就绪'},
      models:[{id:IDENTITY_MODEL_ID,name:'RV',ready:true,architecture:'SD1.5',loras:[]},{id:ILLUSTRIOUS_IDENTITY_MODEL_ID,name:'Illustrious',ready:true,architecture:'SDXL',loras:[]}]});
    if(url==='/api/identity/profiles') return json([profile]);
    if(url==='/api/identity/profiles/person-a') return json(profile);
    if(url==='/api/identity/references') return json([{id:'ref-a',name:'Example ref',imageUrl:'/ref.png',faces:[{index:0,box:[1,1,50,50]}]}]);
    if(url==='/api/identity/anime-profiles') return json([anime]);
    if(url==='/api/identity/jobs') return json(batch?.items ?? []);
    if(url==='/api/identity/batches' && init?.method==='POST') {
      const item={id:'job-a',request:body.request,state:'complete',progress:100,message:'完成',error:null,result:{imageUrl:'/final.png',metadata:{facePolish:{enabled:true,status:'completed',originalImageUrl:'/original.png',method:'anime-reference-local-redraw',profileName:'Example-动漫'}}}};
      batch={id:'batch-a',request:body,state:'complete',items:[item],completedItems:1,totalItems:1,currentItem:1,step:30,totalSteps:30,progress:100,stage:'完成',elapsedMs:1000,etaMs:null,previewUrl:null,error:null};
      return json(batch);
    }
    if(url==='/api/identity/batches') return json(batch ? [batch] : []);
    if(url==='/api/identity/batches/batch-a') return json(batch);
    throw new Error('Unexpected URL '+url);
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
async function selectAnime() {
  await waitFor(()=>expect(screen.getByLabelText('选择人物档案')).toBeEnabled());
  fireEvent.change(screen.getByLabelText('选择人物档案'),{target:{value:'person-a'}});
  await waitFor(()=>expect(screen.getByLabelText('场景提示词')).toHaveValue('anime portrait'));
  fireEvent.change(screen.getByLabelText('人物底图模型'),{target:{value:ILLUSTRIOUS_IDENTITY_MODEL_ID}});
  await screen.findByRole('option',{name:'Example-动漫 · 动漫局部重绘'});
  fireEvent.change(screen.getByLabelText('修脸参考'),{target:{value:animeId}});
  fireEvent.click(screen.getByRole('checkbox',{name:'生成后修脸（可选）'}));
}

it('retains anime draft with the compatible base model after remount',async()=>{
  const view=render(<IdentityPage/>);await selectAnime();view.unmount();render(<IdentityPage/>);
  await waitFor(()=>expect(screen.getByLabelText('选择人物档案')).toHaveValue('person-a'));
  await waitFor(()=>expect(screen.getByLabelText('人物底图模型')).toHaveValue(ILLUSTRIOUS_IDENTITY_MODEL_ID));
  expect(screen.getByRole('checkbox',{name:'生成后修脸（可选）'})).toBeChecked();
  await waitFor(()=>expect(screen.getByRole('button',{name:'生成人物图像'})).toBeEnabled());
});

it('submits the selected anime binding and restores it from the completed batch',async()=>{
  const view=render(<IdentityPage/>);await selectAnime();
  fireEvent.click(screen.getByRole('button',{name:'生成人物图像'}));
  await waitFor(()=>expect(writes).toHaveLength(1));
  expect(writes[0].body.request).toMatchObject({modelId:ILLUSTRIOUS_IDENTITY_MODEL_ID,animeProfileId:animeId,animeDenoiseStrength:.35,facePolish:true});
  await screen.findByText('修脸完成 · Example-动漫 · 动漫局部重绘');
  view.unmount();render(<IdentityPage/>);
  await waitFor(()=>expect(screen.getByLabelText('修脸参考')).toHaveValue(animeId));
  expect(screen.getByLabelText('动漫局部重绘强度')).toHaveValue(.35);
});

it('keeps an explicit return to real-face reference after refresh',async()=>{
  const view=render(<IdentityPage/>);await selectAnime();
  fireEvent.click(screen.getByRole('button',{name:'生成人物图像'}));
  await screen.findByText('修脸完成 · Example-动漫 · 动漫局部重绘');
  fireEvent.change(screen.getByLabelText('修脸参考'),{target:{value:''}});
  view.unmount();render(<IdentityPage/>);
  await waitFor(()=>expect(screen.getByLabelText('选择人物档案')).toBeEnabled());
  await waitFor(()=>expect(screen.getByLabelText('修脸参考')).toHaveValue(''));
  expect(screen.queryByLabelText('动漫局部重绘强度')).not.toBeInTheDocument();
});
