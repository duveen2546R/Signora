from pathlib import Path
import json,subprocess,sys,os,numpy as np
from app.validation.fbx_motion import load_motion
root=Path(__file__).resolve().parents[2]
receipt={}
for action in ('addition','father'):
 job=json.loads((root/f'study/action_shape_audit/{action}_job.json').read_text())['jobId'];p=root/'backend/data/analyses'/job
 manifest=json.loads((p/'manifest.json').read_text());summary=json.loads((p/'results/summary.json').read_text())
 receipt[action]={}
 for label,file in [('suit','motioncapture.fbx'),('non_suit','old.fbx')]:
  motion=load_motion(p/file,include_extras=True)
  lo,hi=manifest['trials'][0]['windows'][label];mask=(motion.times>=lo)&(motion.times<=hi)
  for side in range(2):
   hand=np.concatenate([motion.joints[mask,4+side:5+side],motion.extras[mask,3+side*20:23+side*20]],axis=1)
   excursions=[]
   for f in range(5):
    chain=[0,*range(1+4*f,5+4*f)]
    for j in range(1,4):
     a=hand[:,chain[j-1]]-hand[:,chain[j]];b=hand[:,chain[j+1]]-hand[:,chain[j]]
     angles=np.rad2deg(np.arctan2(np.linalg.norm(np.cross(a,b),axis=1),np.einsum('ij,ij->i',a,b)))
     excursions.append(float(np.ptp(angles)))
   key=f'{label}_{("left","right")[side]}'
   expected=summary['action_shape']['hand_animation_diagnostics'][key]['maximum_bend_excursion_deg']
   assert abs(max(excursions)-expected)<1e-6
   receipt[action][key]={'independent_atan2_max_excursion_deg':max(excursions),'reported_max_excursion_deg':expected}
  code='''import ufbx,sys,json,os
s=ufbx.load_file(sys.argv[1]); owners=[s]; ns=s.nodes;owners.append(ns);nodes=[ns[i] for i in range(len(ns))];owners.append(nodes)
clean=lambda n:n.rsplit(':',1)[-1].rsplit('|',1)[-1]
lookup={clean(n.name):n for n in nodes};result={}
for side in ('Left','Right'):
 for f in ('Thumb','Index','Middle','Ring','Pinky'):
  for j in range(1,5):
   name=f'{side}Hand{f}{j}';parent=lookup[name].parent;owners.append(parent)
   actual=clean(parent.name);expected=f'{side}Hand' if j==1 else f'{side}Hand{f}{j-1}'
   assert actual==expected,(name,actual,expected)
   result[name]=actual
print(json.dumps(result),flush=True);os._exit(0)
'''
  proc=subprocess.run([sys.executable,'-c',code,str(p/file)],capture_output=True,text=True,check=True)
  receipt[action][label+'_hierarchy_verified']=len(json.loads(proc.stdout))
(root/'study/action_shape_audit/independent_finger_verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
