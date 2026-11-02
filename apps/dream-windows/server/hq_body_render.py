"""Re-render only confirmed mannequin artifacts with the local HQ checkpoint and garment adapter."""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from hq_repair_version import DIRECT


def local_box(w, h, cx, cy, width, height):
    width=min(w,max(64,int(round(width/8))*8)); height=min(h,max(64,int(round(height/8))*8))
    x=min(w-width,max(0,round(cx-width/2))); y=min(h-height,max(0,round(cy-height/2)))
    return (x,y,x+width,y+height)


def build_masks(photo,guide,regions):
    src=np.asarray(photo); changed=np.any(src!=np.asarray(guide),axis=2)
    H,W=changed.shape; Y,X=np.ogrid[:H,:W]; passes=[]
    knees=[r for r in regions if r['part']=='knee' and r['method'] not in DIRECT]
    if knees:
        mask=np.zeros((H,W),bool); centers=[];radii=[]
        for r in knees:
            cx,cy=r['center']; rx,ry=r['radii']
            mask|=((X-cx)/(1.61*rx))**2+((Y-cy+.08*ry)/(1.42*ry))**2<1
            centers.append((cx,cy));radii.append((rx,ry))
        cx,cy=np.mean(centers,axis=0);rx,ry=np.mean(radii,axis=0)
        span=np.ptp([a[0] for a in centers])
        width=max(span+5.9*rx,7.2*rx)
        box=local_box(W,H,cx,cy-ry,width,max(6.3*ry,width*.66))
        passes.append(('knee',mask,box,knees))
    for r in regions:
        if r['part']!='bodice':continue
        x,y,ex,ey=r['box']; bw,bh=ex-x,ey-y
        mask=np.zeros((H,W),np.uint8);mask[y:ey,x:ex]=changed[y:ey,x:ex]
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))
        # Never expand above the observed garment into a nearby chin.
        mask=cv2.dilate(mask,np.ones((3,3),np.uint8));mask[:y]=0
        box=local_box(W,H,(ex+x)/2,(ey+y)/2+bh*.10,bw*2.07,bh*2.10)
        passes.append(('bodice',mask.astype(bool),box,[r]))
    return passes


def checked_composite(src,patch,mask,box,part,regions):
    x,y,r,b=box
    if mask[y:b,x:r].sum()!=mask.sum():return None
    srcarr=np.asarray(src); local=srcarr[y:b,x:r]; m=mask[y:b,x:r]; H,W=m.shape
    alpha=np.clip(cv2.distanceTransform(np.pad(m.astype('uint8'),1),cv2.DIST_L2,5)[1:-1,1:-1]/max(3.,min(H,W)*.018),0,1)[:,:,None]
    layer=np.rint(local*(1-alpha)+np.asarray(patch)*alpha).clip(0,255).astype('uint8')
    gray=cv2.cvtColor(layer,cv2.COLOR_RGB2GRAY)
    if part=='knee':
        for reg in regions:
            cx,cy=reg['center'];rx,ry=reg['radii'];Y,X=np.ogrid[y:b,x:r]
            roi=((X-cx)/rx)**2+((Y-cy)/ry)**2<.88
            dark=float((gray[roi]<reg['darkThreshold']).mean())
            if dark>max(.005,reg['darkFraction']*.36):return None
            if 'referenceHue' in reg:
                from hq_body_repair import reference_mark
                dyed=float(reference_mark(layer,reg['referenceHue'],reg['minSaturation'])[roi].mean())
                if dyed>reg['colorFraction']*.27:return None
                reg['remainingColorFraction']=round(dyed,4)
            reg['remainingDarkFraction']=round(dark,4)
    else:
        if (gray[m]<118).mean()<.64 or ((gray[m]>135)&(np.ptp(layer[m],axis=1)<25)).mean()>.20:return None
    result=src.copy();result.paste(Image.fromarray(layer),box[:2]);return result


def render(photo,guide,regions,garment,task,config):
    import torch
    from diffusers import EulerDiscreteScheduler, StableDiffusionInpaintPipeline
    from identity_pipeline import configure_cuda, load_identity_pipe, extract_clip_features
    from hq_tryon_conditioning import load_adapter
    from hq_body_repair import isolated_top
    def file_sha(path):
        with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    if file_sha(config['checkpoint'])!=task['checkpointSha256'] or file_sha(task['adapterPath'])!=task['adapterSha256']:
        raise ValueError('HQ 修整模型与生成时的绑定不一致')
    configure_cuda()
    (x,y,w,h),_,_=isolated_top(np.asarray(garment))
    gw,gh=garment.size
    top=garment.crop((int(gw*x),int(gh*y),int(gw*(x+w)),int(gh*(y+h))))
    pos,neg=extract_clip_features(config,ImageOps.pad(top,(224,224),color='white'))
    embeds=torch.cat([neg,pos],dim=0).unsqueeze(1)
    base=load_identity_pipe(config);pipe=StableDiffusionInpaintPipeline.from_pipe(base,torch_dtype=None);del base
    pipe.scheduler=EulerDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.load_ip_adapter([load_adapter(task['adapterPath'])],subfolder=[''],weight_name=['garment.bin'],image_encoder_folder=None,local_files_only=True)
    pipe.vae.enable_slicing();pipe.vae.enable_tiling();pipe.enable_sequential_cpu_offload(device='cuda');pipe.set_progress_bar_config(disable=True)
    result=photo.copy();accepted=[];rejected=[];forward_records=[]
    approved=np.zeros((photo.height,photo.width),bool)
    for region in regions:
        if region['method'] in DIRECT:
            # Sparse strokes have measured skin on both sides: preserve the
            # existing leg contour instead of re-synthesizing the whole joint.
            box=tuple(region['box']);x,y,r,b=box;cx,cy=region['center'];rx,ry=region['radii']
            Y,X=np.ogrid[y:b,x:r]
            u=(X-cx)/rx;v=(Y-cy)/ry
            support=((u/1.84)**2+((v+.04)/1.71)**2<1) if region['method']=='paired-textile-imprint' else (u*u+v*v<1.80)
            approved[y:b,x:r]|=support
            result.paste(guide.crop(box),box[:2],Image.fromarray(support.astype('uint8')*255));accepted.append(region)
    for part,mask,box,entries in build_masks(photo,guide,regions):
        garment_pass=part=='bodice';strength=.49 if garment_pass else .69; scale=.93 if garment_pass else 0.
        cond=embeds if garment_pass else torch.zeros_like(embeds)
        pipe.set_ip_adapter_scale(scale)
        prompt=('fashion product photograph, fitted black embroidered lace halter bra, two separate soft scalloped fabric cups, detailed black floral mesh, realistic studio light, preserve garment coverage' if garment_pass else
            'close-up studio fashion photograph of the lower body of a kneeling adult, two natural knees bent on a pale studio floor, kneecaps continuously connected to thighs, gently shaded skin and subtle creases, realistic anatomy, photographic light')
        negative=('grey or white hard cups, plate, armor, metal, plastic, extra straps, exposed chest, text' if garment_pass else
            'face, eye, hair, head, mouth, fingers, ribbons, mechanical hinge, printed marks, knee pads, straps, circles, disks, additional legs, watermark')
        m=Image.fromarray(mask.astype('uint8')*255).crop(box);init=guide.crop(box);seen=0
        def observe(mod,args,kwargs):
            nonlocal seen
            if kwargs.get('down_block_additional_residuals') is not None or kwargs.get('mid_block_additional_residual') is not None:
                raise ValueError('Unexpected depth conditioning in localized repair')
            seen+=1
        hook=pipe.unet.register_forward_pre_hook(observe,with_kwargs=True)
        try:
            with torch.inference_mode():
                patch=pipe(prompt=prompt,negative_prompt=negative,image=init,mask_image=m,width=init.width,height=init.height,
                           num_inference_steps=30 if garment_pass else 28,strength=strength,guidance_scale=5.5,
                           generator=torch.Generator(device='cpu').manual_seed(task['seed']),ip_adapter_image_embeds=[cond]).images[0]
        finally:hook.remove()
        if seen<10:raise ValueError('Insufficient localized denoising steps')
        updated=checked_composite(result,patch,mask,box,part,entries)
        forward_records.append({'part':part,'crop':list(box),'observedForwards':seen,'garmentScale':scale,'denoise':strength,
                                'poseControl':False,'faceAdapter':False,'accepted':updated is not None})
        if updated is None:rejected.extend(e['part'] for e in entries)
        else:result=updated;accepted.extend(entries);approved|=mask
    if np.any(np.asarray(result)[~approved]!=np.asarray(photo)[~approved]):
        raise ValueError('Repair changed pixels outside the accepted support')
    return result,accepted,rejected,forward_records
