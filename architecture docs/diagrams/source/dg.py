"""dg.py - tiny diagram library that emits a native draw.io file AND an SVG from one geometry.

Why: draw.io is not available to the author, so the same layout is rendered to SVG/PNG for review,
while the .drawio file uses the AWS 2023 icon library (mxgraph.aws4.*) when opened in draw.io.

Everything is absolute-positioned; for the .drawio output each cell is nested inside the smallest
group that contains it, so groups can be dragged in draw.io.
"""
import html
import math
import textwrap
from xml.etree import ElementTree as ET

FONT = "Helvetica, Arial, sans-serif"

# AWS 2023 icon category colours
CAT = {
    "compute": "#ED7100", "container": "#ED7100", "db": "#C925D1", "net": "#8C4FFF",
    "storage": "#7AA116", "integ": "#E7157B", "mgmt": "#E7157B", "sec": "#DD344C",
    "front": "#DD344C", "dev": "#3B48CC", "dark": "#232F3D", "ext": "#5A6C86", "grey": "#7D8998",
}

# group kinds: svg stroke/fill/dash/label colour/badge, drawio style
GROUP = {
    "aws_cloud": dict(stroke="#232F3E", fill="none", dash=None, color="#232F3E", badge="AWS",
                      dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;dashed=0;fontColor=#232F3E;"),
    "region": dict(stroke="#147EB4", fill="none", dash="6 4", color="#147EB4", badge="RGN",
                   dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;strokeColor=#147EB4;fillColor=none;dashed=1;fontColor=#147EB4;"),
    "vpc": dict(stroke="#8C4FFF", fill="none", dash=None, color="#6B3FD1", badge="VPC",
                dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;dashed=0;fontColor=#6B3FD1;"),
    "az": dict(stroke="#147EB4", fill="none", dash="4 3", color="#147EB4", badge=None,
               dio="fillColor=none;strokeColor=#147EB4;dashed=1;dashPattern=4 3;fontColor=#147EB4;"),
    "public": dict(stroke="#7AA116", fill="#F2F6E8", dash=None, color="#3F6B0F", badge="PUB",
                   dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;dashed=0;fontColor=#3F6B0F;"),
    "private": dict(stroke="#147EB4", fill="#E6F2F8", dash=None, color="#147EB4", badge="PRV",
                    dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#147EB4;fillColor=#E6F2F8;dashed=0;fontColor=#147EB4;"),
    "account": dict(stroke="#CD2264", fill="none", dash=None, color="#CD2264", badge="ACC",
                    dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;strokeColor=#CD2264;fillColor=none;dashed=0;fontColor=#CD2264;"),
    "ou": dict(stroke="#5A6C86", fill="#F7F9FA", dash="6 4", color="#3F4E63", badge="OU",
               dio="rounded=1;arcSize=2;strokeColor=#5A6C86;fillColor=#F7F9FA;dashed=1;dashPattern=6 4;fontColor=#3F4E63;"),
    "org": dict(stroke="#232F3E", fill="none", dash=None, color="#232F3E", badge="ORG",
                dio="rounded=1;arcSize=1;strokeColor=#232F3E;fillColor=none;dashed=0;fontColor=#232F3E;"),
    "dc": dict(stroke="#5A6C86", fill="none", dash=None, color="#3F4E63", badge="DC",
               dio="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_corporate_data_center;strokeColor=#5A6C86;fillColor=none;dashed=0;fontColor=#3F4E63;"),
    "band": dict(stroke="#9AA5AE", fill="#FFFFFF", dash=None, color="#3F4E63", badge=None,
                 dio="rounded=1;arcSize=3;strokeColor=#9AA5AE;fillColor=#FFFFFF;dashed=0;fontColor=#3F4E63;"),
    "band_ecs": dict(stroke="#ED7100", fill="#FFF7EE", dash=None, color="#B35400", badge=None,
                     dio="rounded=1;arcSize=2;strokeColor=#ED7100;fillColor=#FFF7EE;dashed=0;fontColor=#B35400;"),
    "band_data": dict(stroke="#C925D1", fill="#FCF3FD", dash=None, color="#8F1996", badge=None,
                      dio="rounded=1;arcSize=2;strokeColor=#C925D1;fillColor=#FCF3FD;dashed=0;fontColor=#8F1996;"),
    "band_ops": dict(stroke="#E7157B", fill="#FEF3F8", dash=None, color="#B00F5E", badge=None,
                     dio="rounded=1;arcSize=2;strokeColor=#E7157B;fillColor=#FEF3F8;dashed=0;fontColor=#B00F5E;"),
    "ext": dict(stroke="#7D8998", fill="#F4F6F8", dash="5 4", color="#3F4E63", badge=None,
                dio="rounded=1;arcSize=3;strokeColor=#7D8998;fillColor=#F4F6F8;dashed=1;dashPattern=5 4;fontColor=#3F4E63;"),
    "ghost": dict(stroke="#B8C0C8", fill="#FAFBFC", dash="3 3", color="#7D8998", badge=None,
                  dio="rounded=1;arcSize=3;strokeColor=#B8C0C8;fillColor=#FAFBFC;dashed=1;dashPattern=3 3;fontColor=#7D8998;"),
}

EDGE = {
    "erp": dict(color="#C2570C", w=3.0, dash=None, label="#9A4309"),
    "app": dict(color="#5B6770", w=2.0, dash=None, label="#3F4A52"),
    "ops": dict(color="#147EB4", w=2.0, dash="7 4", label="#0F6590"),
    "net": dict(color="#8C4FFF", w=2.2, dash="7 4", label="#6B3FD1"),
    "deploy": dict(color="#3B7D23", w=2.0, dash="7 4", label="#2E6119"),
    "ext": dict(color="#8A949E", w=1.5, dash="3 3", label="#5B6770"),
}


ZORD = {"aws_cloud": 0, "org": 0, "region": 1, "ou": 1, "vpc": 2, "account": 2, "dc": 2, "ext": 2, "ghost": 2, "az": 3,
        "public": 4, "private": 4}


def gkey(g):
    return (ZORD.get(g["kind"], 5), -g["w"] * g["h"])


def wrap(text, width):
    out = []
    for para in str(text).split("\n"):
        out.extend(textwrap.wrap(para, width, break_long_words=False) or [""])
    return out


class D:
    def __init__(self, name, w, h, title, subtitle=""):
        self.name, self.w, self.h, self.title, self.subtitle = name, w, h, title, subtitle
        self.groups, self.nodes, self.texts, self.edges, self.legends = [], [], [], [], []
        self.ids = set()

    def _id(self, i):
        assert i not in self.ids, f"duplicate id {i}"
        self.ids.add(i)
        return i

    # ---- element constructors -------------------------------------------------------
    def group(self, id, label, x, y, w, h, kind="band", sub=None, lsize=12, lalign="left"):
        self.groups.append(dict(id=self._id(id), label=label, x=x, y=y, w=w, h=h, kind=kind, sub=sub, lsize=lsize, lalign=lalign))

    def node(self, id, label, x, y, icon, cat="compute", code=None, sub=None, kind="res", size=48, lw=150, lines=3, ls="b"):
        """x,y = top-left of the icon square. kind: res (AWS resourceIcon) | plain (mxgraph.aws4.<icon> dark glyph)."""
        self.nodes.append(dict(id=self._id(id), label=label, x=x, y=y, icon=icon, cat=cat, code=code or icon[:3].upper(),
                               sub=sub, kind=kind, size=size, lw=lw, lines=lines, ls=ls))

    def text(self, id, lines, x, y, w, size=11, color="#232F3E", bold_first=False, h=None, box=False, align="left", lh=None):
        if isinstance(lines, str):
            lines = [lines]
        lh = lh or size + 4
        h = h or (len(lines) * lh + 8)
        self.texts.append(dict(id=self._id(id), lines=lines, x=x, y=y, w=w, h=h, size=size, color=color,
                               bold_first=bold_first, box=box, align=align, lh=lh))

    def edge(self, id, src, ss, dst, ds, label="", style="app", via=None, mid=None, sf=0.5, df=0.5, num=None, lpos=None, arrow=True, both=False):
        self.edges.append(dict(id=self._id(id), src=src, ss=ss, dst=dst, ds=ds, label=label, style=style, via=via,
                               mid=mid, sf=sf, df=df, num=num, lpos=lpos, arrow=arrow, both=both))

    def legend(self, x, y, items, title="Legend", w=300):
        self.legends.append(dict(x=x, y=y, items=items, title=title, w=w, id=self._id(f"legend{len(self.legends)}")))

    # ---- geometry helpers -----------------------------------------------------------
    def rect(self, i):
        for g in self.groups:
            if g["id"] == i:
                return g["x"], g["y"], g["w"], g["h"]
        for n in self.nodes:
            if n["id"] == i:
                return n["x"], n["y"], n["size"], n["size"]
        for t in self.texts:
            if t["id"] == i:
                return t["x"], t["y"], t["w"], t["h"]
        raise KeyError(i)

    @staticmethod
    def anchor(r, side, f):
        x, y, w, h = r
        if side == "r":
            return x + w, y + h * f
        if side == "l":
            return x, y + h * f
        if side == "t":
            return x + w * f, y
        return x + w * f, y + h

    def path(self, e):
        r0, r1 = self.rect(e["src"]), self.rect(e["dst"])
        p0 = self.anchor(r0, e["ss"], e["sf"])
        p1 = self.anchor(r1, e["ds"], e["df"])
        via = e["via"]
        if via is None:
            via = []
            s0, s1 = e["ss"], e["ds"]
            if s0 in "rl" and s1 in "rl":
                if abs(p0[1] - p1[1]) > 0.5:
                    mx = e["mid"] if e["mid"] is not None else (p0[0] + p1[0]) / 2
                    via = [(mx, p0[1]), (mx, p1[1])]
            elif s0 in "tb" and s1 in "tb":
                if abs(p0[0] - p1[0]) > 0.5:
                    my = e["mid"] if e["mid"] is not None else (p0[1] + p1[1]) / 2
                    via = [(p0[0], my), (p1[0], my)]
            elif s0 in "rl" and s1 in "tb":
                via = [(p1[0], p0[1])]
            else:
                via = [(p0[0], p1[1])]
        return [p0] + [tuple(v) for v in via] + [p1]

    @staticmethod
    def midpoint(pts):
        segs = [(math.dist(pts[i], pts[i + 1]), i) for i in range(len(pts) - 1)]
        total = sum(s for s, _ in segs)
        half, acc = total / 2, 0
        for s, i in segs:
            if acc + s >= half:
                t = (half - acc) / s if s else 0
                return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)
            acc += s
        return pts[0]

    # ---- SVG ------------------------------------------------------------------------
    def to_svg(self):
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">']
        o.append('<defs>')
        for k, v in EDGE.items():
            o.append(f'<marker id="a-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{v["color"]}"/></marker>')
        o.append('</defs>')
        o.append(f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>')
        o.append(f'<text x="24" y="34" font-size="22" font-weight="700" fill="#232F3E">{html.escape(self.title)}</text>')
        if self.subtitle:
            o.append(f'<text x="24" y="56" font-size="12.5" fill="#5B6770">{html.escape(self.subtitle)}</text>')
        for g in sorted(self.groups, key=gkey):
            s = GROUP[g["kind"]]
            dash = f' stroke-dasharray="{s["dash"]}"' if s["dash"] else ""
            o.append(f'<rect x="{g["x"]}" y="{g["y"]}" width="{g["w"]}" height="{g["h"]}" rx="5" fill="{s["fill"]}" stroke="{s["stroke"]}" stroke-width="1.6"{dash}/>')
            lx = g["x"] + 10
            if s["badge"]:
                o.append(f'<rect x="{g["x"] + 6}" y="{g["y"] + 6}" width="30" height="20" rx="3" fill="{s["stroke"]}"/>')
                o.append(f'<text x="{g["x"] + 21}" y="{g["y"] + 20}" font-size="9" font-weight="700" fill="#fff" text-anchor="middle">{s["badge"]}</text>')
                lx = g["x"] + 42
            anchor, tx = "start", lx
            if g["lalign"] == "center":
                anchor, tx = "middle", g["x"] + g["w"] / 2
            o.append(f'<text x="{tx}" y="{g["y"] + 21}" font-size="{g["lsize"]}" font-weight="700" fill="{s["color"]}" text-anchor="{anchor}">{html.escape(g["label"])}</text>')
            if g["sub"]:
                for j, ln in enumerate(wrap(g["sub"], max(20, int(g["w"] / 6.1)))):
                    o.append(f'<text x="{tx}" y="{g["y"] + 36 + j * 13}" font-size="10.5" fill="#5B6770" text-anchor="{anchor}">{html.escape(ln)}</text>')
        for t in self.texts:
            if t["box"]:
                o.append(f'<rect x="{t["x"]}" y="{t["y"]}" width="{t["w"]}" height="{t["h"]}" rx="4" fill="#FFFFFF" stroke="#C5CCD3"/>')
            for j, ln in enumerate(t["lines"]):
                fw = "700" if (t["bold_first"] and j == 0) else "400"
                x = t["x"] + (t["w"] / 2 if t["align"] == "center" else 8)
                anc = "middle" if t["align"] == "center" else "start"
                o.append(f'<text x="{x}" y="{t["y"] + 14 + j * t["lh"]}" font-size="{t["size"]}" font-weight="{fw}" fill="{t["color"]}" text-anchor="{anc}">{html.escape(ln)}</text>')
        for e in self.edges:
            pts = self.path(e)
            st = EDGE[e["style"]]
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            dash = f' stroke-dasharray="{st["dash"]}"' if st["dash"] else ""
            me = f' marker-end="url(#a-{e["style"]})"' if e["arrow"] else ""
            ms = f' marker-start="url(#a-{e["style"]})"' if e["both"] else ""
            o.append(f'<path d="{d}" fill="none" stroke="{st["color"]}" stroke-width="{st["w"]}"{dash}{me}{ms} stroke-linejoin="round"/>')
        for n in self.nodes:
            s = n["size"]
            fill = CAT.get(n["cat"], n["cat"])
            if n["kind"] == "plain":
                fill = CAT["dark"]
            o.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{s}" height="{s}" rx="6" fill="{fill}" stroke="#fff" stroke-width="1"/>')
            o.append(f'<text x="{n["x"] + s / 2}" y="{n["y"] + s / 2 + 4}" font-size="{11 if len(n["code"]) <= 3 else 9}" font-weight="700" fill="#fff" text-anchor="middle">{html.escape(n["code"])}</text>')
            ls_ = wrap(n["label"], max(12, int(n["lw"] / 6.3)))[: n["lines"]]
            subl = wrap(n["sub"], max(12, int(n["lw"] / 5.6)))[: (5 if n.get("ls", "b") in "rl" else 3)] if n["sub"] else []
            total = len(ls_) * 12.5 + len(subl) * 11.5
            side = n.get("ls", "b")
            cx, cy = n["x"] + s / 2, n["y"] + s / 2
            if side == "b":
                x0, y0, anc = cx, n["y"] + s + 13, "middle"
            elif side == "t":
                x0, y0, anc = cx, n["y"] - 6 - total + 10, "middle"
            elif side == "r":
                x0, y0, anc = n["x"] + s + 8, cy - total / 2 + 10, "start"
            else:
                x0, y0, anc = n["x"] - 8, cy - total / 2 + 10, "end"
            for j, ln in enumerate(ls_):
                o.append(f'<text x="{x0}" y="{y0 + j * 12.5}" font-size="11" fill="#232F3E" text-anchor="{anc}" font-weight="{"600" if j == 0 else "400"}">{html.escape(ln)}</text>')
            for k, ln in enumerate(subl):
                o.append(f'<text x="{x0}" y="{y0 + len(ls_) * 12.5 + k * 11.5}" font-size="9.5" fill="#6B7783" text-anchor="{anc}">{html.escape(ln)}</text>')
        for e in self.edges:
            pts = self.path(e)
            st = EDGE[e["style"]]
            if e["label"]:
                mx, my = e["lpos"] or self.midpoint(pts)
                lines = wrap(e["label"], 30)
                w = max(len(l) for l in lines) * 5.6 + 8
                h = len(lines) * 12 + 4
                o.append(f'<rect x="{mx - w / 2:.1f}" y="{my - h / 2:.1f}" width="{w:.1f}" height="{h}" rx="3" fill="#fff" fill-opacity="0.92"/>')
                for j, ln in enumerate(lines):
                    o.append(f'<text x="{mx:.1f}" y="{my - h / 2 + 11 + j * 12:.1f}" font-size="10" fill="{st["label"]}" text-anchor="middle">{html.escape(ln)}</text>')
            if e["num"]:
                bx, by = pts[0]
                dx = pts[1][0] - pts[0][0]
                dy = pts[1][1] - pts[0][1]
                L = math.hypot(dx, dy) or 1
                bx, by = bx + dx / L * 16, by + dy / L * 16
                o.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="9" fill="#232F3E"/><text x="{bx:.1f}" y="{by + 3.5:.1f}" font-size="10" font-weight="700" fill="#fff" text-anchor="middle">{e["num"]}</text>')
        for lg in self.legends:
            h = 30 + len(lg["items"]) * 20
            o.append(f'<rect x="{lg["x"]}" y="{lg["y"]}" width="{lg["w"]}" height="{h}" rx="4" fill="#fff" stroke="#C5CCD3"/>')
            o.append(f'<text x="{lg["x"] + 10}" y="{lg["y"] + 18}" font-size="11.5" font-weight="700" fill="#232F3E">{html.escape(lg["title"])}</text>')
            for j, (st_name, lab) in enumerate(lg["items"]):
                st = EDGE[st_name]
                yy = lg["y"] + 38 + j * 20
                dash = f' stroke-dasharray="{st["dash"]}"' if st["dash"] else ""
                o.append(f'<line x1="{lg["x"] + 10}" y1="{yy}" x2="{lg["x"] + 48}" y2="{yy}" stroke="{st["color"]}" stroke-width="{st["w"]}"{dash}/>')
                o.append(f'<text x="{lg["x"] + 56}" y="{yy + 3.5}" font-size="10.5" fill="#3F4A52">{html.escape(lab)}</text>')
        o.append('</svg>')
        return "\n".join(o)

    # ---- draw.io --------------------------------------------------------------------
    def _parent_of(self, x, y, w, h, own=None):
        best, area = "1", None
        for g in self.groups:
            if g["id"] == own:
                continue
            if g["x"] - 1 <= x and g["y"] - 1 <= y and x + w <= g["x"] + g["w"] + 1 and y + h <= g["y"] + g["h"] + 1:
                a = g["w"] * g["h"]
                if area is None or a < area:
                    best, area = g["id"], a
        return best

    def to_drawio(self):
        mx = ET.Element("mxfile", host="app.diagrams.net", agent="architecture-docs generator", version="24.0.0")
        dia = ET.SubElement(mx, "diagram", id=self.name, name=self.title[:40])
        gm = ET.SubElement(dia, "mxGraphModel", dx="1600", dy="1000", grid="1", gridSize="10", guides="1", tooltips="1", connect="1",
                           arrows="1", fold="1", page="1", pageScale="1", pageWidth=str(self.w), pageHeight=str(self.h), math="0", shadow="0")
        root = ET.SubElement(gm, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")

        def cell(id, value, style, x, y, w, h, parent="1", vertex=True):
            c = ET.SubElement(root, "mxCell", id=id, value=value, style=style, vertex="1", parent=parent)
            px, py = 0, 0
            if parent != "1":
                pg = next(g for g in self.groups if g["id"] == parent)
                px, py = pg["x"], pg["y"]
            ET.SubElement(c, "mxGeometry", x=str(round(x - px, 1)), y=str(round(y - py, 1)), width=str(w), height=str(h)).set("as", "geometry")
            return c

        # title
        cell("title", f'<b style="font-size:20px">{html.escape(self.title)}</b><br><font style="font-size:11px" color="#5B6770">{html.escape(self.subtitle)}</font>',
             "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;overflow=hidden;", 20, 10, self.w - 40, 50)
        for g in sorted(self.groups, key=gkey):
            s = GROUP[g["kind"]]
            label = html.escape(g["label"])
            if g["sub"]:
                label += f'<br><font style="font-size:10px;font-weight:normal" color="#5B6770">{html.escape(g["sub"])}</font>'
            has_icon = "grIcon" in s["dio"]
            style = (s["dio"] + f"verticalAlign=top;align={'center' if g['lalign'] == 'center' else 'left'};spacingLeft={30 if has_icon else 8};"
                     f"fontStyle=1;fontSize={g['lsize']};html=1;whiteSpace=wrap;container=1;collapsible=0;recursiveResize=0;")
            parent = self._parent_of(g["x"], g["y"], g["w"], g["h"], own=g["id"])
            cell(g["id"], label, style, g["x"], g["y"], g["w"], g["h"], parent)
        for t in self.texts:
            body = []
            for j, ln in enumerate(t["lines"]):
                ln = html.escape(ln)
                body.append(f"<b>{ln}</b>" if (t["bold_first"] and j == 0) else ln)
            style = (f"text;html=1;whiteSpace=wrap;overflow=hidden;align={t['align']};verticalAlign=top;spacingLeft=6;spacingTop=2;fontSize={t['size']};fontColor={t['color']};"
                     + ("strokeColor=#C5CCD3;fillColor=#FFFFFF;rounded=1;arcSize=4;" if t["box"] else "strokeColor=none;fillColor=none;"))
            parent = self._parent_of(t["x"], t["y"], t["w"], t["h"], own=t["id"])
            cell(t["id"], "<br>".join(body), style, t["x"], t["y"], t["w"], t["h"], parent)
        for n in self.nodes:
            fill = CAT.get(n["cat"], n["cat"])
            label = html.escape(n["label"])
            if n["sub"]:
                label += f'<br><font style="font-size:9px" color="#6B7783">{html.escape(n["sub"])}</font>'
            lp = {"b": "verticalLabelPosition=bottom;verticalAlign=top;align=center;",
                  "t": "verticalLabelPosition=top;verticalAlign=bottom;align=center;",
                  "r": "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=6;",
                  "l": "labelPosition=left;verticalLabelPosition=middle;align=right;verticalAlign=middle;spacingRight=6;"}[n.get("ls", "b")]
            if n["kind"] == "plain":
                style = (f"sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor={CAT['dark']};strokeColor=none;dashed=0;{lp}"
                         f"html=1;fontSize=11;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{n['icon']};whiteSpace=wrap;")
            else:
                style = (f"sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor={fill};strokeColor=#ffffff;dashed=0;{lp}"
                         f"html=1;fontSize=11;fontStyle=1;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{n['icon']};whiteSpace=wrap;")
            parent = self._parent_of(n["x"], n["y"], n["size"], n["size"])
            c = cell(n["id"], label, style, n["x"], n["y"], n["size"], n["size"], parent)
        for e in self.edges:
            st = EDGE[e["style"]]
            r0, r1 = self.rect(e["src"]), self.rect(e["dst"])
            def side_xy(side, f):
                return {"r": (1, f), "l": (0, f), "t": (f, 0), "b": (f, 1)}[side]
            ex, ey = side_xy(e["ss"], e["sf"])
            nx, ny = side_xy(e["ds"], e["df"])
            style = (f"endArrow={'block' if e['arrow'] else 'none'};startArrow={'block' if e['both'] else 'none'};endFill=1;startFill=1;html=1;rounded=0;strokeColor={st['color']};strokeWidth={st['w']};"
                     + (f"dashed=1;dashPattern={st['dash']};" if st["dash"] else "")
                     + f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx};entryY={ny};entryDx=0;entryDy=0;"
                     f"labelBackgroundColor=#FFFFFF;fontSize=10;fontColor={st['label']};")
            lab = html.escape(e["label"])
            c = ET.SubElement(root, "mxCell", id=e["id"], value=lab, style=style, edge="1", parent="1", source=e["src"], target=e["dst"])
            g = ET.SubElement(c, "mxGeometry", relative="1")
            g.set("as", "geometry")
            pts = self.path(e)
            if len(pts) > 2:
                arr = ET.SubElement(g, "Array")
                arr.set("as", "points")
                for (x, y) in pts[1:-1]:
                    ET.SubElement(arr, "mxPoint", x=str(round(x, 1)), y=str(round(y, 1)))
            if e["num"]:
                bx, by = pts[0]
                dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
                L = math.hypot(dx, dy) or 1
                bx, by = bx + dx / L * 16, by + dy / L * 16
                b = ET.SubElement(root, "mxCell", id=f"{e['id']}_n", value=str(e["num"]), vertex="1", parent="1",
                                  style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#232F3E;strokeColor=none;fontColor=#FFFFFF;fontSize=10;fontStyle=1;")
                ET.SubElement(b, "mxGeometry", x=str(round(bx - 9, 1)), y=str(round(by - 9, 1)), width="18", height="18").set("as", "geometry")
        for lg in self.legends:
            h = 30 + len(lg["items"]) * 20
            cell(lg["id"], f"<b>{html.escape(lg['title'])}</b>", "rounded=1;arcSize=4;html=1;strokeColor=#C5CCD3;fillColor=#FFFFFF;verticalAlign=top;align=left;spacingLeft=8;spacingTop=2;fontSize=11;",
                 lg["x"], lg["y"], lg["w"], h)
            for j, (st_name, lab) in enumerate(lg["items"]):
                st = EDGE[st_name]
                yy = lg["y"] + 38 + j * 20
                c = ET.SubElement(root, "mxCell", id=f"{lg['id']}_l{j}", value="", edge="1", parent="1",
                                  style=f"endArrow=none;html=1;strokeColor={st['color']};strokeWidth={st['w']};" + (f"dashed=1;dashPattern={st['dash']};" if st["dash"] else ""))
                g = ET.SubElement(c, "mxGeometry", width="50", height="50", relative="1")
                g.set("as", "geometry")
                ET.SubElement(g, "mxPoint", x=str(lg["x"] + 10), y=str(yy)).set("as", "sourcePoint")
                ET.SubElement(g, "mxPoint", x=str(lg["x"] + 48), y=str(yy)).set("as", "targetPoint")
                cell(f"{lg['id']}_t{j}", html.escape(lab), "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=10;fontColor=#3F4A52;",
                     lg["x"] + 54, yy - 9, lg["w"] - 60, 18)
        ET.indent(mx)
        return ET.tostring(mx, encoding="unicode")

    def save(self, outdir):
        import os
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, self.name + ".svg"), "w").write(self.to_svg())
        open(os.path.join(outdir, self.name + ".drawio"), "w").write(self.to_drawio())
