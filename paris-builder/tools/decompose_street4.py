"""Decompose street4 (巴黎民居街区4[斜面建筑]) elements into library-v4 atlas-techniques.

Same lossless pipeline as tools/decompose_street1.py: source crop, air-padding trim,
explicit chain->iron_chain rename for 1.21.11, roundtrip + load checks, registry
validation, seven-view previews. Output goes to
knowledge/library-v4/atlas-techniques/<id>/ plus index-street4.json.
Idempotent: geometry is rewritten deterministically; previews are re-rendered only
when the detail schematic hash changes.

Measured layout (probes in runs/TECHNIQUE-ATLAS-v0.1/probe_street4_*.txt):
- bar (north street front, z 2-24): west building x 0-48 (white shops, continuous
  balcony, double dormer rows, ridge chimneys), middle building x 53-80 (dark shop
  band with red doors), east/corner building x 78-108 (rounded NE corner, mansard
  cap with glass-rimmed light well; contains all create:* modded blocks).
- wedge (diagonal slab, z 31-118): two shell facades stepping ~1 x per 3.4 z,
  warped-trapdoor awning shops, mansard with double ridge merging at the prow tip
  (z 111-118 chamfer, ~3 x per z). No terrain slope anywhere: every wall starts at
  y=0; '斜面' is the oblique plan, not a hillside. st4-slope-base is therefore a
  documented negative finding, not a crop.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.source_decomposition import crop, encode, inventory, state_context, family_matches, migrate_to_12111
from paris_builder.schematic import load_schematic, _plain
from paris_builder.exporter import write_schematic, dump_json
from paris_builder.fonts import node_binary
from paris_builder.preview3d import render_previews

OUT = ROOT / 'knowledge/library-v4/atlas-techniques'
SOURCE_PATH = ROOT.parent / '巴黎建筑素材/巴黎民居街区4[斜面建筑].schem'
SOURCE_REL = '巴黎建筑素材/巴黎民居街区4[斜面建筑].schem'
SOURCE_ID = 'street4'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'
MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'

PARTS = [
    {
        'id': 'st4-prow-base', 'bbox': [44, 0, 105, 84, 9, 119],
        'title': '街区4 · 船头尖角基座段（非对称收头与尖端小店）',
        'families': ['diagonal_corner', 'shopfront', 'awning', 'plinth'],
        'outside': 'south/+z（尖端）+ west/-x（西南斜面）+ east/+x（东北斜面）',
        'observation': '楔形楼船头收头实测为非对称：西南斜面于 z≈111 以端柱平收，东北斜面继续绕合，'
                       '以约 45° 阶梯包角（自 (78,105) 收至 (73,118)，进深约 10）包住尖端，'
                       '两壳体立面之间的内腔在南端敞开（源即壳体做法）；尖端绕合段根开独立小店：'
                       '诡异木台阶雨棚（warped_slab[type=top]，y5）+抛光闪长岩半砖压顶（y6）'
                       '+闪长岩墙/铁活板/铁栏/枯珊瑚扇窗面（y11-14），西南尾段亦带诡异木雨棚店面残段。'
                       '基座全落地 y=0，无地形高差。',
        'constraint': '尖端收头是不对称做法：45° 包角只在东北面，西南面平收，拼接时保持两段立面错位与'
                      '内腔敞口；裁切边界 z=105 切断两侧长立面，连接态冻结入账，粘贴须关方块更新。',
        'finding': None,
    },
    {
        'id': 'st4-prow-body', 'bbox': [44, 9, 105, 84, 31, 119],
        'title': '街区4 · 船头尖角主体段（斜端三面开窗）',
        'families': ['diagonal_corner', 'window_surround', 'pilaster', 'string_course'],
        'outside': 'south/+z（尖端）+ west/-x（西南斜面）+ east/+x（东北斜面）',
        'observation': '尖角主体三个面：西南斜面尾段（端柱平收 z≈111）、东北斜面尾段与 45° 绕合包角（z≈112-118）；'
                       '两面均按开间开窗：外层砂岩墙薄墩+三道铁栏窗台（y13/19/25）+枯珊瑚扇花箱（y14）'
                       '+拉杆牛腿（y16/22/28）+桦木活板横梃带（y17/23/29），窗芯去皮白桦木板、内衬深板岩；'
                       '包角段开间随阶梯错位、窗轴竖直；内缘共墙肋（深板岩/白桦木通高）在件内。'
                       'y29-31 为活板带+砂岩檐口起线。',
        'constraint': '包角段开间随墙阶梯错位，窗轴竖向不变；与 prow-base、prow-rooftip 上下叠合使用；'
                      '裁切面 z=105 处栏杆与墙面连接冻结，拼接时需延续或做端头。',
        'finding': None,
    },
    {
        'id': 'st4-prow-rooftip', 'bbox': [44, 31, 105, 84, 48, 119],
        'title': '街区4 · 船头屋顶尖端（曼萨德坡汇聚与屋脊收头）',
        'families': ['roof_slope', 'ridge', 'chimney', 'finial'],
        'outside': 'roof（尖端朝南）',
        'observation': '曼萨德屋面在尖端上方合拢成攒尖顶帽：两长坡沿斜墙收窄，y43 双脊留谷、y44 合拢，'
                       '盖住两壳体立面间的内腔（腔体在南端以下敞开，源即如此）；檐口链（y32）与屋脊链（y42-43）'
                       '挂边（已改名 iron_chain），雪片/枯珊瑚扇/铁栏点缀坡面；尖端两组烟囱'
                       '（z≈103-105 x66-69、z≈109-110 x64-67）立屋脊：根系土/泥土基座+花岗岩墙（up=true）'
                       '+红色花盆收头（y44-48）；东北坡高处有深板岩小老虎窗。',
        'constraint': '屋脊在尖端并合为一点，不可延伸过端墙；烟囱花盆为冻结装饰态；与 prow-body 上下叠合。',
        'finding': None,
    },
    {
        'id': 'st4-corner-rounded-body', 'bbox': [88, 0, 1, 109, 30, 18],
        'title': '街区4 · 圆角转角楼主体（基座紧弧+主体弓形外鼓）',
        'families': ['outer_corner', 'shopfront', 'window_surround', 'pilaster'],
        'outside': 'north/-z + east/+x（圆角朝东北）',
        'observation': '东北圆角以两级半径逼近：基座（y0-6）弧紧（外缘 x≈102，弧柱为 create 方解石墙），'
                       '主体（y7-29）向外鼓 4-5 格（外缘 x≈107），均以 1-2 格阶梯走四分之一弧；'
                       '基座店面为深板岩+深色橡木活板橱窗带绕弧（北面临街 |T##T| 开间、东面玻璃橱窗通高 y0-11）；'
                       '主体每层沿弧阶梯错位开窗（铁门薄窗+白玻璃背衬），砂岩墙薄墩分隔，弧上窗轴竖直。',
        'constraint': '含 create:cut_calcite_wall 模组方块（基座弧柱与店面条带），原版装配需替换白色墙类；'
                      '主体弓形外鼓与基座紧弧的退台关系是读法关键；西、南裁切面连接冻结。',
        'finding': None,
    },
    {
        'id': 'st4-corner-rounded-cap', 'bbox': [77, 30, 1, 109, 44, 28],
        'title': '街区4 · 圆角转角楼顶帽（绕弧曼萨德+玻璃采光井）',
        'families': ['outer_corner', 'dormer', 'parapet', 'roof_slope', 'ridge'],
        'outside': 'roof（圆角朝东北）',
        'observation': '顶帽绕弧走曼萨德：北坡 y31 铁门暗窗老虎窗、y35-37 桦木活板老虎窗，东坡同制绕弧；'
                       'y39 一周深色橡木活板檐带绕角压边；中央采光井（x≈80-97，z≈12-27）井口以白玻璃板镶边（y39），'
                       '井口盖板为 create 切闪长岩半砖（y41）；顶帽西缘以共墙（x≈76-80，升至 y43）与邻楼相隔。',
        'constraint': '含 create:cut_diorite_slab（y41 井盖板）与少量 create 墙类；采光井玻璃镶边是屋面开口收头，'
                      '勿封堵；与 corner-rounded-body 上下对位叠合。',
        'finding': None,
    },
    {
        'id': 'st4-shopfront-white', 'bbox': [18, 0, 1, 49, 9, 7],
        'title': '街区4 · 白色三联店面（潜影盒展台+红玻璃点缀+挂牌）',
        'families': ['shopfront', 'sign_band', 'mullion', 'transom'],
        'outside': 'north/-z',
        'observation': '西楼北面临街三联白色店面，每联 8 格宽：白色潜影盒展台（三格成组）+白玻璃橱窗（y1-4）'
                       '+白混凝土门脸柱，联间灰色羊毛立柱（y0-4）嵌红色玻璃砖点缀（y6），'
                       '两联内各一根红木门柱（mangrove_door[facing=east] 于 x23/x38、z=5 叠三格全 half=lower，'
                       '朱红色门扇视觉）；门脸上方桦木栅栏檐口（z2）挂桦木/红木告示牌招牌（两联各一组），'
                       '桦木活板挑檐（y7-8）；其余店门为铁门/桦木门叶（half=lower 源冻结态，桦木门 lower/upper 成对）。',
        'constraint': '潜影盒与告示牌为方块实体，导出仅保留方块几何（NBT 在 source-nbt-context.json）；'
                      '灰色羊毛立柱是开间分隔，复用保持 8 格开间模数。',
        'finding': None,
    },
    {
        'id': 'st4-shopfront-red', 'bbox': [53, 0, 1, 77, 9, 7],
        'title': '街区4 · 深色店面带朱红门柱（黑羊毛招牌带+系桩）',
        'families': ['shopfront', 'sign_band', 'door', 'plinth'],
        'outside': 'north/-z',
        'observation': '中楼北面深色店面：裂深板岩砖门脸柱与基座，黑色羊毛通长招牌带（y5-6），'
                       '两联朱红门柱（mangrove_door 于 x60-61/63-64、z=4 叠六格 y0-5：仅 y0-1 为 lower/upper 配对，'
                       'y2-5 全部 half=lower 冻结态，组成 2 宽 6 高红色门洞视觉）与铁门橱窗开间相间；'
                       '门前街道一排磨制深板岩墙系桩（z2，y0-2，间距约 4 格）；店上接桦木活板层间带（y7-8）。'
                       '东缘 x77 起为转角楼 create 方解石墙共墙带，已排除出包围盒。',
        'constraint': '朱红门柱大部分为 half=lower 源冻结态，禁当可开启门洞；系桩属街道设施，'
                      '拼接时与建筑立面线对位。',
        'finding': None,
    },
    {
        'id': 'st4-shopfront-awning', 'bbox': [59, 0, 67, 70, 13, 81],
        'title': '街区4 · 楔形楼西南斜面绿色雨棚店面',
        'families': ['shopfront', 'awning', 'sign_band', 'mullion'],
        'outside': 'west/-x（西南斜面）',
        'observation': '西南斜面底层店面：诡异木活板雨棚（warped_trapdoor 关闭平贴态，y4-5，八格连续，青绿色）'
                       '+ y12 白混凝土招牌带，橱窗白混凝土门框内退 1-2 格、深色竖梃分隔；'
                       '店面随斜墙每 3-4 格内收 1 格阶梯，雨棚与招牌带同步阶梯错位。'
                       '同类雨棚西南面共三处（z≈44-51/70-77/96-103）、东北面三处，本件取 z≈70-77 一处。',
        'constraint': '斜墙阶梯使店面左右边界不在同一 x，复用时按斜面模数错位；雨棚活板为关闭平贴冻结态，'
                      '粘贴须关更新。',
        'finding': None,
    },
    {
        'id': 'st4-window-bay-noble', 'bbox': [19, 17, 1, 25, 25, 7],
        'title': '街区4 · 西楼贵族层窗开间（双开铁门高窗+铁栏小阳台）',
        'families': ['window_surround', 'railing', 'sill', 'string_course'],
        'outside': 'north/-z',
        'observation': '西楼北面贵族层开间（y17-24）：两格宽铁门薄窗前后两层朝向相对（half=lower 冻结态，y19-22），'
                       '窗脚 y18 铁栏+桦木栅栏挑出小阳台（z2），窗头 y23 层间带，两侧砂岩墙薄墩；'
                       '上接标准层铁栏窗台（y24），下接连续阳台带顶（y17）。',
        'constraint': '薄窗面双层铁门做法禁当真门洞；小阳台挑出 1 格与窗开间绑定，不可上移下挪。',
        'finding': None,
    },
    {
        'id': 'st4-window-bay-wedge', 'bbox': [61, 12, 62, 70, 33, 69],
        'title': '街区4 · 楔形楼斜面标准窗开间（三层叠置）',
        'families': ['window_surround', 'pilaster', 'railing', 'string_course'],
        'outside': 'west/-x（西南斜面）',
        'observation': '西南斜面开间三层叠置（y13-30）：外层砂岩墙薄墩+三道铁栏窗台（y13/19/25）'
                       '+枯珊瑚扇花箱（y14）+拉杆牛腿（y16/22/28）+桦木活板横梃带（y17/23/29），'
                       '窗芯衬去皮白桦木板，内衬深板岩；墙随斜面阶梯内收，开间竖轴不变；顶接 y31 檐口与 y32 檐口链。',
        'constraint': '斜面开间左右缘阶梯错位，窗轴保持竖直；花箱/牛腿/横梃是三层重复模块，'
                      '不可省略成单格窗洞。',
        'finding': None,
    },
    {
        'id': 'st4-balcony-band', 'bbox': [84, 12, 1, 109, 21, 16],
        'title': '街区4 · 转角楼绕角连续带（橡木楼梯带+砂轮齿饰+讲台栏柱）',
        'families': ['balcony_slab', 'railing', 'bracket', 'string_course'],
        'outside': 'north/-z + east/+x（绕角）',
        'observation': '转角楼贵族层窗脚的绕角连续带：y13 砂轮（grindstone）齿饰与绊线钩纹样带，'
                       'y14 橡木楼梯通长带（北面—弧—东面连续，外唇 oak_trapdoor 平贴）绕角，'
                       '其上 y15-18 铁活板深色窗面开间，y19 拉杆/枯角珊瑚/绊线钩线脚，'
                       'y20 桦木半砖+墙面告示牌+讲台（lectern）成组栏柱收头；带在弧上随 1-2 格阶梯错位绕角、'
                       '标高不变。直线通长阳台带另见 st4-balcony-band-straight。',
        'constraint': '绕角带标高不变而平面随弧错位，复用时保持楼梯带绕角连续；讲台/告示牌为方块实体'
                      '（NBT 在 source-nbt-context.json）；弧上含 create 方解石墙零星格，已标追溯专用。',
        'finding': None,
    },
    {
        'id': 'st4-balcony-band-straight', 'bbox': [18, 7, 1, 35, 19, 7],
        'title': '街区4 · 西楼直线连续阳台带（台面板+讲台栏柱+黑板压顶）',
        'families': ['balcony_slab', 'railing', 'bracket', 'string_course'],
        'outside': 'north/-z',
        'observation': '西楼北面通长阳台带（17 格）：y8-9 悬挑台面板+桦木栅栏立柱贯通，'
                       'y15 栅栏门（open=true 平贴态）栏花+铁栏，y16 讲台（lectern）成对作栏柱，'
                       'y17 磨制黑石压力板（powered=true 冻结态）作通长压顶，y18 铁栏栏杆；'
                       '带后为标准层双层铁门薄窗，y12 拉杆成排作窗头牛腿。绕角连续带另见 st4-balcony-band。',
        'constraint': '压力板 powered=true 与栏门 open 平贴均为禁更新冻结态；台面板悬挑 1 格靠墙内拉杆承托。',
        'finding': None,
    },
    {
        'id': 'st4-roof-section', 'bbox': [52, 28, 63, 88, 47, 69],
        'title': '街区4 · 楔形楼曼萨德横剖条（双坡+双脊并合）',
        'families': ['roof_slope', 'ridge', 'cornice', 'dormer'],
        'outside': '剖面：西南/-x 坡 + 东北/+x 坡',
        'observation': '楔形楼横剖（z≈63-68，穿过一个共墙烟囱档）：两壳体立面（外层装饰层+白桦木芯+深板岩内衬）'
                       '→ 檐口（y29-31 桦木活板带+砂岩檐板+拉杆牛腿）→ 陡坡（y31-41，深板岩杂混肌理，'
                       '每 1-2 层内收 1 格，坡面饰雪片/枯珊瑚扇/铁栏/桦木栅栏，东北坡高处带闪长岩颊小老虎窗）'
                       '→ 檐口链（y32）与屋脊链（y42-43，已改名 iron_chain）→ 双脊并合（y43 两脊留谷、'
                       'y44 合拢成 M 形顶峰）→ 屋脊种植床（泥土/根系土）与花岗岩烟囱基座（y44-46，'
                       '花盆柱在剖外两侧）。',
        'constraint': '双脊并合（M 形顶峰）是楔形楼屋面特征，不可简化为单脊；本剖穿过烟囱档，'
                      '屋脊烟囱整组另见 st4-chimney 与 st4-prow-rooftip。',
        'finding': None,
    },
    {
        'id': 'st4-dormer-lower', 'bbox': [19, 30, 1, 23, 35, 10],
        'title': '街区4 · 西楼下排老虎窗（白玻璃亮窗+铁栏）',
        'families': ['dormer', 'window_surround', 'railing'],
        'outside': 'north/-z',
        'observation': '西楼曼萨德下排老虎窗（y31-33）：两格宽白玻璃亮窗（white_stained_glass 整玻璃，z7 背衬）'
                       '前叠铁门暗窗（z5），白色框料，窗前三面铁栏围挡（y31，z3），'
                       '窗脚前缘深色橡木活板带（y31-35），顶接桦木檐板；嵌陡坡脚，与上排老虎窗同轴成组。',
        'constraint': '亮窗是整玻璃+暗门双层做法（st1 为全暗窗，透明度分级不同）；与上排共用竖轴，'
                      '单件截取注意上方还有一排。',
        'finding': None,
    },
    {
        'id': 'st4-dormer-upper', 'bbox': [23, 33, 1, 27, 39, 10],
        'title': '街区4 · 西楼上排老虎窗（深颊板+玻璃板亮窗）',
        'families': ['dormer', 'window_surround'],
        'outside': 'north/-z',
        'observation': '西楼曼萨德上排老虎窗（y35-37）：深板岩砖颊板窗亭，两格宽白框开口内铁门暗窗'
                       '+白玻璃板背衬，深色半砖小脊压顶，前缘深色橡木活板檐带（y35）；立坡折上方缓坡，'
                       '与下排（y31-33）组成双排制——下排白框整玻璃、上排深颊板玻璃板，'
                       '颊板材料与透明度按高度分级。',
        'constraint': '上排落缓坡段，位置由坡折决定；与下排同轴成组使用。',
        'finding': None,
    },
    {
        'id': 'st4-chimney', 'bbox': [25, 39, 8, 35, 49, 14],
        'title': '街区4 · 西楼屋脊烟囱组（叠层石柱+花岗岩墙+红花盆）',
        'families': ['chimney', 'chimney_cap', 'ridge'],
        'outside': 'roof',
        'observation': '西楼屋脊（z10-12）烟囱组：石砖/石头/安山岩逐层换材叠柱（y41-45）'
                       '+ 花岗岩墙单柱（up=true，y46）+ 红色花盆收头（y47）；两柱一组（x27/32，'
                       '另组 x42/47 在剖外），根部与屋脊板岩咬合；同法见于楔形楼屋脊各组（花岗岩+根系土基座）。',
        'constraint': '花盆为冻结装饰收头；叠柱材质逐层变化是肌理一部分，勿统一替换。',
        'finding': None,
    },
]


FINDINGS = {
    'st4-prow-base': '七视角确认：西南斜面尾段（带绿雨棚店面残段）与东北面 45° 绕合包角、尖端独立小店'
                     '（诡异台阶雨棚+闪长岩窗面）齐全；两壳体立面间内腔南端敞口为源有壳体做法，已在观察中注明。',
    'st4-prow-body': '七视角确认：尖角三面开间（西南尾段、东北尾段、45° 包角段）与斜墙阶梯错位、'
                     '竖向窗轴、内缘共墙肋完整；顶部檐口起线在件内，与 prow-base/rooftip 叠合关系成立。',
    'st4-prow-rooftip': '七视角确认：双坡在尖端上方合拢成攒尖顶帽、屋脊链挂边、花岗岩烟囱墙与红花盆收头、'
                        '坡面铁栏/雪片/珊瑚装饰完整；top 视角可见脊线向尖端收窄。',
    'st4-corner-rounded-body': '七视角确认：基座紧弧与主体弓形外鼓两级半径、绕弧开间、深色店面带与'
                               '东面玻璃橱窗完整可读；模组弧柱已标注。',
    'st4-corner-rounded-cap': '七视角确认：绕弧曼萨德、北/东坡老虎窗、y39 深色活板檐带绕角、'
                              '玻璃镶边采光井与井盖板齐全；模组半砖已标注。',
    'st4-shopfront-white': '七视角确认：三联店面潜影盒展台、白玻璃橱窗、灰羊毛开间柱嵌红玻璃、'
                           '红木门柱与挂牌檐口完整；含 y7-8 活板挑檐作上边界。',
    'st4-shopfront-red': '七视角确认：两联朱红门柱（六格高）、黑羊毛招牌带、铁门橱窗开间、'
                         '门前系桩与上部活板层间带完整；东缘共墙带已排除。',
    'st4-shopfront-awning': '七视角确认：绿色诡异木雨棚一完整开间、白混凝土招牌带、内退橱窗与深色竖梃齐全；'
                            '含相邻开间边缘作斜面错位参照。',
    'st4-window-bay-noble': '七视角确认：贵族层高窗双层薄窗面、挑出小阳台（铁栏+黑板压顶）、'
                            '两侧薄墩与上下层间带齐全。',
    'st4-window-bay-wedge': '七视角确认：斜面开间三层叠置模块（薄墩/铁栏/花箱/拉杆/活板横梃）完整，'
                            '白桦木窗芯与深板岩内衬、檐口起线与檐口链在件内。',
    'st4-balcony-band': '七视角确认：y14 橡木楼梯带自北面绕弧至东面连续不断、砂轮齿饰与绊线钩带、'
                        '活板唇边、上方告示牌/讲台栏柱组完整一段；top 视角可见带随弧阶梯错位。',
    'st4-balcony-band-straight': '七视角确认：17 格通长阳台带的台面板、铁栏、讲台栏柱、黑板压顶、'
                                 '栅栏门栏花与拉杆牛腿连续可读，带后薄窗完整。',
    'st4-roof-section': '七视角确认：横剖双壳体立面、双坡、双脊并合、屋脊种植床与烟囱基座、'
                        '檐口链/脊链齐全；东北坡闪长岩颊小老虎窗作参照。',
    'st4-dormer-lower': '七视角确认：下排亮窗老虎窗整玻璃+暗门双层、白色框料、三面铁栏与前缘活板带完整。',
    'st4-dormer-upper': '七视角确认：上排深颊板老虎窗、白框玻璃板亮窗、深色半砖小脊与前缘活板带完整。',
    'st4-chimney': '七视角确认：两柱一组叠层石柱（逐层换材）、花岗岩墙单柱、红花盆收头与屋脊石板基盘完整。',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT.parent).as_posix()


def context_entities(data, bbox):
    kept = []
    for entry in data.block_entities:
        entry = _plain(entry)
        pos = entry.get('Pos', entry.get('pos'))
        if pos is not None and len(pos) == 3 and all(bbox[i] <= int(pos[i]) < bbox[i + 3] for i in range(3)):
            kept.append(entry)
    return {'block_entities_in_crop': kept, 'source_block_entity_count': len(data.block_entities),
            'policy': 'source NBT retained here as context; exported schematics carry block geometry only',
            'source_entities': _plain(data.entities)}


def build_part(data, part, catalog, source_sha, render):
    folder = OUT / part['id']
    folder.mkdir(parents=True, exist_ok=True)
    raw, cleaned, offset, cleaning = crop(data, part['bbox'])
    original_inventory = inventory(cleaned)
    cleaned, migrations = migrate_to_12111(cleaned, offset)
    cleaning['version_migrations'] = migrations
    cleaning['changed_nonair_cells'] = len(migrations)
    cleaning['policy'] = 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES'
    for filename, grid in [('source-crop.schem', raw), ('detail.schem', cleaned)]:
        volume, palette = encode(grid)
        write_schematic(folder / filename, volume, palette, name=part['id'],
                        data_version=data.data_version if filename == 'source-crop.schem' else 4671)
    read = load_schematic(folder / 'detail.schem')
    actual = np.asarray(read.id_to_state, dtype=object)[read.volume]
    transformed_equal = bool(np.array_equal(actual, cleaned))
    reverted = cleaned.copy()
    for change in migrations:
        x, y, z = change['local_xyz']
        reverted[y, z, x] = change['before']
    raw_read = load_schematic(folder / 'source-crop.schem')
    raw_grid = np.asarray(raw_read.id_to_state, dtype=object)[raw_read.volume]
    source_equal = bool(np.array_equal(raw_grid, raw))
    pad = cleaning['removed_air_padding_xyz']
    (sx, ex), (sy, ey), (sz, ez) = pad
    trimmed = raw_grid[sy:raw_grid.shape[0] - ey, sz:raw_grid.shape[1] - ez, sx:raw_grid.shape[2] - ex]
    only_documented = bool(np.array_equal(trimmed, reverted))
    if not source_equal or not transformed_equal or not only_documented:
        raise ValueError('Export changed source states: ' + part['id'])
    load_validation = read.validation()
    if load_validation['status'] != 'PASS':
        raise ValueError('Detail schematic failed load validation: ' + part['id'])
    dump_json(folder / 'source-nbt-context.json', context_entities(data, part['bbox']))
    registry = folder / 'registry.json'
    result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'),
                             str(folder / 'detail.schem'), str(registry)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    check = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'status': 'FAIL', 'issues': [result.stderr]}
    inv = inventory(cleaned)
    vanilla = check['status'] == 'PASS'
    record = {
        'id': part['id'], 'title': part['title'], 'bbox': part['bbox'],
        'source': SOURCE_REL, 'source_id': SOURCE_ID, 'source_sha256': source_sha,
        'source_bbox_xyz_half_open': part['bbox'], 'clean_origin_source_xyz': offset,
        'parent': SOURCE_ID, 'outside': part['outside'],
        'observation': part['observation'], 'constraint': part['constraint'], 'families': part['families'],
        'inventory': inv, 'source_inventory': original_inventory, 'cleaning': cleaning,
        'state_context': state_context(data, cleaned, offset),
        'library_matches': family_matches(part['families'], inv['exact_states'], catalog),
        'schematic': relative(folder / 'detail.schem'), 'schematic_sha256': digest(folder / 'detail.schem'),
        'raw_schematic': relative(folder / 'source-crop.schem'),
        'validation': {'source_states_equal': source_equal, 'documented_transform_equal': transformed_equal,
                       'detail_differs_from_source_crop_only_at_documented_cells': only_documented,
                       'load_validation': load_validation['status'],
                       'registry_status': check['status'], 'registry_issues': check.get('issues', []),
                       'game_acceptance': 'NOT_RUN'},
        'claim_status': 'SOURCE_STATES_VERIFIED_SEMANTICS_ANNOTATED',
        'role_review': 'PENDING_VISUAL_REVIEW',
        'compatible_vanilla': vanilla,
        'compatibility_note': VANILLA_NOTE if vanilla else MODDED_NOTE,
        'entity_scope': 'block geometry only; source NBT in source-nbt-context.json',
    }
    if part.get('finding') or FINDINGS.get(part['id']):
        record['role_review'] = {'reviewer': 'agent visual inspection', 'reviewer_type': 'agent',
                                 'decision': 'ANNOTATED_REFERENCE',
                                 'finding': part.get('finding') or FINDINGS[part['id']],
                                 'game_acceptance': 'NOT_RUN'}
        record['claim_status'] = 'SOURCE_STATES_VERIFIED_VISUALLY_INTERPRETED'
    dump_json(folder / 'record.json', record)
    if render:
        metadata = folder / 'previews/render_cache.json'
        cached = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
        if cached.get('schematic_sha256') != record['schematic_sha256']:
            render_previews(folder / 'detail.schem', folder / 'previews', max_size=700)
            dump_json(metadata, {'schematic_sha256': record['schematic_sha256'], 'views': VIEWS})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'knowledge/library-v1/catalog.json').read_text(encoding='utf-8'))
    data = load_schematic(SOURCE_PATH)
    source_meta = {'id': SOURCE_ID, 'path': SOURCE_REL, 'name': SOURCE_PATH.name, 'sha256': digest(SOURCE_PATH),
                   'data_version': data.data_version, 'dimensions_whd': [data.width, data.height, data.length],
                   'nonair': int(data.nonair_mask().sum()), 'air_palette_ids': data.air_ids.tolist(),
                   'slope_note': '全楼落地 y=0，无地形高差；“斜面”指平面斜向（楔形总图），st4-slope-base 为否定结论不入件。',
                   'layout_note': '北侧横排三栋（西楼白店面+直线连续阳台带+双排老虎窗+屋脊烟囱；中楼深色店面带朱红门柱；'
                                  '东端圆角转角楼带绕角连续带、曼萨德顶帽与玻璃采光井）+ 斜向楔形长楼'
                                  '（两侧壳体立面、诡异木雨棚店面、双脊曼萨德、船头非对称收头：西南平收+东北 45° 绕合包角）。'}
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        record = build_part(data, part, catalog, source_meta['sha256'], args.render)
        records.append(record)
        print(part['id'], record['inventory']['dimensions_whd'], record['inventory']['nonair'],
              record['validation']['registry_status'], 'migrations', len(record['cleaning']['version_migrations']),
              flush=True)
    index = {'schema': 'atlas-techniques-v4-street4',
             'coordinate_convention': 'source-local xyz; bbox [x0,y0,z0,x1,y1,z1], upper bounds exclusive',
             'source': source_meta,
             'cleaning_policy': 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES',
             'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
             'game_acceptance': 'NOT_RUN',
             'negative_findings': [
                 {'id': 'st4-slope-base', 'topic': '坡地基座处理',
                  'finding': '逐 z 实测（probe_street4_d.txt 节 F）：楔形楼两条立面与尖端全部落地 y=0，'
                             '店面与层线沿斜面无高差变化；源内不存在坡地基座处理，'
                             '“斜面建筑”指平面斜向（楔形总图与斜墙阶梯），故不入裁件。'},
             ],
             'parts': [{'id': r['id'], 'title': r['title'], 'bbox': r['source_bbox_xyz_half_open'],
                        'dimensions_whd': r['inventory']['dimensions_whd'], 'nonair': r['inventory']['nonair'],
                        'families': r['families'], 'outside': r['outside'],
                        'compatible_vanilla': r['compatible_vanilla'],
                        'schematic': r['schematic'], 'record': relative(OUT / r['id'] / 'record.json')}
                       for r in records]}
    dump_json(OUT / 'index-street4.json', index)
    print('index-street4.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
