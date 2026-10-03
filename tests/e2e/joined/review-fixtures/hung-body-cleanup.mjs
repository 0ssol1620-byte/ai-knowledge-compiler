// Copy of the independent reviewer's fixture, adjusted only to read this working repo's harness and to give the helper
// block its imports. It deliberately never exits: joined-diagnostics.test.mjs runs it only as a child of
// deadline-supervisor.mjs, under a bounded deadline, and asserts the supervisor stops it. Never run or await it unbounded.
import { readFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const harness=fileURLToPath(new URL('../joined-e2e.mjs',import.meta.url));
const source=readFileSync(harness,'utf8');
const begin=source.indexOf('// >>> joined-diagnostics helpers'), end=source.indexOf('// <<< joined-diagnostics helpers');
const api=await import(`data:text/javascript;base64,${Buffer.from([
  'import { spawn } from "node:child_process"; import { renameSync, rmSync, writeFileSync } from "node:fs";',source.slice(begin,end),
  'export { ledgerCheckpointer, createStepRunner };'
].join('\n')).toString('base64')}`);
const root=mkdtempSync(path.join(tmpdir(),'joined-review-hung-cleanup-'));
const file=path.join(root,'ledger.json');
const ledger={success:false,stage:'browser-upload',step:null,booleans:{uploadViaUiVerified:false},timeline:[{stage:'browser-upload',startedAt:new Date().toISOString()}]};
const checkpoint=api.ledgerCheckpointer({ledger,file,redact:String,logError:console.error});
const step=api.createStepRunner({ledger,checkpoint,log:()=>{}});
try { await step('response-body',10,()=>new Promise(()=>{})); }
catch(error) { ledger.failure={name:error.name,message:error.message,stage:ledger.stage,step:ledger.step}; checkpoint('failure'); }
const written=JSON.parse(readFileSync(file,'utf8'));
if(written.failure?.name!=='StageTimeoutError'||written.failure.step!=='response-body'||written.success!==false||written.booleans.uploadViaUiVerified!==false) throw Error('failure checkpoint assertion failed');
console.log(JSON.stringify({result:'checkpoint readable before hung cleanup',ledger:file,checkpoint:written.lastCheckpoint.reason,stage:written.failure.stage,step:written.failure.step,success:written.success,proof:written.booleans}));
setInterval(()=>{},1000);
await new Promise(()=>{}); // deliberate stuck-cleanup stand-in; stop this process after reading the ledger
