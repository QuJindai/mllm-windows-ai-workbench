"""Conservative, CPU-only correction of articulated mannequin imprints in paired-depth HQ photos.

Proposals come from the registered white mannequin. A proposal alone never authorizes
painting: the photograph and isolated garment must independently support the edit.
The caller owns the original; only a derivative and its actual changed-pixel mask are saved.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from hq_repair_version import VERSION, DIRECT


def kernel(radius):
    r = max(1, int(round(radius)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*r+1, 2*r+1))


def components(mask):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype('uint8'))
    return sorted(((s.tolist(), i) for i, s in enumerate(stats[1:n], 1)), key=lambda item: -item[0][4]), labels


def isolated_top(garment):
    # A disconnected dark bodice on a neutral catalogue background is distinguishable
    # from a dark full suit with intentional knee guards or a real pale chest panel.
    thumb = np.asarray(Image.fromarray(garment).resize((256, 384), Image.Resampling.BILINEAR))
    lab = cv2.cvtColor(thumb, cv2.COLOR_RGB2LAB).astype('float32')
    bg = np.median(np.concatenate((lab[:, :9], lab[:, -9:]), axis=1), axis=1)
    parts, labels = components(np.linalg.norm(lab-bg[:, None], axis=2) > 27)
    parts = [(b, i) for b, i in parts if b[4] >= 300]
    tops = [(b, i) for b, i in parts if b[1] < 85 and 25 < b[3] < 155 and b[2] >= 40
            and b[1]+b[3] < 175 and any(q[1] > b[1]+b[3]+3 and q[3] > 55 for q, _ in parts)]
    if len(tops) != 1:
        return None
    (x, y, w, h, _), i = tops[0]
    # Ignore straps when measuring/mapping the actual textile.
    yy = np.arange(384)[:, None]
    cloth = thumb[(labels == i) & (yy > y+h*.54) & (yy < y+h*.94)]
    if not len(cloth):
        return None
    return (x/256, y/384, w/256, h/384), np.median(cloth, axis=0), float((cloth.mean(1) < 108).mean())


def proposals(pose, size, depth):
    w, h = size
    view = ImageOps.pad(pose.convert('L'), size, method=Image.Resampling.BILINEAR, color=255)
    contours, _ = cv2.findContours((np.asarray(view) > 160).astype('uint8'), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    yy, xx = np.where(np.asarray(view) < 125)
    if len(yy) < 50:
        return [], [], None
    top, bottom = int(yy.min()), int(yy.max())
    height = bottom-top
    joints, torsos = [], []
    for c in contours:
        area = cv2.contourArea(c)
        if len(c) < 5 or not .0015*w*h < area < .13*w*h:
            continue
        (cx, cy), (a, b), _ = cv2.fitEllipse(c)
        x, y, bw, bh = cv2.boundingRect(c)
        if min(a, b) <= 0:
            continue
        fill = area/(np.pi*a*b/4)
        if (.68 < (cy-top)/max(height, 1) < 1 and .94 < fill < 1.065 and a/b > .65
                and .092*height < min(a,b) < .28*height):
            mask = np.zeros(depth.shape, np.uint8)
            cv2.drawContours(mask, [c], -1, 1, -1)
            z = float(np.median(depth[mask != 0]))
            if z > 168:
                # A detached ink outline can yield an inner and outer contour for
                # one joint. Collapse coincident fits, never two adjacent knees.
                if not any(abs(cx-ox)<.10*bw and abs(cy-oy)<.10*bh and .76<ow/bw<1.31 for ox,oy,ow,_,_ in joints):
                    joints.append((cx, cy, bw, bh, z))
        if (top+.13*height < y < top+.44*height and .12*height < bw < .49*height
                and bw > bh*1.24 and bh < .25*height and area/(bw*bh) > .38):
            torsos.append(c)
    pairs = []
    for a, b in itertools.combinations(sorted(joints), 2):
        if (.14*height < b[0]-a[0] < .68*height and abs(a[1]-b[1]) < .12*height
                and min(a[2], b[2]) > .59*max(a[2], b[2])):
            pairs.append([a, b])
    # Ambiguous anatomy, multiple people or too-small joints: abstain.
    return pairs[0] if len(pairs) == 1 else [], torsos, height


def skin_pixels(rgb):
    r,g,b = np.moveaxis(rgb.astype('float32'), -1, 0)
    return (r-g > 8) & (g-b > 3) & (r > 100) & (r-g < 90)


def harmonic_fill(rgb,mask):
    # Solve four-neighbour interpolation against measured boundary pixels.
    from scipy.sparse import csr_matrix
    from scipy.sparse.linalg import spsolve
    y,x=np.nonzero(mask);idx=np.full(mask.shape,-1,np.int32)
    i=np.arange(len(y));idx[y,x]=i
    rows=[i];cols=[i];weights=[np.full(len(y),4.)];rhs=np.zeros((len(y),3))
    for dy,dx in [(1,0),(-1,0),(0,1),(0,-1)]:
        ny=np.clip(y+dy,0,mask.shape[0]-1);nx=np.clip(x+dx,0,mask.shape[1]-1)
        ref=idx[ny,nx];inside=ref>=0
        rows.append(i[inside]);cols.append(ref[inside]);weights.append(-np.ones(inside.sum()))
        rhs[~inside]+=rgb[ny[~inside],nx[~inside]]
    mat=csr_matrix((np.concatenate(weights),(np.concatenate(rows),np.concatenate(cols))),shape=(len(y),len(y)))
    result=rgb.copy();result[y,x]=np.rint(spsolve(mat,rhs)).clip(0,255).astype('uint8')
    return result


def reference_mark(rgb, hue, saturation):
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    delta=np.abs(hsv[:,:,0].astype(int)-hue)
    return (np.minimum(delta,180-delta)<8) & (hsv[:,:,1]>saturation) & (hsv[:,:,2]>48)


def clear_print(q,gray,u,v,rx,rad,dyed,hue,dark_threshold):
    """Continue measured skin under transferred textile; keep the actual contact silhouette."""
    from scipy.ndimage import distance_transform_edt
    extent=(u/1.58)**2+((v+.04)/1.44)**2<1
    ink=cv2.morphologyEx((dyed&extent).astype('uint8'),cv2.MORPH_CLOSE,kernel(rx*.055))
    parts,labels=components(ink)
    opaque=np.isin(labels,[i for (_,_,_,_,size),i in parts if size>max(18,rx*.5)])
    if not opaque.any():return None
    density=cv2.GaussianBlur(skin_pixels(q).astype('float32'),(0,0),rx*.13)
    ridges=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,kernel(rx*.16))
    strokes=((ridges>8)&(density>.58)&extent) | ((gray<dark_threshold+12)&(density>.38)&(rad<1.1))
    strokes=cv2.dilate(strokes.astype('uint8'),kernel(rx*.068)).astype(bool)
    mask=cv2.dilate(opaque.astype('uint8'),kernel(rx*.145)).astype(bool)
    remove=strokes & ~(cv2.dilate(opaque.astype('uint8'),kernel(rx*.02)).astype(bool))
    clean=harmonic_fill(q,remove) if remove.any() else q
    f=q.astype('float32');r,g,b=np.moveaxis(f,-1,0)
    good=skin_pixels(q)&(~reference_mark(q,hue,85))&(~strokes)&(g-b>.20*(r-g))
    if np.count_nonzero(good)<100:return None
    iy,ix=distance_transform_edt(~good,return_distances=False,return_indices=True)
    skin=harmonic_fill(q[iy,ix],mask)
    interior=cv2.distanceTransform(mask.astype('uint8'),cv2.DIST_L2,5)
    shade=1-.068*np.clip(v-.48,0,1)*np.clip(interior/12,0,1)
    matte=cv2.GaussianBlur(cv2.dilate(opaque.astype('uint8'),kernel(2)).astype('float32'),(0,0),.6)
    skin_matte=np.clip((g-b-4)/11,0,1)*np.clip((r-g-8)/12,0,1)
    alpha=(np.clip(interior/6,0,1)*np.maximum(matte,skin_matte))[:,:,None]
    base=q.copy();upper=remove&(v<.43)&(density>.51);base[upper]=clean[upper]
    return np.rint(base*(1-alpha)+skin*shade[:,:,None]*alpha).clip(0,255).astype('uint8')


def knee(source, depth, joint, garment_color):
    h,w = depth.shape
    cx,cy,bw,bh,z = joint
    rx,ry = bw/2,bh/2
    x0,x1 = max(0, int(cx-2.15*rx)), min(w, int(cx+2.15*rx)+1)
    y0,y1 = max(0, int(cy-2.6*ry)), min(h, int(cy+1.75*ry)+1)
    q = source[y0:y1, x0:x1]; y,x = np.mgrid[y0:y1,x0:x1].astype('float32')
    u,v = (x-cx)/rx,(y-cy)/ry
    rad = u*u+v*v
    skin = skin_pixels(q)
    above = (abs(u)<.72) & (v< -1.2) & (v> -2)
    info = {'part':'knee','center':[round(cx), round(cy)],'box':[x0,y0,x1,y1],'radii':[round(rx,2),round(ry,2)]}
    if above.sum()<40 or skin[above].mean()<.79:
        return None
    gray = cv2.cvtColor(q,cv2.COLOR_RGB2GRAY)
    typical = float(np.median(gray[above & skin]))
    info['darkThreshold']=round(min(90.,typical*.54),2)
    dark = gray < min(90., typical*.54)
    inside = rad < .88
    ink = float(dark[inside].mean())
    # The rim can be a fine dark thread or the edge of a filled "hair bun".
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel(min(rx,ry)*.15)).astype(float)
    ring = (rad>.68) & (rad<1.39)
    theta = np.arctan2(v,u)
    edges=blackhat>24
    if ink>.29:
        edges |= cv2.Canny(gray,45,100)>0
    arcs = sum(bool(np.any(edges & ring & (theta >= t) & (theta < t+np.pi/6)))
               for t in np.linspace(-np.pi,np.pi,12,endpoint=False))
    reference=cv2.cvtColor(np.uint8(garment_color).reshape(1,1,3),cv2.COLOR_RGB2HSV)[0,0]
    hue=int(reference[0]); sat=max(126,int(reference[1]*.88))
    dyed=reference_mark(q,hue,sat)
    color_fraction=float(dyed[inside].mean())
    colored_sectors=sum(np.any(dyed & ring & (theta>=t)&(theta<t+np.pi/6)) for t in np.linspace(-np.pi,np.pi,12,endpoint=False))
    extension=float(dyed[(rad>1.38)&(rad<2.30)].mean())
    # A garter running across a whole leg is not a compact, lower-rim imprint.
    colored=(reference[1]>105 and .055<color_fraction<.64 and colored_sectors>=3 and
             extension<color_fraction*.60 and dyed[(abs(u)>1.15)&(abs(v)<.78)&(rad<2.65)].mean()<.08 and np.median(v[inside&dyed])>.21 and dyed[above].mean()<.028)
    info.update(darkFraction=round(ink,4),rimSectors=int(arcs))
    if colored:info.update(referenceHue=hue,minSaturation=sat,colorFraction=round(color_fraction,4))
    if not (colored or (ink>.29 and arcs>=4) or (.012<ink<.25 and arcs>=4)):
        return None
    if colored:
        fixed=clear_print(q,gray,u,v,rx,rad,dyed,hue,info['darkThreshold'])
        if fixed is None:return None
        alpha=np.any(fixed!=q,axis=2).astype('float32')
        method='paired-textile-imprint'
    elif ink>.29:
        # Continue the photographed thigh's light, not the embossed manikin disk.
        d = depth[y0:y1,x0:x1].astype('float32')
        bg = np.minimum(np.median(depth[y0:y1,:5],axis=1),np.median(depth[y0:y1,-5:],axis=1))[:,None]
        fg = cv2.GaussianBlur(np.clip((d-bg-8)/25,0,1),(0,0),1.3)
        donor = q[np.clip(np.rint(cy-1.59*ry-y0+(y-cy)*.27).astype(int),0,q.shape[0]-1),
                  np.clip(np.rint(cx-x0+(x-cx)*.52).astype(int),0,q.shape[1]-1)].astype('float32')
        fallback=np.median(q[above & skin],axis=0)
        donor=np.where(skin_pixels(donor)[:,:,None],donor,fallback)
        donor=cv2.GaussianBlur(donor,(0,0),1.3)
        # A broad gradual falloff at the underside avoids a new circular boundary.
        shade=1-.092*np.clip(v+.07,0,1)-.036*np.clip(abs(u)-.15,0,1)
        donor*=shade[:,:,None]
        outside=(fg<.1) & (rad>1.52)
        sigma=max(3.,rx*.27)
        weights=cv2.GaussianBlur(outside.astype('float32'),(0,0),sigma)
        floor=cv2.GaussianBlur(q.astype('float32')*outside[:,:,None],(0,0),sigma)/np.maximum(.0001,weights[:,:,None])
        floor=np.where(weights[:,:,None]>.007,floor,np.median(source[y0:y1,:12],axis=1)[:,None,:])
        fixed=donor*fg[:,:,None]+floor*(1-fg[:,:,None])
        # Include thin straps over the top of the knee but exclude the foot beside it.
        boundary=(u/1.66)**2+((v+.10)/1.35)**2
        alpha=np.clip((1-boundary)/.24,0,1)
        method='adjacent-skin-and-silhouette'
    else:
        # Narrow marks: keep real skin, floor and lighting on both sides of each line.
        density=cv2.GaussianBlur(skin.astype('float32'),(0,0),rx*.13)
        suspect=((blackhat>9)&(density>.66)&(rad<1.54)) | ((gray<info['darkThreshold']+12)&(density>.38)&(rad<.98))
        parts, ids=components(suspect)
        keep=np.zeros_like(dark)
        for (bx,by,bww,bhh,count),i in parts:
            blob=ids==i
            if count>max(8,rx*.36) and (np.any(blob&dark) or np.count_nonzero(blob&ring&(blackhat>20))>rx*.17):
                keep |= blob
        repair=cv2.dilate(keep.astype('uint8'),kernel(max(2,rx*.058)))
        if not repair.any() or repair[inside].mean()>.57:
            return None
        fixed=harmonic_fill(q,repair.astype(bool))
        alpha=repair.astype('float32')
        method='local-line-interpolation'
    new=np.uint8(np.clip(np.rint(q*(1-alpha[:,:,None])+fixed*alpha[:,:,None]),0,255))
    residual=float((cv2.cvtColor(new,cv2.COLOR_RGB2GRAY)[inside]<min(90.,typical*.54)).mean())
    if residual>max(.002,ink*.39) or ((ink>.29 or colored) and skin_pixels(new)[inside].mean()<.74):
        return None
    if colored:
        after=float(reference_mark(new,hue,sat)[inside].mean())
        if after>color_fraction*.27:return None
        info['remainingColorFraction']=round(after,4)
    info.update(method=method,remainingDarkFraction=round(residual,4))
    return (x0,y0,x1,y1),new,info


def bodice(source,garment,top,torsos,height):
    (sx,sy,sw,sh),color,dark=top
    if dark<.74 or np.ptp(color)>31:
        return None
    h,w=source.shape[:2]
    gray=cv2.cvtColor(source,cv2.COLOR_RGB2GRAY)
    cold=(np.ptp(source,axis=2)<28)&(gray>115)&(gray<241)
    candidates=[]
    for c in torsos:
        outline=np.zeros((h,w),np.uint8);cv2.drawContours(outline,[c],-1,1,-1)
        if cold[outline!=0].mean()<.67:
            continue
        search=cv2.dilate(outline,kernel(height*.012))
        comps,idx=components((search!=0)&cold)
        if not comps: continue
        b,i=comps[0]
        shell=idx==i
        if np.count_nonzero(shell & (outline!=0))<.62*outline.sum():continue
        candidates.append((b,shell))
    if len(candidates)!=1:return None
    (x,y,bw,bh,area),shell=candidates[0]
    if bw<40 or bh<24:return None
    # Use both observed lobes. The thin dark seam between the two is retained.
    core=cv2.distanceTransform(shell.astype('uint8'),cv2.DIST_L2,5)
    peaks=[]
    for lo,hi in [(x,int(x+bw*.55)),(int(x+bw*.55),x+bw)]:
        _,v,_,(px,py)=cv2.minMaxLoc(core[y:y+bh,lo:hi])
        if v<min(bw,bh)*.095:return None
        peaks.append(np.array([lo+px,y+py],dtype='float32'))
    if peaks[1][0]-peaks[0][0]<bw*.28:return None
    Y,X=np.mgrid[y:y+bh,x:x+bw].astype('float32')
    g=np.asarray(garment);gh,gw=g.shape[:2]; q=source[y:y+bh,x:x+bw]
    shell=shell[y:y+bh,x:x+bw]
    # A watershed with the real dark seam as a barrier separates projected cups.
    seeds=np.zeros((bh,bw),np.int32);seeds[~shell]=1
    for n,(px,py) in enumerate(peaks,2):
        cv2.circle(seeds,(int(px-x),int(py-y)),max(2,round(core[int(py),int(px)]*.36)),n,-1)
    labels=cv2.watershed(cv2.cvtColor(q.copy(),cv2.COLOR_RGB2BGR),seeds)
    # Recover patterned edges the watershed excluded, without pulling in the
    # smooth catalogue backdrop above a cup or crossing into the face.
    distance=[cv2.distanceTransform((labels!=i).astype('uint8'),cv2.DIST_L2,5) for i in (2,3)]
    lum=gray[y:y+bh,x:x+bw].astype('float32')
    detail=cv2.GaussianBlur(np.abs(lum-cv2.GaussianBlur(lum,(0,0),1.2)),(0,0),2)
    which=distance[1]<distance[0]
    extended=shell & (np.minimum(*distance)<bw*.145) & (detail>.80) & (Y>np.where(which,peaks[1][1],peaks[0][1]))
    extended=cv2.morphologyEx(extended.astype('uint8'),cv2.MORPH_CLOSE,kernel(bw*.012)).astype(bool) & shell
    fixed=q.copy();applied=np.zeros((bh,bw),bool)
    for n in (0,1):
        target=((labels==n+2) | (extended & (which==bool(n)))) & shell & (labels!=3-n)
        if target.sum()<area*.12:return None
        # Warp rows of the *original garment*, retaining its textile pattern and opacity.
        by,bx=target.nonzero(); lo,hi=by.min(),by.max()
        tx0,tx1=(0.,.50) if n==0 else (.50,1.)
        mx=np.zeros((bh,bw),'float32');my=mx.copy()
        for row in range(lo,hi+1):
            pixels=np.where(target[row])[0]
            if not len(pixels):continue
            v=(row-lo)/max(1,hi-lo)
            # Follow reference cup shape: narrow tip, widening lower body.
            outer=.11+.10*(1-v); inner=.06+.46*(1-v)**1.9
            l,r=(outer,1-inner) if n==0 else (inner,1-outer)
            u=(pixels-pixels.min())/max(1,float(np.ptp(pixels)))
            mx[row,pixels]=(sx+sw*(tx0+(tx1-tx0)*(l+u*(r-l))))*gw
            my[row,pixels]=(sy+sh*(.411+v*.525))*gh
        tex=cv2.remap(g,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype('float32')
        intensity=tex.mean(2)
        # Catalogue backdrop through open lace should take on the local fabric underlay.
        bg=np.median(g[:,:max(2,gw//35)],axis=(0,1)).mean()
        under=q.astype('float32')*.38
        mix=np.clip((bg-7-intensity)/45,0,1)[:,:,None]
        material=tex*mix+under*(1-mix)
        # Restore very soft illumination from the *photographed* cup without its embossed outline.
        light=cv2.GaussianBlur(gray[y:y+bh,x:x+bw].astype('float32'),(0,0),max(3.,bw*.035))
        material*=np.clip(light/np.median(light[target]),.77,1.15)[:,:,None]
        fixed[target]=np.uint8(np.clip(np.rint(material[target]),0,255))
        applied|=target
    cover=applied.sum()/area
    if cover<.77:return None
    # Feather inwards only; a photo pixel outside the recognized fabric cannot change.
    dist=cv2.distanceTransform(np.pad(applied.astype('uint8'),1),cv2.DIST_L2,5)[1:-1,1:-1]
    alpha=np.clip(dist/max(1.4,bw*.009),0,1)[:,:,None]
    fixed=np.uint8(np.clip(np.rint(q*(1-alpha)+fixed*alpha),0,255))
    if (fixed[applied].mean(1)<118).mean()<.68:return None
    return (x,y,x+bw,y+bh),fixed,{'part':'bodice','box':[x,y,x+bw,y+bh],'method':'registered-original-textile',
            'referenceDarkFraction':round(dark,4),'shellCoverage':round(float(cover),4)}


def restore(photo, depth, pose, garment):
    src=np.array(photo.convert('RGB')); z=np.array(depth.convert('L'))
    if z.shape!=src.shape[:2] or src.size>3*1152*1152:
        raise ValueError('invalid registered control dimensions')
    top=isolated_top(np.array(garment.convert('RGB')))
    pair,torsos,height=proposals(pose,photo.size,z)
    out=src.copy();regions=[]
    # Deliberately abstain on standing boots, occluded legs and unrecognised products.
    if top and pair:
        edits=[knee(src,z,j,top[1]) for j in pair]
        dyed=[i for i,e in enumerate(edits) if e is not None and e[2]['method']=='paired-textile-imprint']
        if len(dyed)==1:edits[dyed[0]]=None  # Unpaired colour may be an intentional accessory.
        edits.append(bodice(src,np.array(garment.convert('RGB')),top,torsos,height))
        for edit in edits:
            if edit is not None:
                (x,y,r,b),patch,evidence=edit
                local=src[y:b,x:r]; changed_here=np.any(local!=patch,axis=2)
                out[y:b,x:r][changed_here]=patch[changed_here]
                regions.append(evidence)
    changed=np.any(out!=src,axis=2)
    report={'version':VERSION,'state':'applied' if regions else 'unchanged','regions':regions,
            'changedPixels':int(changed.sum()),'eligibleKnees':len(pair),'isolatedGarment':bool(top)}
    return Image.fromarray(out),Image.fromarray(changed.astype('uint8')*255),report


def run(manifest, config):
    """Worker takes only a server-created local manifest (never a client path)."""
    cv2.setNumThreads(2)
    task=json.loads(manifest.read_text(encoding='utf-8'))
    images={}
    import io
    for role in ('photo','depth','pose','garment'):
        item=task[role]; data=Path(item['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('source digest mismatch: '+role)
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height>20_000_000 or image.n_frames!=1:raise ValueError('invalid source image')
            images[role]=image.convert('RGB')
    result,mask,report=restore(**images)
    if any(r['method'] not in DIRECT for r in report['regions']):
        from hq_body_render import render
        from identity_models import resolve_identity_model, DEFAULT_MODEL_ID
        result,regions,rejected,passes=render(images['photo'],result,report['regions'],images['garment'],task,resolve_identity_model(config,DEFAULT_MODEL_ID))
        changed=np.any(np.asarray(result)!=np.asarray(images['photo']),axis=2)
        mask=Image.fromarray(changed.astype('uint8')*255)
        report.update(regions=regions,rejected=rejected,passes=passes,changedPixels=int(changed.sum()),
                      state=('partial' if rejected else 'applied') if regions else 'rejected',
                      seed=task['seed'],checkpointSha256=task['checkpointSha256'],adapterSha256=task['adapterSha256'])
    elif report['regions']:
        report.update(passes=[],seed=task['seed'])
    report['sourceHashes']={k:task[k]['sha256'] for k in images}
    if report['state'] in {'applied','partial'}:
        for im,name,key in ((result,'result.png','sha256'),(mask,'mask.png','maskSha256')):
            tmp=manifest.parent/(name+'.tmp');im.save(tmp,format='PNG');tmp.replace(manifest.parent/name)
            report[key]=hashlib.sha256((manifest.parent/name).read_bytes()).hexdigest()
    tmp=manifest.parent/'report.tmp';tmp.write_text(json.dumps(report,allow_nan=False),encoding='utf-8')
    tmp.replace(manifest.parent/'report.json')

    return report
