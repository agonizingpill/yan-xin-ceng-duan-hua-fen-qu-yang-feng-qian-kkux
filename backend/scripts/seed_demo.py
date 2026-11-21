import json
import numpy as np
from sqlalchemy import select
from src.database import Session,Base,engine
from src.models import User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision,CoreBox,BoxRemeasure
from src.security import password_hash
from src import box_service

def seed():
    Base.metadata.create_all(engine)
    with Session.begin()as s:
        for role in ['operator','supervisor','viewer']:
            if not s.scalar(select(User).where(User.email==role+'@liheng.local')):s.add(User(email=role+'@liheng.local',password=password_hash('Core2026!'),role=role))
        h=s.scalar(select(Borehole).where(Borehole.code=='BH-31'))
        if not h:
            h=Borehole(code='BH-31',site='砾衡青石沟东线 / ZK-31',total_depth=36,cut_quota=6);s.add(h);s.flush()
            rng=np.random.default_rng(42)
            for code,start,end,recovered in [('R01',0,18,17),('R02',18,36,18)]:
                run=CoreRun(borehole_id=h.id,code=code,start_m=start,end_m=end,recovered_m=recovered);s.add(run);s.flush()
                for depth in np.arange(start+.5,end,1):
                    if depth==12.5:continue
                    group=min(int(depth//12),2);center=[(2.1,12,2200),(2.6,50,4100),(3.1,100,6100)][group]
                    s.add(Reading(borehole_id=h.id,run_id=run.id,depth_m=float(depth),density=round(float(center[0]+rng.normal(0,.035)),4),susceptibility=round(float(center[1]+rng.normal(0,1.5)),4),velocity=round(float(center[2]+rng.normal(0,55)),3)))
            s.add(MissingInterval(borehole_id=h.id,start_m=12,end_m=13,state='observed',reason=''))
            # 入库芯盒。BX-01 三项物性顺倒都说得通，留待核实后由主管核定顺放；
            # BX-02 复测只在倒放下配得上原测点；BX-03 尚未复测，属未核查，不得切样。
            boxes=[CoreBox(borehole_id=h.id,code='BX-01',start_m=0,end_m=9),
                   CoreBox(borehole_id=h.id,code='BX-02',start_m=9,end_m=21),
                   CoreBox(borehole_id=h.id,code='BX-03',start_m=21,end_m=36)]
            s.add_all(boxes);s.flush()
            by_depth={float(r.depth_m):r for r in s.scalars(select(Reading).where(Reading.borehole_id==h.id))}
            def add_remeasure(box,physical,depth):
                # 复测偏移按物理朝向落屏：倒放箱的实际深度对应到自箱尾计，可越过缺芯。
                segs=box_service.segments(box.start_m,box.end_m,s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)).all())
                off=box_service.offset_of(depth,segs)
                if physical=='reversed':off=box_service.phys_len(segs)-off
                r=by_depth[depth];s.add(BoxRemeasure(box_id=box.id,offset_m=round(off,4),density=r.density,susceptibility=r.susceptibility,velocity=r.velocity))
            # BX-01：顺向放置实测，但三项物性在该岩性带内顺倒都配得上 → 留待核实。
            for depth in[.5,2.5,3.5]:add_remeasure(boxes[0],'normal',depth)
            # BX-02：实际倒放（含 12–13m 缺芯），物理复测仅在倒放下配得上原测点。
            for depth in[20.5,15.5,11.5]:add_remeasure(boxes[1],'reversed',depth)
            s.flush()
            for b in boxes[:2]:
                basis=box_service.compare(s,b);b.basis=basis
                b.orientation='normal'if b.code=='BX-01'else'reversed'
                b.state='confirmed';b.confirmed_by='supervisor@liheng.local';b.confirmed_at=box_service.now()
                basis['confirmed_orientation']=b.orientation
                if b.code=='BX-01':b.note='三项物性顺倒都说得通，现场复核纹理后核定顺放'
            legacy=Interpretation(borehole_id=h.id,state='historical',evidence={'note':'旧纸本区间来源，仅保留既有切样，不替代新GMM解释'});s.add(legacy);s.flush();st=Stratum(interpretation_id=legacy.id,start_m=0,end_m=12,lithology='旧编录砂岩',contact_note='纸本编录回录，仅保留历史取样依据');s.add(st);s.flush();sample=SampleInterval(borehole_id=h.id,stratum_id=st.id,code='CS-031-OLD',start_m=8,end_m=9,purpose='历史抗压试验',destructive=True,state='broken',box_id=boxes[0].id,box_from_m=8,box_to_m=9,box_orientation='normal');s.add(sample);s.flush();s.add(Seal(sample_id=sample.id,code='CX031-001',state='broken',reason='运输交接发现铅封裂口，待现场核样重封',sealed_by='operator@liheng.local',snapshot={'code':sample.code,'start_m':8,'end_m':9,'source':'历史纸本'}))
    with Session()as s:return {cls.__tablename__:len(s.scalars(select(cls)).all())for cls in [User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,CoreBox,BoxRemeasure,SampleInterval,Seal,Custody,ColumnRevision]}
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False))
