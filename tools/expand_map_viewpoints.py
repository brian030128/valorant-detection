"""Additional ray-checked camera positions; preserve original catalog IDs and map geometry."""
import bpy,json,sys,math,random,hashlib,time
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import bisect
import numpy as np
args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]).resolve();out=Path(args[1]).resolve();out.mkdir(parents=True,exist_ok=True)
base=json.loads((out/'viewpoints.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
# Omit enormous sky domes and non-renderable helpers; retain architectural vistas.
removed=[]
for o in list(bpy.data.objects):
 if o.type!='MESH' or max(o.dimensions)>1500 or any(k in o.name.lower() for k in ['skydome','sky_sphere','skybox','blockingvolume','navmesh','lightleak','light_leak','collision']):
  removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
objects=[o for o in bpy.context.scene.objects if o.type=='MESH'];core=[o for o in objects if not any('vista' in c.name.lower() for c in o.users_collection)]
points=np.array([tuple(o.matrix_world@Vector(v)) for o in core for v in o.bound_box])
lo=np.quantile(points,.01,axis=0);hi=np.quantile(points,.99,axis=0)
lo[2]=max(lo[2],-30);hi[2]=min(hi[2],80)
print('CORE_BOUNDS',lo.tolist(),hi.tolist(),'meshes',len(objects),flush=True)
cached_views = False
if cached_views:
 data=json.loads((out/'viewpoints.json').read_text());candidates=data['candidates'];usable=data['views']
else:
 bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();scene=bpy.context.scene
 # One world-space BVH avoids Blender scene.ray_cast traversing thousands of instances per query.
 vertices=[];triangles=[];face_ends=[];ray_objects=[]
 for oi,o in enumerate(objects):
  mesh=o.data;mesh.calc_loop_triangles()
  coords=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',coords);coords=coords.reshape(-1,3)
  matrix=np.array(o.matrix_world);coords=coords@matrix[:3,:3].T+matrix[:3,3]
  indices=np.empty(len(mesh.loop_triangles)*3,dtype=np.int32);mesh.loop_triangles.foreach_get('vertices',indices);indices=indices.reshape(-1,3)+len(vertices)
  vertices.extend(map(tuple,coords));triangles.extend(map(tuple,indices));face_ends.append(len(triangles));ray_objects.append(dict(name=o.name,collections=[c.name for c in o.users_collection]))
  if oi%2000==0:print('BVH_GEOMETRY',oi,len(triangles),flush=True)
 bvh=BVHTree.FromPolygons(vertices,triangles,all_triangles=True);del vertices,triangles
 print('BVH_READY',flush=True)
 def ray(origin,direction,distance):
  loc,normal,face,dist=bvh.ray_cast(origin,direction,distance)
  if loc is None:return False,None,None,None,None,None
  obj=ray_objects[bisect.bisect_right(face_ends,face)]
  return True,loc,normal,face,obj,None
 rng=random.Random(1942871);candidates=[];seen=set()
 step=1.75
 for xi,x in enumerate(np.arange(lo[0],hi[0],step)):
  for y in np.arange(lo[1],hi[1],step):
   origin=Vector((float(x)+rng.uniform(-.6,.6),float(y)+rng.uniform(-.6,.6),float(hi[2])+2))
   for level in range(14):
    hit,loc,normal,face,obj,matrix=ray(origin,Vector((0,0,-1)),distance=float(hi[2]-lo[2]+5))
    if not hit or loc.z<lo[2]-1:break
    if normal.z>.72 and not any('vista' in name.lower() for name in obj['collections']) and any(k in obj['name'].lower() for k in ['ground','floor','stairs','stair','steps','ramp','path','walk','road','pavement','terrain','platform','bridge']) and not any(k in obj['name'].lower() for k in ['roof','ceiling']):
     # Body clearance and an open eye position; actual silhouettes are checked during rendering.
     start=loc+Vector((0,0,.06));up=ray(start,Vector((0,0,1)),distance=2.3)[0]
     key=(round(loc.x,1),round(loc.y,1),round(loc.z,1))
     if not up and key not in seen:
      seen.add(key);candidates.append(dict(point=list(loc),region=f'{math.floor(loc.x/8)}_{math.floor(loc.y/8)}_{math.floor(loc.z/4)}',surface=obj['name'],collection=obj['collections']))
    origin=loc-Vector((0,0,.08))
  if xi%20==0:print('GROUND_SCAN',xi,len(candidates),flush=True)
 assert len(candidates)>200,len(candidates)
 # Each camera has several target locations, across both distance and viewing direction.
 coords=np.array([c['point'] for c in candidates]);usable=[]
 for i,c in enumerate(candidates):
  delta=coords-coords[i];dist=np.linalg.norm(delta[:,:2],axis=1)
  nearby=np.flatnonzero((dist>=4)&(dist<=45)&(np.abs(delta[:,2])<4.5)).tolist();rng.shuffle(nearby)
  targets=[];eye=Vector(c['point'])+Vector((0,0,1.65))
  for j in nearby[:180]:
   aim=Vector(candidates[j]['point'])+Vector((0,0,1.5));direction=aim-eye
   hit=ray(eye,direction.normalized(),distance=max(.01,direction.length-.5))[0]
   if not hit:targets.append(j)
   if len(targets)>=24:break
  if len(targets)>=3:usable.append(dict(candidate=i,targets=targets))
  if i%500==0:print('VIEWPOINT_SCAN',i,len(usable),flush=True)
 assert len(usable)>100,len(usable)
 offset=len(base['candidates']); original_views=len(base['views'])
 base['candidates'].extend(candidates)
 base['views'].extend(dict(candidate=v['candidate']+offset,targets=[t+offset for t in v['targets']]) for v in usable)
 base['expansion']=dict(seed=1942871,grid_step_meters=1.75,original_views=original_views,added_views=len(usable),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
 (out/'viewpoints_expanded.json').write_text(json.dumps(base,separators=(',',':')))
 print('VIEWPOINTS_READY',len(candidates),len(usable),flush=True)

print('VIEWPOINT_EXPANSION_COMPLETE',out,flush=True)
