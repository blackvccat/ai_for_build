"""Reusable facade recipes, with complete states and explicit derivation labels.

Recipes are new combinations; source crops are retained separately and are never
silently converted into recipes or claimed to have survived Minecraft updates.
"""
from .architecture import ComponentDefinition, state

FAMILIES = {
 'plinth':'勒脚', 'basement_vent':'地下通风口', 'rustication':'锈石',
 'masonry_joint':'墙面分缝', 'string_course':'层间带', 'pilaster':'壁柱', 'quoin':'转角石',
 'window_recess':'窗洞', 'window_surround':'窗套', 'sill':'窗台',
 'transom':'横梃', 'mullion':'竖梃', 'shutter':'百叶', 'pediment':'山花', 'arch':'拱顶',
 'door':'门', 'portal':'入口门廊', 'shopfront':'店面', 'sign_band':'招牌带',
 'awning':'雨棚', 'balcony_slab':'阳台板', 'railing':'栏杆', 'balustrade':'栏板',
 'bracket':'托臂', 'corbel':'牛腿', 'planter':'花箱', 'cornice':'檐口',
 'parapet':'女儿墙', 'roof_slope':'屋面坡段', 'ridge':'屋脊', 'dormer':'老虎窗',
 'gutter':'天沟', 'downpipe':'落水管', 'chimney':'烟囱', 'chimney_cap':'烟囱帽',
 'roof_ornament':'屋顶小构筑物', 'finial':'装饰柱及收头',
 'outer_corner':'外角', 'inner_corner':'内角', 'diagonal_corner':'45度转角',
 'courtyard_return':'院落回折', 'roof_junction':'立面屋顶交接',
 'light_baffle':'遮光', 'glass_backing':'玻璃背衬', 'visible_interior':'可见室内进深'
}

def slab(material='smooth_sandstone',kind='bottom'):
    return state(material+'_slab',type=kind,waterlogged='false')

def stair(material='smooth_sandstone',facing='north',half='top',shape='straight'):
    return state(material+'_stairs',facing=facing,half=half,shape=shape,waterlogged='false')

def wall(material='sandstone',east='low',west='low',north='none',south='none',up='false'):
    return state(material+'_wall',east=east,west=west,north=north,south=south,up=up,waterlogged='false')

def pane(material='gray_stained_glass_pane'):
    return state(material,east='true',west='true',north='false',south='false',waterlogged='false')

def trap(material='iron',facing='north',half='bottom',opened='false'):
    return state(material+'_trapdoor',facing=facing,half=half,open=opened,powered='false',waterlogged='false')

def rail(): return pane('iron_bars')

def recipe(family,variant=0,width=3,height=4,evidence=None):
    if family not in FAMILIES: raise ValueError(f'Unknown family {family}')
    if variant not in (0,1,2): raise ValueError('variant must be 0,1,2')
    cells={}
    def p(x,y,z,s): cells[(x,y,z)]=s if ':' in s else 'minecraft:'+s
    def line(y,z,s,x0=0,x1=None):
        for x in range(x0,width if x1 is None else x1): p(x,y,z,s)
    stone=('smooth_sandstone','cut_sandstone','sandstone')[variant]
    wood=('birch','oak','dark_oak')[variant]
    if family in ('plinth','string_course','sill','balcony_slab','cornice','gutter','sign_band'):
        if family=='sign_band':
            line(0,0,('green_terracotta','red_terracotta','brown_terracotta')[variant]); line(1,-1,slab())
        elif family=='gutter':
            line(0,0,stair('oxidized_cut_copper',half='bottom'))
            if variant: line(0,1,slab('deepslate_tile','top'))
            if variant==2:p(0,-1,0,state('iron_chain',axis='y',waterlogged='false'))
        else:
            line(0,0,slab(kind='top' if family=='balcony_slab' else 'bottom'))
            if family in ('cornice','balcony_slab') or variant==1:
                line(0,1,stone)
            if family=='cornice':
                line(-1,1,stair()); line(1,0,slab())
            elif variant==2: line(-1,1,wall())
    elif family in ('rustication','masonry_joint'):
        for y in range(3):
            line(y,1,stone)
            for x in range(width):
                if family=='masonry_joint' or y%2==0:
                    p(x,y,0,wall(east='low' if (x+variant)%3!=2 else 'none',west='low'))
                else: p(x,y,0,stone)
    elif family in ('pilaster','quoin'):
        for y in range(height):
            p(0,y,0,stone if family=='pilaster' or y%2==0 else 'smooth_sandstone')
            if family=='quoin' and (y+variant)%2==0: p(1,y,0,slab(kind='top'))
        p(0,height,0,stair(shape=('straight','outer_left','outer_right')[variant]))
        p(0,-1,0,slab())
    elif family in ('window_recess','window_surround','portal'):
        for y in range(height):
            for x in (-1,width):
                p(x,y,0,stone)
                if variant==2: p(x,y,-1,wall(east='tall' if x<0 else 'none',west='tall' if x>0 else 'none'))
        line(-1,0,slab()); line(height,0,slab())
        if variant==1: line(height+1,1,stone)
        if family=='portal':
            line(height+1,-1,stair()); line(height+2,-1,slab())
    elif family in ('transom','mullion','shutter'):
        if family=='transom':
            line(0,0,trap(wood if variant==2 else 'iron',half='bottom' if variant==1 else 'top'))
        else:
            for y in range(height):
                p(0,y,0,trap(wood if family=='shutter' else 'iron',facing=('east','west','north')[variant],opened='true'))
    elif family in ('pediment','arch'):
        line(0,0,slab())
        centre=(width-1)/2
        for x in range(width):
            rise=max(0,int((width/2-abs(x-centre))/ (2 if variant==0 else 1.5)))
            p(x,rise+1,1,stair(facing='east' if x<centre else 'west',half='bottom',shape='straight'))
        if family=='arch':
            p(-1,-1,0,stair(shape='inner_left'));p(width,-1,0,stair(shape='inner_right'))
        if variant==2:p(width//2,2,0,wall(east='none',west='none',up='true'))
    elif family=='door':
        for x in range(2):
            for y in range(2):
                p(x,y,0,state(wood+'_door',facing='north',half='lower' if y==0 else 'upper',
                    hinge='left' if x==0 else 'right',open='false',powered='false'))
    elif family=='shopfront':
        for y in range(height):
            for x in range(width): p(x,y,1,pane('light_blue_stained_glass_pane'))
        for x in (-1,width):
            for y in range(height+1):p(x,y,0,('polished_deepslate','dark_oak_planks','spruce_planks')[variant])
        line(height,0,('green_terracotta','red_terracotta','brown_terracotta')[variant])
    elif family=='awning':
        for x in range(width):
            for z in (-1,0): p(x,0,z,('green_carpet','red_carpet','brown_carpet')[variant] if x%2==0 else 'white_carpet')
    elif family in ('railing','balustrade','basement_vent'):
        line(0,0,rail() if family!='balustrade' else wall())
        if family=='railing' and variant==1: line(1,0,trap(half='top'))
        elif variant==1:line(1,0,slab())
        elif variant==2:
            for x in (0,width-1):p(x,0,0,state(wood+'_fence_gate',facing='east',in_wall='true',open='true',powered='false'))
    elif family in ('bracket','corbel'):
        p(0,0,0,stair(shape=('straight','outer_left','outer_right')[variant]));p(0,1,0,slab())
        if family=='bracket':p(0,-1,1,wall(east='tall',west='none'))
    elif family=='planter':
        line(0,0,trap(wood,opened='true'))
        line(0,1,'dirt')
        for x in range(width):p(x,1,1,state('azalea_leaves',distance='1',persistent='true',waterlogged='false'))
    elif family in ('parapet','ridge','roof_ornament','finial'):
        if family=='parapet':
            line(0,0,stone);line(1,0,slab())
        elif family=='ridge':
            line(0,0,slab('deepslate_tile','top'))
            if variant: line(1,0,rail())
            if variant==2:
                for x in range(0,width,2):p(x,2,0,wall('deepslate_brick',east='none',west='none',up='true'))
        else:
            p(0,0,0,wall('deepslate_brick',up='true'))
            p(0,1,0,state('lightning_rod',facing='up',powered='false',waterlogged='false'))
            if variant==1:p(0,0,0,slab('deepslate_tile','top'))
            if variant==2:p(0,2,0,state('end_rod',facing='up'))
    elif family in ('roof_slope','roof_junction'):
        for y in range(4):
            line(y,(y*2 if variant==2 else y//(2 if variant==1 else 1)),stair('deepslate_tile',half='bottom'))
        if family=='roof_junction':line(-1,-1,slab('oxidized_cut_copper'))
    elif family=='dormer':
        for y in range(3):
            for x in range(width):p(x,y,1,pane())
            p(-1,y,0,stone);p(width,y,0,stone)
        line(3,0,slab());line(4,1,slab('deepslate_tile'))
        if variant==1:
            for x in range(width):p(x,4+int(x==width//2),1,slab('deepslate_tile'))
        if variant==2:line(3,-1,stair())
    elif family=='downpipe':
        for y in range(height):p(0,y,0,state(('iron_chain','iron_bars','lightning_rod')[variant],
            **({'axis':'y','waterlogged':'false'} if variant==0 else
               {'east':'false','west':'false','north':'false','south':'false','waterlogged':'false'} if variant==1 else
               {'facing':'up','powered':'false','waterlogged':'false'})))
    elif family in ('chimney','chimney_cap'):
        if family=='chimney':
            for y in range(4+variant):
                for z in (0,1):line(y,z,('bricks','stone_bricks','mud_bricks')[variant],0,2)
            for x in (0,1):p(x,4+variant,0,wall('brick',east='none',west='none',up='true'))
        else:
            line(0,0,slab('brick'),0,2)
            for x in (0,1):p(x,1,0,wall(('brick','mud_brick','stone_brick')[variant],east='none',west='none',up='true'))
    elif family in ('outer_corner','inner_corner','diagonal_corner','courtyard_return'):
        for y in range(3):
            for u in range(3):
                p(u,y,u if family=='diagonal_corner' else 0,stone)
                if family!='diagonal_corner':p(0,y,u if family!='inner_corner' else -u,stone)
        if variant==1:
            for u in range(3):p(u,3,u if family=='diagonal_corner' else 0,slab())
        elif variant==2:p(0,3,0,stair(shape='inner_left' if family=='inner_corner' else 'outer_left'))
    elif family in ('light_baffle','glass_backing','visible_interior'):
        for y in range(height):
            line(y,0,('gray_terracotta','tinted_glass','brown_terracotta')[variant] if family!='glass_backing' else ('gray_stained_glass','white_stained_glass','tinted_glass')[variant])
        if family=='visible_interior':
            for z in range(-3,1):line(-1,z,'spruce_planks')
    voxels=[(*xyz,value) for xyz,value in sorted(cells.items())]
    return ComponentDefinition(f'{family}-v{variant+1}',family,variant,voxels,evidence or [],{
        'origin':'DERIVED_COMPOSITION_NOT_SOURCE_COPY','outside':'north/-z',
        'anchor':[0,0,0],'connectors':{'left':[0,0,0],'right':[width-1,0,0]},
        'view_cone':{'preferred':['front','front_left_45','front_right_45'],'failure_views':['rear_without_backing']},
        'scale_range':{'width':[2,7],'height':[2,7]},'lod':'near_detail_with_mid_distance_silhouette',
        'rotation':'quarter_turns_transform_positions_and_properties','mirror':'x_reflection_swaps_chirality',
        'update_policy':'UNTESTED','attachment':'assemble against backing or documented supporting component',
        'occlusion':'rear construction layers hidden by host wall',
        'game_test':'NOT_RUN'})
