"""Run in Blender with --disable-autoexec. Export map geometry/diffuse materials and ray-checked viewpoints."""
import bpy,json,sys,math,random,hashlib,time
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import bisect
import numpy as np
args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]).resolve();out=Path(args[1]).resolve();out.mkdir(parents=True,exist_ok=True)
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
cached_views = '--reuse-viewpoints' in args and (out/'viewpoints.json').exists()
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
 rng=random.Random(817293);candidates=[];seen=set()
 step=2.5
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
  for j in nearby[:100]:
   aim=Vector(candidates[j]['point'])+Vector((0,0,1.5));direction=aim-eye
   hit=ray(eye,direction.normalized(),distance=max(.01,direction.length-.5))[0]
   if not hit:targets.append(j)
   if len(targets)>=12:break
  if len(targets)>=3:usable.append(dict(candidate=i,targets=targets))
  if i%500==0:print('VIEWPOINT_SCAN',i,len(usable),flush=True)
 assert len(usable)>100,len(usable)
 (out/'viewpoints.json').write_text(json.dumps(dict(coordinate_system='Blender Z-up meters; Godot [x,z,-y]',candidates=candidates,views=usable,bounds=[lo.tolist(),hi.tolist()]),separators=(',',':')))
 print('VIEWPOINTS_READY',len(candidates),len(usable),flush=True)
material_report=[]
for mat in list(bpy.data.materials):
 if not mat.use_nodes:continue
 tree=mat.node_tree;groups=[n for n in tree.nodes if n.type=='GROUP'];group=groups[0] if groups else None
 image=None;normal_image=None;tint=[1,1,1,1];uv_scale=1.0
 use_vertex_color=bool(group and group.inputs.get('Use Vertex Color') and group.inputs['Use Vertex Color'].default_value>.5)
 if group:
  for key in ['Normal','Normal A','Normal_NM']:
   socket=group.inputs.get(key)
   if socket and socket.is_linked:
    node=socket.links[0].from_node
    if node.type=='TEX_IMAGE' and node.image:normal_image=node.image;break
 if group:
  for key in ['Diffuse','Diffuse A','Albedo_DF','Diffuse Low','RGBA']:
   socket=group.inputs.get(key)
   if socket and socket.is_linked:
    node=socket.links[0].from_node
    if node.type=='TEX_IMAGE' and node.image:image=node.image;break
  for key in ['DiffuseColor','Tint','Layer A Tint']:
   socket=group.inputs.get(key)
   if socket and not socket.is_linked and hasattr(socket.default_value,'__len__'):
    value=list(socket.default_value)
    if len(value)==4 and max(value[:3])>0:tint=[tint[k]*max(0,min(4,value[k])) for k in range(4)]
 if image is None:
  images=[n.image for n in tree.nodes if n.type=='TEX_IMAGE' and n.image and any(k in n.image.name.lower() for k in ['_df','diffuse','albedo'])]
  image=images[0] if images else None
 if max(tint[:3])<.05:tint=[1,1,1,1]
 mode=float(group.inputs['BLENDMODE'].default_value) if group and group.inputs.get('BLENDMODE') else 2.0
 masked=mode<1.5
 opacity_mask=list(group.inputs['Mask'].default_value) if group and group.inputs.get('Mask') and not group.inputs['Mask'].is_linked else None
 color_mult=list(group.inputs['Color Mult'].default_value) if group and group.inputs.get('Color Mult') else None
 material_report.append(dict(material=mat.name,diffuse=image.name if image else None,normal=normal_image.name if normal_image else None,use_vertex_color=use_vertex_color,tint=tint,masked=masked,original_group=group.node_tree.name if group else None,blend_mode=mode,opacity_mask=opacity_mask,color_mult=color_mult))
 tree.nodes.clear();output=tree.nodes.new('ShaderNodeOutputMaterial');bsdf=tree.nodes.new('ShaderNodeBsdfPrincipled');tree.links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
 bsdf.inputs['Base Color'].default_value=tint;bsdf.inputs['Roughness'].default_value=.85
 if image:
  tex=tree.nodes.new('ShaderNodeTexImage');tex.image=image
  tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
  if use_vertex_color:
   vertex=tree.nodes.new('ShaderNodeVertexColor');mix=tree.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1
   tree.links.new(tex.outputs['Color'],mix.inputs[1]);tree.links.new(vertex.outputs['Color'],mix.inputs[2]);tree.links.new(mix.outputs['Color'],bsdf.inputs['Base Color'])
  if masked:
   if opacity_mask:
    channel=max(range(3),key=lambda k:opacity_mask[k]);separate=tree.nodes.new('ShaderNodeSeparateColor');tree.links.new(tex.outputs['Color'],separate.inputs['Color']);tree.links.new(separate.outputs[channel],bsdf.inputs['Alpha'])
    if color_mult:tree.links.remove(bsdf.inputs['Base Color'].links[0]);bsdf.inputs['Base Color'].default_value=color_mult
   else:tree.links.new(tex.outputs['Alpha'],bsdf.inputs['Alpha'])
 if normal_image:
  normal_tex=tree.nodes.new('ShaderNodeTexImage');normal_tex.image=normal_image
  normal=tree.nodes.new('ShaderNodeNormalMap');tree.links.new(normal_tex.outputs['Color'],normal.inputs['Color']);tree.links.new(normal.outputs['Normal'],bsdf.inputs['Normal'])
 mat.use_backface_culling=False
 if masked and hasattr(mat,'surface_render_method'):mat.surface_render_method='DITHERED'
# Export API options are read from the installed Blender, keeping version compatibility.
props=bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
options=dict(filepath=str(out/'map.glb'),export_format='GLB',export_animations=False,export_cameras=False,export_lights=False,export_yup=True,export_apply=True,export_materials='EXPORT',export_texcoords=True,export_normals=True,export_attributes=False)
for key,value in [('export_vertex_color','ACTIVE'),('export_all_vertex_colors',False),('export_image_format','AUTO')]:
 if key in props:options[key]=value
print('GLB_EXPORT_START',flush=True)
bpy.ops.export_scene.gltf(**{k:v for k,v in options.items() if k in props})
report=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),blender=bpy.app.version_string,meshes=len(objects),removed=removed,materials=material_report,viewpoints=len(usable),regions=len({candidates[v['candidate']]['region'] for v in usable}),conversion='Original geometry, UVs and full-resolution packed diffuse textures; source blend modes and decal opacity respected. Complex layered shaders approximated as diffuse rough materials; not an exact Riot renderer.')
(out/'conversion.json').write_text(json.dumps(report,indent=2));print('MAP_CONVERSION_COMPLETE',out,flush=True)
