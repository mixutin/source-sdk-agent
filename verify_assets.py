"""Local integration fixtures for the dedicated automation_test project; no publishing."""
from pathlib import Path
import json
import math
import struct
import wave
from PIL import Image
import agent as a

name='automation_test'
root,_=a.project(name)
assets=root/'assetsrc'
assets.mkdir(exist_ok=True)
def current(relative):
    path=a.contained(root,relative)
    return a.sha(path.read_bytes()) if path.exists() else ''
def put(relative,text):
    return a.write_text(name,relative,text,current(relative))
image=Image.new('RGBA',(64,64))
image.putdata([(240,160,40,255) if (x//8+y//8)%2 else (30,45,65,255) for y in range(64) for x in range(64)])
image.save(assets/'agent_checker.png')
texture=a.TOOLS['compile_texture'](name,'assetsrc/agent_checker.png','agent/agent_checker',current('game/mod_hl2mp/materials/agent/agent_checker.vtf'))
materials=[]
for material,shader in [('agent_checker','VertexLitGeneric'),('agent_wall','LightmappedGeneric')]:
    materials.append(a.TOOLS['create_material'](name,'agent/'+material,shader,{'$basetexture':'agent/agent_checker','$surfaceprop':'metal'},current('game/mod_hl2mp/materials/agent/'+material+'.vmt')))
with wave.open(str(assets/'tone.wav'),'wb') as f:
    f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050)
    f.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/22050))) for i in range(2205)))
sound=a.TOOLS['convert_sound'](name,'assetsrc/tone.wav','agent/verification_tone',True,current('game/mod_hl2mp/sound/agent/verification_tone.wav'))
verts=[(-16,-16,0),(16,-16,0),(16,16,0),(-16,16,0),(-16,-16,32),(16,-16,32),(16,16,32),(-16,16,32)]
faces=[((0,3,2,1),(0,0,-1)),((4,5,6,7),(0,0,1)),((0,1,5,4),(0,-1,0)),((3,7,6,2),(0,1,0)),((0,4,7,3),(-1,0,0)),((1,2,6,5),(1,0,0))]
smd='version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n'
for face,normal in faces:
    for order in ((0,1,2),(0,2,3)):
        smd+='agent_checker\n'
        for index in order:
            x,y,z=verts[face[index]];nx,ny,nz=normal;u,v=((0,0),(1,0),(1,1),(0,1))[index]
            smd+=f'0 {x} {y} {z} {nx} {ny} {nz} {u} {v}\n'
smd+='end\n'
put('modelsrc/verification_cube.smd',smd)
put('modelsrc/verification_cube.qc','$modelname "agent/verification_cube.mdl"\n$body body "verification_cube.smd"\n$staticprop\n$surfaceprop "metal"\n$cdmaterials "agent/"\n$sequence idle "verification_cube.smd" fps 1\n$collisionmodel "verification_cube.smd" { $mass 10 }\n')
model=a.TOOLS['compile_model'](name,'modelsrc/verification_cube.qc')
report={'texture':texture,'materials':materials,'sound':sound,'model_job':model}
(root/'.source-agent/verification').mkdir(exist_ok=True)
a.atomic_json(root/'.source-agent/verification/asset-pipeline.json',report)
print(json.dumps(report,indent=2))
