"""离线测试 S7Client，不导入真实 snap7。"""
import sys
from types import SimpleNamespace
import pytest
from plc.s7_client import S7Client
from plc.config import load_config


class MemoryClient:
    def __init__(self):
        self.online=False; self.destroyed=False; self.parameters=None; self.dbs={400:bytearray(256),401:bytearray(256)}; self.writes=0
    def connect(self,ip,rack,slot): self.parameters=(ip,rack,slot); self.online=True
    def get_connected(self): return self.online
    def db_read(self,db,offset,size): return bytearray(self.dbs.setdefault(db,bytearray(256))[offset:offset+size])
    def db_write(self,db,offset,data):
        self.writes+=1; b=self.dbs.setdefault(db,bytearray(256)); b[offset:offset+len(data)]=data
    def disconnect(self): self.online=False
    def destroy(self): self.destroyed=True


def install_fake_snap7(monkeypatch,fake):
    monkeypatch.setitem(sys.modules,'snap7',SimpleNamespace(client=SimpleNamespace(Client=lambda:fake)))


def test_client_lifecycle_read_and_fail_closed_write(monkeypatch):
    fake=MemoryClient(); install_fake_snap7(monkeypatch,fake)
    config=load_config(); client=S7Client(config)
    with pytest.raises(ConnectionError): client.read_bytes(400,0,1)
    client.connect(); assert fake.parameters==('192.168.2.20',0,1)
    assert client.read_bytes(400,0,1)==b'\x00'
    with pytest.raises(RuntimeError,match='未武装'): client.write_bytes(401,0,b'\x01')
    assert fake.writes==0
    config['safety'].update(write_enabled=True,dry_run=False)
    client.write_bytes(401,0,b'\x05'); assert fake.dbs[401][0]==5 and fake.writes==1
    client.disconnect(); assert fake.destroyed and not client.is_connected()


def test_failed_connection_cleanup(monkeypatch):
    fake=MemoryClient()
    def failed(*args): raise ConnectionError('模拟失败')
    fake.connect=failed; install_fake_snap7(monkeypatch,fake)
    client=S7Client(load_config())
    with pytest.raises(ConnectionError): client.connect()
    assert fake.destroyed
