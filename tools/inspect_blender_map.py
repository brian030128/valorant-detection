import bpy,json,sys
from pathlib import Path
from mathutils import Vector
args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]);out=Path(args[1]);out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
meshes=[o for o in bpy.data.objects if o.type=='MESH']
points=[o.matrix_world@Vector(v) for o in meshes for v in o.bound_box]
report=dict(blender=bpy.app.version_string,objects=len(bpy.data.objects),meshes=len(meshes),polygons=sum(len(o.data.polygons) for o in meshes),bounds=[[min(v[i] for v in points) for i in range(3)],[max(v[i] for v in points) for i in range(3)]],unit_scale=bpy.context.scene.unit_settings.scale_length,collections=[(c.name,len(c.objects)) for c in bpy.data.collections],images=[dict(name=i.name,size=list(i.size),packed=bool(i.packed_file),source=i.source,path=i.filepath) for i in bpy.data.images],materials=[])
for m in list(bpy.data.materials)[:30]:
 report['materials'].append(dict(name=m.name,nodes=[dict(name=n.name,type=n.type,image=n.image.name if n.type=='TEX_IMAGE' and n.image else None) for n in m.node_tree.nodes] if m.use_nodes else [],links=[(l.from_node.name,l.from_socket.name,l.to_node.name,l.to_socket.name) for l in m.node_tree.links] if m.use_nodes else []))
report['sample_objects']=[dict(name=o.name,location=list(o.location),scale=list(o.scale),dimensions=list(o.dimensions)) for o in meshes[:20]]
(out/'inspection.json').write_text(json.dumps(report,indent=2))
print('INSPECTED',source.name,len(meshes),report['bounds'],flush=True)
