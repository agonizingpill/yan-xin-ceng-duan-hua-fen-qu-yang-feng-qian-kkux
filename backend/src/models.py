from sqlalchemy import String,Float,ForeignKey,JSON,Boolean,CheckConstraint,UniqueConstraint,Text
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    password:Mapped[str]=mapped_column(String(256))
    role:Mapped[str]=mapped_column(String(20))
class Audit(Base):
    __tablename__='audit'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(Text)
    at:Mapped[str]=mapped_column(String(40))
class Borehole(Base):
    __tablename__='boreholes'
    __table_args__=(CheckConstraint('total_depth>0 AND cut_quota>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    site:Mapped[str]=mapped_column(String(120))
    total_depth:Mapped[float]=mapped_column(Float)
    cut_quota:Mapped[float]=mapped_column(Float)
    state:Mapped[str]=mapped_column(String(20),default='open')
class CoreRun(Base):
    __tablename__='core_runs'
    __table_args__=(UniqueConstraint('borehole_id','code'),CheckConstraint('start_m>=0 AND end_m>start_m AND recovered_m>=0 AND recovered_m<=end_m-start_m'))
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    code:Mapped[str]=mapped_column(String(40))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    recovered_m:Mapped[float]=mapped_column(Float)
class Reading(Base):
    __tablename__='readings'
    __table_args__=(UniqueConstraint('borehole_id','depth_m'),CheckConstraint('depth_m>=0 AND density>0 AND susceptibility>=0 AND velocity>0'))
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    run_id:Mapped[int]=mapped_column(ForeignKey('core_runs.id'))
    depth_m:Mapped[float]=mapped_column(Float)
    density:Mapped[float]=mapped_column(Float)
    susceptibility:Mapped[float]=mapped_column(Float)
    velocity:Mapped[float]=mapped_column(Float)
class MissingInterval(Base):
    __tablename__='missing_intervals'
    __table_args__=(CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    reason:Mapped[str]=mapped_column(String(600),default='')
    state:Mapped[str]=mapped_column(String(20),default='observed')
class Interpretation(Base):
    __tablename__='interpretations'
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    state:Mapped[str]=mapped_column(String(20),default='queued')
    evidence:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(String(600),default='')
class Stratum(Base):
    __tablename__='strata'
    __table_args__=(UniqueConstraint('interpretation_id','start_m'),CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    interpretation_id:Mapped[int]=mapped_column(ForeignKey('interpretations.id'))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    lithology:Mapped[str]=mapped_column(String(100))
    contact_note:Mapped[str]=mapped_column(String(600))
class CoreBox(Base):
    __tablename__='core_boxes'
    __table_args__=(UniqueConstraint('borehole_id','code'),CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    code:Mapped[str]=mapped_column(String(40))
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    # 入库芯盒偶有首尾倒放：unverified→pending/resolved→confirmed。核定前不得切样。
    state:Mapped[str]=mapped_column(String(20),default='unverified')
    orientation:Mapped[str]=mapped_column(String(20),default='normal')
    basis:Mapped[dict]=mapped_column(JSON,default=dict)
    note:Mapped[str]=mapped_column(String(600),default='')
    confirmed_by:Mapped[str]=mapped_column(String(120),default='')
    confirmed_at:Mapped[str]=mapped_column(String(40),default='')
class BoxRemeasure(Base):
    __tablename__='box_remeasures'
    __table_args__=(UniqueConstraint('box_id','offset_m'),CheckConstraint('offset_m>=0 AND density>0 AND susceptibility>=0 AND velocity>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    box_id:Mapped[int]=mapped_column(ForeignKey('core_boxes.id'))
    # 自箱头计的实际有芯偏移，因此与首尾倒放无关，可两向比对。
    offset_m:Mapped[float]=mapped_column(Float)
    density:Mapped[float]=mapped_column(Float)
    susceptibility:Mapped[float]=mapped_column(Float)
    velocity:Mapped[float]=mapped_column(Float)
class SampleInterval(Base):
    __tablename__='sample_intervals'
    __table_args__=(CheckConstraint('start_m>=0 AND end_m>start_m'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    stratum_id:Mapped[int]=mapped_column(ForeignKey('strata.id'))
    code:Mapped[str]=mapped_column(String(60),unique=True)
    start_m:Mapped[float]=mapped_column(Float)
    end_m:Mapped[float]=mapped_column(Float)
    purpose:Mapped[str]=mapped_column(String(200))
    destructive:Mapped[bool]=mapped_column(Boolean,default=True)
    state:Mapped[str]=mapped_column(String(20),default='planned')
    # 落单留实际箱位：切样所在芯盒及相对箱头的实际位置（倒放时已换算）。
    box_id:Mapped[int|None]=mapped_column(ForeignKey('core_boxes.id'),nullable=True)
    box_from_m:Mapped[float|None]=mapped_column(Float,nullable=True)
    box_to_m:Mapped[float|None]=mapped_column(Float,nullable=True)
    box_orientation:Mapped[str|None]=mapped_column(String(20),nullable=True)
    # 回执丢失重试的幂等键；同一键重试返回原切样单，不重复扣配额。
    request_key:Mapped[str|None]=mapped_column(String(80),unique=True,nullable=True)
class Seal(Base):
    __tablename__='seals'
    id:Mapped[int]=mapped_column(primary_key=True)
    sample_id:Mapped[int]=mapped_column(ForeignKey('sample_intervals.id'))
    code:Mapped[str]=mapped_column(String(60),unique=True)
    previous_id:Mapped[int|None]=mapped_column(ForeignKey('seals.id'),nullable=True)
    state:Mapped[str]=mapped_column(String(20),default='intact')
    reason:Mapped[str]=mapped_column(String(600),default='')
    sealed_by:Mapped[str]=mapped_column(String(120))
    snapshot:Mapped[dict]=mapped_column(JSON)
class Custody(Base):
    __tablename__='custodies'
    __table_args__=(UniqueConstraint('seal_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    seal_id:Mapped[int]=mapped_column(ForeignKey('seals.id'))
    receiver:Mapped[str]=mapped_column(String(100))
    destination:Mapped[str]=mapped_column(String(120))
    condition:Mapped[str]=mapped_column(String(300))
    at:Mapped[str]=mapped_column(String(40))
class ColumnRevision(Base):
    __tablename__='column_revisions'
    __table_args__=(UniqueConstraint('borehole_id','version'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    borehole_id:Mapped[int]=mapped_column(ForeignKey('boreholes.id'))
    version:Mapped[str]=mapped_column(String(40))
    note:Mapped[str]=mapped_column(String(600))
    state:Mapped[str]=mapped_column(String(20),default='draft')
    snapshot:Mapped[dict]=mapped_column(JSON,default=dict)
    frozen_by:Mapped[str]=mapped_column(String(120),default='')
