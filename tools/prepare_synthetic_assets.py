"""Add head-skin weights as vertex colors without changing source assets."""
import json
import struct
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/source/kingdomarchives'
OUTPUT = ROOT / 'assets/generated/head_weighted'
DTYPES = {5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
WIDTH = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}

def convert(slug):
    config = json.loads((SOURCE/slug/'viewer_config.json').read_text())
    data = (SOURCE/slug/config['Model']['Name']).read_bytes()
    size, kind = struct.unpack_from('<II', data, 12)
    doc = json.loads(data[20:20+size])
    offset = 20+size
    size, kind = struct.unpack_from('<II', data, offset)
    binary = bytearray(data[offset+8:offset+8+size])
    def accessor(index):
        a = doc['accessors'][index]; v = doc['bufferViews'][a['bufferView']]
        dtype = np.dtype(DTYPES[a['componentType']]); width = WIDTH[a['type']]
        result = np.ndarray((a['count'],width), dtype=dtype, buffer=binary,
            offset=v.get('byteOffset',0)+a.get('byteOffset',0),
            strides=(v.get('byteStride',width*dtype.itemsize),dtype.itemsize)).copy()
        if a.get('normalized') and dtype.kind in 'ui': result = result.astype(float)/np.iinfo(dtype).max
        return result
    heads = [i for i,n in enumerate(doc['nodes']) if n.get('name','').lower() == 'head']
    assert heads, (slug, heads)
    descendants = set()
    def visit(i):
        descendants.add(i)
        for child in doc['nodes'][i].get('children',[]): visit(child)
    for head in heads: visit(head)
    totals = [0,0]
    seen = set()
    for node in doc['nodes']:
        if 'mesh' not in node or 'skin' not in node: continue
        if node['mesh'] in seen: continue
        seen.add(node['mesh'])
        joints = doc['skins'][node['skin']]['joints']
        head_joint_indices = [i for i,j in enumerate(joints) if j in descendants]
        inverse_binds = accessor(doc['skins'][node['skin']]['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
        head_indices = [i for i,j in enumerate(joints) if j in heads]
        if not head_indices: continue
        head_inverse = inverse_binds[head_indices[0]]
        for prim in doc['meshes'][node['mesh']]['primitives']:
            attrs = prim['attributes']
            if 'JOINTS_0' not in attrs: continue
            weights = np.zeros(len(accessor(attrs['POSITION'])), dtype=np.float32)
            for k in (0,1):
                if f'JOINTS_{k}' in attrs:
                    js = accessor(attrs[f'JOINTS_{k}']); ws = accessor(attrs[f'WEIGHTS_{k}'])
                    weights += (ws*np.isin(js,head_joint_indices)).sum(axis=1)
            positions = accessor(attrs['POSITION'])
            local = np.column_stack([positions,np.ones(len(positions))]) @ head_inverse.T
            # Crop long ponytails/scarves below the skull. This is a visual head
            # annotation, not every mesh attached anywhere under the Head joint.
            envelope = ((local[:,1]>=-.115) & (local[:,1]<=.30)
                        & (np.abs(local[:,0])<=.25) & (np.abs(local[:,2])<=.28))
            weights *= envelope
            colors = np.zeros((len(weights),4), dtype=np.uint8)
            colors[:,0] = np.rint(np.clip(weights,0,1)*255).astype(np.uint8)
            colors[:,3] = 255
            while len(binary)%4: binary.append(0)
            view = len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':colors.nbytes,'target':34962})
            binary.extend(colors.tobytes())
            attrs['COLOR_0'] = len(doc['accessors'])
            doc['accessors'].append({'bufferView':view,'componentType':5121,'normalized':True,'count':len(colors),'type':'VEC4'})
            totals[0] += len(weights); totals[1] += int((weights>=.5).sum())
    assert totals[1]>0, slug
    doc['buffers'][0]['byteLength'] = len(binary)
    encoded = json.dumps(doc,separators=(',',':')).encode()
    encoded += b' '*(-len(encoded)%4)
    binary += b'\0'*(-len(binary)%4)
    output = struct.pack('<III',0x46546C67,2,28+len(encoded)+len(binary))
    output += struct.pack('<II',len(encoded),0x4E4F534A)+encoded
    output += struct.pack('<II',len(binary),0x004E4942)+binary
    (OUTPUT/f'{slug}.glb').write_bytes(output)
    return {'character':slug,'vertices':totals[0],'head_vertices':totals[1], 'head_bone':doc['nodes'][heads[0]]['name']}

if __name__ == '__main__':
    OUTPUT.mkdir(parents=True,exist_ok=True)
    catalog=json.loads((SOURCE/'catalog.json').read_text())
    records=[convert(c['slug']) for c in catalog['characters']]
    (OUTPUT/'report.json').write_text(json.dumps(records,indent=2))
    print(json.dumps(records,indent=2))
