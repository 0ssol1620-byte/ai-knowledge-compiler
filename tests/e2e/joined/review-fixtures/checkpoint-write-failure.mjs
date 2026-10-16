// Copy of the independent reviewer's fixture, adjusted only to read this working repo's harness and to give the helper
// block its imports. It reproduced a swallowed checkpoint failure; joined-diagnostics.test.mjs runs it as a bounded child
// and asserts the reproduction now fails: the write failure is thrown and the process exits non-zero.
import { readFileSync, mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const harness=fileURLToPath(new URL('../joined-e2e.mjs',import.meta.url));
const source=readFileSync(harness,'utf8');
const begin=source.indexOf('// >>> joined-diagnostics helpers'), end=source.indexOf('// <<< joined-diagnostics helpers');
const api=await import(`data:text/javascript;base64,${Buffer.from([
  'import { spawn } from "node:child_process"; import { renameSync, rmSync, writeFileSync } from "node:fs";',source.slice(begin,end),
  'export { ledgerCheckpointer };'
].join('\n')).toString('base64')}`);
const root=mkdtempSync(path.join(tmpdir(),'joined-review-checkpoint-failure-'));
const file=path.join(root,'missing-parent','ledger.json');
const errors=[];
api.ledgerCheckpointer({ledger:{success:false},file,redact:String,logError:line=>errors.push(line)})('failure');
if(existsSync(file)||errors.length!==1||!errors[0].includes('ledger checkpoint failure failed')) throw Error('checkpoint failure was not observable');
console.log(JSON.stringify({result:'failed checkpoint is swallowed and logged',ledger:file,exists:existsSync(file),log:errors[0]}));
