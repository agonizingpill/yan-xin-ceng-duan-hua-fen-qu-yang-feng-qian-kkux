from sqlalchemy import select
from fastapi import HTTPException
from .models import CoreBox,BoxRemeasure,Reading,MissingInterval,SampleInterval
from .common import hole,get,pack,audit,now,interval,overlaps

# 复测三项物性与原测点的比对容差。深度容差小于测点间距/缺芯段长度，
# 才能区分“按实际有芯长度对应”与“跨过缺芯硬对应”。
DEPTH_TOL=.35
PROP_TOL=.15
MATCH_MIN=.75
PROPS=('density','susceptibility','velocity')


def segments(s,e,missing):
    # 芯盒[ s, e ]内实际有芯的连续段；缺芯段不含岩芯，物理箱内不占长度。
    out=[];cur=s
    for m in sorted((x for x in missing if x.end_m>s and x.start_m<e),key=lambda z:z.start_m):
        ms=max(m.start_m,s);me=min(m.end_m,e)
        if ms>cur+1e-9:out.append((cur,ms))
        cur=max(cur,me)
    if cur<e-1e-9:out.append((cur,e))
    return out


def phys_len(segs):return sum(b-a for a,b in segs)


def depth_at(p,segs):
    # 物理箱内偏移 p（自箱头计）→ 实际深度，跨过缺芯时跳过缺芯长度。
    acc=0
    for a,b in segs:
        length=b-a
        if p<=acc+length+1e-9:return a+(p-acc)
        acc+=length
    return segs[-1][1] if segs else None


def offset_of(d,segs):
    # 实际深度 d → 自箱头计的物理偏移（不含缺芯长度）。
    total=0
    for a,b in segs:
        if d<=a+1e-9:break
        total+=min(d,b)-a
    return total


def _match(depth,props,readings):
    best=None
    for r in readings:
        diff=abs(r['depth_m']-depth)
        if diff<=DEPTH_TOL and (best is None or diff<best[0]):best=(diff,r)
    if best is None:return None
    r=best[1]
    for k in PROPS:
        a=r[k];b=props[k]
        if abs(a-b)>PROP_TOL*max(abs(a),abs(b),1e-9):return None
    return r['depth_m']


def _score(remeasures,readings,mapper):
    matched=[];missed=[]
    for rm in remeasures:
        props={k:getattr(rm,k) for k in PROPS};p=rm.offset_m
        d=mapper(p);hit=_match(d,props,readings)
        if hit is not None:matched.append({'offset_m':p,'depth_m':round(d,4),'matched_depth_m':hit})
        else:missed.append({'offset_m':p,'depth_m':round(d,4)})
    total=len(remeasures)
    return {'matched':len(matched),'total':total,'ratio':round(len(matched)/total,4)if total else 0,
            'points':matched,'missed':missed}


def compare(s,box):
    readings=[pack(r)for r in s.scalars(select(Reading).where(Reading.borehole_id==box.borehole_id).order_by(Reading.depth_m))]
    missing=s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==box.borehole_id)).all()
    segs=segments(box.start_m,box.end_m,missing);length=phys_len(segs)
    remeasures=s.scalars(select(BoxRemeasure).where(BoxRemeasure.box_id==box.id).order_by(BoxRemeasure.offset_m)).all()
    # proper：按实际有芯长度对应，跨过缺芯时跳过缺芯长度。
    # naive：把缺芯长度也算作岩芯的线性对应；只在 proper 配不上、naive 配得上时，
    # 说明证据“跨过缺芯才配得上”，须留待核实。
    normal=_score(remeasures,readings,lambda p:depth_at(p,segs))
    reversed_=_score(remeasures,readings,lambda p:depth_at(length-p,segs))
    normal_naive=_score(remeasures,readings,lambda p:box.start_m+p)
    reversed_naive=_score(remeasures,readings,lambda p:box.end_m-p)
    ok=lambda r:r['total']>0 and r['ratio']>=MATCH_MIN
    spans_gap=len(segs)>1
    cross_only=(spans_gap and((ok(normal_naive)and not ok(normal))or(ok(reversed_naive)and not ok(reversed_))))
    if ok(normal)and ok(reversed_):decision,reason='pending','both_plausible'
    elif cross_only:decision,reason='pending','crosses_missing_core'
    elif ok(normal):decision,reason='normal','single_supported'
    elif ok(reversed_):decision,reason='reversed','single_supported'
    else:decision,reason='pending','insufficient'
    return {'decision':decision,'reason':reason,'spans_gap':spans_gap,'tolerance':{'depth_m':DEPTH_TOL,'relative':PROP_TOL},
            'box_length_m':round(length,4),'segments':[[a,b]for a,b in segs],'normal':normal,'reversed':reversed_,
            'normal_naive':normal_naive,'reversed_naive':reversed_naive,'computed_at':now()}


def _locked_orientation(s,box):
    # 已有未撤销切样引用该箱时，箱位以落单记录为准；改向会挪动已落单箱位。
    used={r.box_orientation for r in s.scalars(select(SampleInterval).where(SampleInterval.box_id==box.id,SampleInterval.state!='cancelled'))if r.box_orientation}
    return used.pop()if len(used)==1 else None


def _apply(s,box,basis,u,verb):
    locked=_locked_orientation(s,box)
    if basis['decision']in('normal','reversed'):
        auto=basis['decision']
        if locked and auto!=locked:
            basis['decision']='pending';basis['reason']='orientation_locked_by_sample'
            box.note='已有落单箱位，沿用原定位；改向留待人工核定'
            box.orientation=locked;box.state='pending'
        else:
            # 已核定且新证据仍支持同一朝向时保持核定；否则退回待核定重签。
            box.state='confirmed'if box.state=='confirmed'and box.orientation==auto else'resolved'
            box.orientation=auto
    else:
        if locked:
            box.orientation=locked
            box.note='已有落单箱位，沿用原定位；新证据未能定论，留待人工核定'
        box.state='pending'
    box.basis=basis
    s.flush();audit(s,u,verb+' '+box.code)


def create(s,p,u):
    h=hole(s,p.borehole_id);interval(p.start_m,p.end_m,h.total_depth)
    for x in s.scalars(select(CoreBox).where(CoreBox.borehole_id==h.id)):
        if overlaps(x.start_m,x.end_m,p.start_m,p.end_m):raise HTTPException(409,'芯盒区间不可重叠')
    x=CoreBox(**p.model_dump());s.add(x);s.flush();audit(s,u,'登记芯盒 '+x.code);return pack(x)


def resample(s,id,p,u):
    ref=get(s,CoreBox,id);hole(s,ref.borehole_id);x=get(s,CoreBox,id,True)
    segs=segments(x.start_m,x.end_m,s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==x.borehole_id)).all())
    if p.offset_m>phys_len(segs)+1e-6:raise HTTPException(409,'复测偏移超出芯盒实际有芯长度')
    if s.scalar(select(BoxRemeasure.id).where(BoxRemeasure.box_id==x.id,BoxRemeasure.offset_m==p.offset_m)):raise HTTPException(409,'该箱位已有复测记录，请直接重核')
    s.add(BoxRemeasure(box_id=x.id,offset_m=p.offset_m,density=p.density,susceptibility=p.susceptibility,velocity=p.velocity));s.flush()
    basis=compare(s,x);_apply(s,x,basis,u,'箱内复测并重核芯盒')
    return {'box':pack(x),'basis':x.basis}


def recheck(s,id,u):
    ref=get(s,CoreBox,id);hole(s,ref.borehole_id);x=get(s,CoreBox,id,True)
    if not s.scalar(select(BoxRemeasure.id).where(BoxRemeasure.box_id==x.id)):raise HTTPException(409,'尚无箱内复测记录，无法重核顺倒')
    basis=compare(s,x);_apply(s,x,basis,u,'重核芯盒顺倒')
    return {'box':pack(x),'basis':x.basis}


def confirm(s,id,p,u):
    ref=get(s,CoreBox,id);hole(s,ref.borehole_id);x=get(s,CoreBox,id,True)
    orient=p.orientation or x.orientation
    if orient not in('normal','reversed'):raise HTTPException(409,'须指定顺放或倒放才能核定')
    locked=_locked_orientation(s,x)
    if locked and orient!=locked:raise HTTPException(409,'已有落单切样占用箱位，改向会挪动已落单箱位，须沿用原定位')
    x.orientation=orient;x.state='confirmed';x.confirmed_by=u['email'];x.confirmed_at=now()
    if p.note:x.note=p.note
    basis=dict(x.basis or {});basis['confirmed_orientation']=orient;x.basis=basis
    audit(s,u,'核定芯盒 '+x.code+' 为'+('顺放'if orient=='normal'else'倒放'))
    return {'box':pack(x),'basis':x.basis}
