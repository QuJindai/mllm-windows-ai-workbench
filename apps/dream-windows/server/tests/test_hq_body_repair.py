"""Recognise a translated, synthetic imprint without private photographs or ID/coordinate fixtures."""
import numpy as np
import pytest
cv2 = pytest.importorskip('cv2')
from PIL import Image, ImageDraw
from hq_body_repair import restore


def scene(mark, shift=0, armour=False, one=False, wrong_colour=False):
    size=(320,448)
    pose=Image.new('RGB',size,'white');lines=ImageDraw.Draw(pose)
    lines.ellipse((125,24,177,90),outline='black',width=3)
    lines.line((151,90,151,200),fill='black',width=3)
    depth=Image.new('L',size,35);dep=ImageDraw.Draw(depth)
    src=Image.new('RGB',size,(205,161,139));ink=ImageDraw.Draw(src)
    for cx,cy in [(85+shift,345-shift//3),(215+shift,346-shift//3)]:
        b=(cx-24,cy-29,cx+24,cy+29)
        lines.ellipse(b,outline='black',width=2);dep.ellipse(b,fill=246)
        if mark=='dense':ink.ellipse(b,fill=(41,33,30))
        elif mark=='colour' and (not one or cx<150):
            ink.arc(b,175,360,fill=(88,65,55),width=1)
            ink.chord((cx-23,cy-27,cx+23,cy+29),18,160,fill=(181,32,39))
        elif mark=='line':
            ink.ellipse(b,outline=(70,44,40),width=2)
            ink.line((cx,cy-28,cx,cy),fill=(55,39,34),width=3)
    garment=Image.new('RGB',(128,192),(195,194,192));g=ImageDraw.Draw(garment)
    if armour:g.rectangle((20,9,104,178),fill=(44,40,39))
    else:
        g.rectangle((38,9,84,49),fill=((36,49,178) if wrong_colour else (181,32,39)) if mark=='colour' else (44,40,38));g.rectangle((39,75,82,181),fill=(39,37,35))
    return src,depth,pose,garment


@pytest.mark.parametrize('mark',['line','dense'])
@pytest.mark.parametrize('offset',[0,19])
def test_only_registered_observed_artifacts_change(mark,offset):
    src,z,pose,garment=scene(mark,offset)
    repaired,mask,r=restore(src,z,pose,garment)
    assert [p['part'] for p in r['regions']]==['knee','knee']
    before=np.asarray(src);after=np.asarray(repaired);changed=np.any(before!=after,2)
    assert np.array_equal(np.array(mask)>0,changed)
    assert not changed[:275].any() and np.count_nonzero(changed)>100
    assert all(p['remainingDarkFraction']<p['darkFraction']*.4 for p in r['regions'])


@pytest.mark.parametrize('mark,armour',[(None,False),('line',True),('dense',True)])
def test_depth_alone_and_outfits_with_leg_armour_do_not_trigger(mark,armour):
    src,z,pose,garment=scene(mark,armour=armour)
    photo,mask,r=restore(src,z,pose,garment)
    assert r['state']=='unchanged' and not np.any(mask) and np.array_equal(photo,src)


@pytest.mark.parametrize('one,wrong,expected',[(False,False,2),(True,False,0),(False,True,0)])
def test_coloured_imprints_require_symmetric_shape_and_matching_garment(one,wrong,expected):
    src,z,pose,g=scene('colour',one=one,wrong_colour=wrong)
    _,_,r=restore(src,z,pose,g)
    assert len(r['regions'])==expected
    assert all(p['method']=='paired-textile-imprint' for p in r['regions'])


def test_misaligned_input_dimensions_cannot_be_used():
    src,z,p,g=scene('dense')
    with pytest.raises(ValueError,match='dimensions'):restore(src,z.resize((160,224)),p,g)
