from sqlalchemy import select
from fastapi import HTTPException
from .models import Stratum,Interpretation,SampleInterval,MissingInterval,CoreBox
from .common import hole,get,pack,audit,interval,overlaps
from .box_service import segments,phys_len,offset_of


def locate(s,h,p,require_confirmed):
    # 落单留实际箱位：区间须整体落在同一已登记芯盒内，按实际有芯长度换算；
    # 倒放箱自箱尾量起。破坏性切样还须该箱顺倒已核定。
    hits=[b for b in s.scalars(select(CoreBox).where(CoreBox.borehole_id==h.id))if b.start_m<=p.start_m+1e-9 and p.end_m<=b.end_m+1e-9]
    if not hits:
        if require_confirmed:raise HTTPException(409,'取样区间须落在本孔已登记的芯盒内，先登记芯盒')
        return None
    box=hits[0]
    if require_confirmed and box.state!='confirmed':raise HTTPException(409,'芯盒顺倒尚未核定，纳入核查的芯盒核定后才能切样')
    segs=segments(box.start_m,box.end_m,s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)).all())
    length=phys_len(segs);o1=offset_of(p.start_m,segs);o2=offset_of(p.end_m,segs)
    if box.orientation=='reversed':f,t=length-o2,length-o1
    else:f,t=o1,o2
    return box,f,t


def validate(s,h,p,exclude=None):
    interval(p.start_m,p.end_m,h.total_depth);st=get(s,Stratum,p.stratum_id);i=get(s,Interpretation,st.interpretation_id)
    if i.borehole_id!=h.id or i.state!='confirmed' or p.start_m<st.start_m or p.end_m>st.end_m:raise HTTPException(409,'取样须位于本孔同一已确认层段内')
    for m in s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)):
        if overlaps(p.start_m,p.end_m,m.start_m,m.end_m):raise HTTPException(409,'缺芯区间不可取样')
    active=[x for x in s.scalars(select(SampleInterval).where(SampleInterval.borehole_id==h.id,SampleInterval.state!='cancelled'))if x.id!=exclude]
    if p.destructive:
        if any(x.destructive and overlaps(x.start_m,x.end_m,p.start_m,p.end_m)for x in active):raise HTTPException(409,'破坏性切样区间与已有取样重叠')
        if sum(x.end_m-x.start_m for x in active if x.destructive)+p.end_m-p.start_m>h.cut_quota+1e-8:raise HTTPException(409,'切样累计长度超过本孔破坏性配额')


def _box_fields(s,h,p,require_confirmed):
    pos=locate(s,h,p,require_confirmed)
    if not pos:return {}
    box,f,t=pos
    return {'box_id':box.id,'box_from_m':round(f,4),'box_to_m':round(t,4),'box_orientation':box.orientation}


def create(s,p,u):
    # 回执丢失后重试：同一幂等键直接返回原切样单，不再校验、不再扣额。
    if p.request_key:
        old=s.scalar(select(SampleInterval).where(SampleInterval.request_key==p.request_key))
        if old:return pack(old)
    h=hole(s,p.borehole_id);validate(s,h,p)
    kw=p.model_dump();kw.update(_box_fields(s,h,p,p.destructive))
    x=SampleInterval(**kw);s.add(x);s.flush();audit(s,u,'申请切样 '+x.code);return pack(x)


def revise(s,id,p,u):
    ref=get(s,SampleInterval,id);h=hole(s,ref.borehole_id);x=get(s,SampleInterval,id,True)
    if x.state!='planned' or p.borehole_id!=h.id or p.code!=x.code:raise HTTPException(409,'仅未封签计划可修订，孔号和样号固定')
    if p.request_key and p.request_key!=x.request_key and s.scalar(select(SampleInterval.id).where(SampleInterval.request_key==p.request_key,SampleInterval.id!=id)):raise HTTPException(409,'幂等键已被其他切样单占用')
    validate(s,h,p,id)
    for k,v in p.model_dump().items():setattr(x,k,v)
    for k in('box_id','box_from_m','box_to_m','box_orientation'):setattr(x,k,None)
    for k,v in _box_fields(s,h,p,p.destructive).items():setattr(x,k,v)
    audit(s,u,'修订切样区间 '+x.code);return pack(x)


def cancel(s,id,u):
    ref=get(s,SampleInterval,id);hole(s,ref.borehole_id);x=get(s,SampleInterval,id,True)
    if x.state!='planned':raise HTTPException(409,'只有未封签计划可撤销释放配额')
    x.state='cancelled';audit(s,u,'撤销取样 '+x.code);return pack(x)
