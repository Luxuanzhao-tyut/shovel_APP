from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JointWaypoint:
    """三轴联合目标点。t_s 仅为内部顺序索引兼容字段。"""
    t_s: float
    lift: float
    push: float
    swing: float


@dataclass(frozen=True)
class JointTrajectory:
    points: tuple[JointWaypoint, ...]
    name: str = '未命名轨迹'

    @property
    def duration_s(self) -> float:
        return self.points[-1].t_s if self.points else 0.0

    def validate(self, min_points: int = 2) -> None:
        if len(self.points) < int(min_points):
            raise ValueError(f'联合轨迹至少需要 {int(min_points)} 个点')
        if abs(self.points[0].t_s) > 1e-9:
            raise ValueError('第一个轨迹点时间必须为 0 s')
        prev = -1.0
        for i, p in enumerate(self.points):
            vals = (p.t_s, p.lift, p.push, p.swing)
            if not all(float(v) == float(v) and abs(float(v)) != float('inf') for v in vals):
                raise ValueError(f'第 {i + 1} 个轨迹点包含无效数值')
            if p.t_s <= prev:
                raise ValueError('轨迹点时间必须严格递增')
            prev = p.t_s

    def reference_at(self, t_s: float) -> JointWaypoint:
        self.validate()
        t = max(0.0, min(float(t_s), self.duration_s))
        if t <= 0:
            return self.points[0]
        if t >= self.duration_s:
            return self.points[-1]
        for a, b in zip(self.points, self.points[1:]):
            if a.t_s <= t <= b.t_s:
                r = (t - a.t_s) / (b.t_s - a.t_s)
                swing_delta = (b.swing - a.swing + 180.0) % 360.0 - 180.0
                return JointWaypoint(t, a.lift + r*(b.lift-a.lift), a.push + r*(b.push-a.push), a.swing + r*swing_delta)
        return self.points[-1]


def save_joint_trajectory(path: Path, trajectory: JointTrajectory) -> Path:
    trajectory.validate(min_points=1)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['time_s','lift_encoder','push_encoder','swing_angle_deg'])
        for p in trajectory.points:
            w.writerow([f'{p.t_s:.6f}', f'{p.lift:.6f}', f'{p.push:.6f}', f'{p.swing:.6f}'])
    return path


def _make_trajectory(rows, name: str) -> JointTrajectory:
    pts=[]
    for i, values in enumerate(rows):
        try:
            lift, push, swing = values
            pts.append(JointWaypoint(float(i), float(lift), float(push), float(swing)))
        except Exception as exc:
            raise ValueError(f'轨迹文件第 {i+1} 个数据点格式错误：{exc}') from exc
    traj=JointTrajectory(tuple(pts), name); traj.validate(min_points=1); return traj


def load_joint_trajectory(path: Path) -> JointTrajectory:
    """读取 CSV。兼容旧四列格式，也接受中文/英文三目标列。"""
    path=Path(path)
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        reader=csv.DictReader(f); rows=list(reader)
    if not rows: raise ValueError('轨迹文件没有数据点')
    def pick(r, aliases):
        for k in aliases:
            if k in r and r[k] not in (None,''): return r[k]
        raise KeyError('/'.join(aliases))
    pts=[]
    for i,r in enumerate(rows,1):
        try:
            t=float(r.get('time_s', i-1))
            lift=float(pick(r,['lift_encoder','提升目标','提升编码器','lift']))
            push=float(pick(r,['push_encoder','推压目标','推压编码器','push']))
            swing=float(pick(r,['swing_angle_deg','回转目标(°)','回转目标','回转角','swing']))
            pts.append(JointWaypoint(t,lift,push,swing))
        except Exception as exc: raise ValueError(f'轨迹 CSV 第 {i} 行缺少或无法识别三轴目标列：{exc}') from exc
    traj=JointTrajectory(tuple(pts),path.stem); traj.validate(min_points=1); return traj


def _xlsx_rows_stdlib(path: Path):
    """无第三方依赖读取简单 .xlsx 首工作表；用于现场电脑未安装 openpyxl 时兜底。"""
    import re
    import zipfile
    import xml.etree.ElementTree as ET

    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path, 'r') as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si', ns):
                shared.append(''.join(t.text or '' for t in si.iterfind('.//m:t', ns)))
        # 模板/常规 Excel 的首工作表通常为 sheet1.xml；这里不依赖 openpyxl。
        root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        out = []
        for row in root.findall('.//m:sheetData/m:row', ns):
            cells = {}
            max_col = -1
            for c in row.findall('m:c', ns):
                ref = c.attrib.get('r', '')
                letters = re.match(r'[A-Z]+', ref)
                if not letters:
                    continue
                col = 0
                for ch in letters.group(0):
                    col = col * 26 + (ord(ch) - 64)
                col -= 1
                typ = c.attrib.get('t')
                v = c.find('m:v', ns)
                inline = c.find('m:is', ns)
                value = None
                if typ == 'inlineStr' and inline is not None:
                    value = ''.join(t.text or '' for t in inline.iterfind('.//m:t', ns))
                elif v is not None and v.text is not None:
                    raw = v.text
                    if typ == 's':
                        value = shared[int(raw)]
                    else:
                        try:
                            value = float(raw)
                            if value.is_integer(): value = int(value)
                        except Exception:
                            value = raw
                cells[col] = value
                max_col = max(max_col, col)
            out.append(tuple(cells.get(i) for i in range(max_col + 1)) if max_col >= 0 else tuple())
        return out


def load_joint_trajectory_xlsx(path: Path) -> JointTrajectory:
    """读取 Excel 首个工作表。优先 openpyxl；未安装时自动使用内置 XLSX 读取器。"""
    path=Path(path)
    try:
        from openpyxl import load_workbook
    except ImportError:
        all_rows = _xlsx_rows_stdlib(path)
    else:
        wb=load_workbook(path, read_only=True, data_only=True); ws=wb.active
        all_rows=list(ws.iter_rows(values_only=True)); wb.close()
    if not all_rows: raise ValueError('Excel 为空')
    headers=[str(x).strip() if x is not None else '' for x in all_rows[0]]
    aliases={
        'lift':['提升目标','提升编码器','lift_encoder','lift'],
        'push':['推压目标','推压编码器','push_encoder','push'],
        'swing':['回转目标(°)','回转目标','回转角','swing_angle_deg','swing'],
    }
    idx={}
    for key,names in aliases.items():
        for name in names:
            if name in headers: idx[key]=headers.index(name); break
        if key not in idx: raise ValueError(f'Excel 缺少“{names[0]}”列；当前表头：{headers}')
    vals=[]
    for excel_row_no,row in enumerate(all_rows[1:],2):
        if not row or all(v is None or str(v).strip()=='' for v in row): continue
        try: vals.append((row[idx['lift']],row[idx['push']],row[idx['swing']]))
        except Exception as exc: raise ValueError(f'Excel 第 {excel_row_no} 行读取失败：{exc}') from exc
    return _make_trajectory(vals,path.stem)

def load_joint_trajectory_file(path: Path) -> JointTrajectory:
    path=Path(path)
    if path.suffix.lower()=='.csv': return load_joint_trajectory(path)
    if path.suffix.lower()=='.xlsx': return load_joint_trajectory_xlsx(path)
    raise ValueError('仅支持 .csv 或 .xlsx 轨迹文件')
