import test from 'node:test';
import assert from 'node:assert/strict';
import { validatePrompt, promptCharacters, readChatEvents, chatHttpFailure } from '../../src/renderer/shared/utils/chatReliability.ts';
function stream(text, split = 3) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({start(c) { for (let i=0;i<bytes.length;i+=split) c.enqueue(bytes.slice(i,i+split)); c.close(); }});
}
const frame = event => `data: ${JSON.stringify(event)}\r\n\r\n`;
async function collect(body) { const out=[]; for await (const event of readChatEvents(body)) out.push(event); return out; }
test('exact Unicode budget includes whitespace and CRLF without mutating input', () => {
  const original='  العربية\r\n```sql\nSELECT 1;\n``` 🧭  ';
  assert.equal(promptCharacters(original),Array.from(original).length);
  assert.equal(validatePrompt(original),null);
  assert.equal(original,'  العربية\r\n```sql\nSELECT 1;\n``` 🧭  ');
  assert.equal(validatePrompt('🧭'.repeat(32000)),null);
  assert.match(validatePrompt('🧭'.repeat(32001)),/32000/);
});
test('blank rejected, default boundary accepted, custom-agent boundary retained', () => {
  assert.ok(validatePrompt(' \n\t'));
  assert.equal(validatePrompt('x'.repeat(32000)),null);
  assert.match(validatePrompt('x'.repeat(32001)),/unchanged/);
  assert.ok(validatePrompt('x'.repeat(4001),4000));
});
test('SSE survives UTF8 and record splits and confirms done', async () => {
  const events=[{type:'conv_id',conv_id:'c1'},{type:'delta',text:'العربية 🧭'},{type:'done'}];
  for (const n of [1,2,7,1024]) assert.deepEqual(await collect(stream(events.map(frame).join(''),n)),events);
});
test('premature EOF is a failure even after partial text', async () => {
  await assert.rejects(collect(stream(frame({type:'delta',text:'partial'}))),/interrupted/);
});
test('provider error is terminal and cannot consume later fake success', async () => {
  assert.deepEqual(await collect(stream(frame({type:'error',message:'failed'})+frame({type:'done'}))),[{type:'error',message:'failed'}]);
});
test('malformed SSE data is rejected', async () => {
  await assert.rejects(collect(stream('data: {bad}\n\n')),SyntaxError);
});
test('reader releases lock after success and truncated response', async () => {
  const ok=stream(frame({type:'done'})); await collect(ok); assert.equal(ok.locked,false);
  const bad=stream('data: {'); await assert.rejects(collect(bad)); assert.equal(bad.locked,false);
});

test('422 reports the actual server limit without leaking echoed prompt or traces', async () => {
  const response = new Response(JSON.stringify({detail:[{loc:['body','prompt'],type:'string_too_long',ctx:{max_length:4000},input:'DO_NOT_ECHO_SECRET',msg:'raw trace DO_NOT_ECHO_SECRET'}]}),{status:422});
  const message=await chatHttpFailure(response);
  assert.match(message,/4000/); assert.match(message,/page context/); assert.match(message,/not started/);
  assert.equal(message.includes('DO_NOT_ECHO_SECRET'),false);
});
test('legacy validation schema and display_text also expose a safe length limit', async () => {
  const response=new Response(JSON.stringify({detail:[{loc:['body','display_text'],type:'value_error.any_str.max_length',ctx:{limit_value:32000}}]}),{status:422});
  assert.match(await chatHttpFailure(response),/32000/);
});
test('non-JSON 422 is actionable and does not expose raw proxy content', async () => {
  const response=new Response('<html>INTERNAL_SECRET</html>',{status:422});
  const message=await chatHttpFailure(response);
  assert.match(message,/validation failed/); assert.equal(message.includes('INTERNAL_SECRET'),false);
});
test('unrelated validation and server errors do not echo sensitive details', async () => {
  for(const status of [401,403,402,429,500]){
    assert.equal((await chatHttpFailure(new Response('DO_NOT_ECHO_SECRET',{status}))).includes('DO_NOT_ECHO_SECRET'),false);
  }
  const response=new Response(JSON.stringify({detail:[{loc:['body','secret'],type:'string_too_long',ctx:{max_length:99},input:'DO_NOT_ECHO_SECRET'}]}),{status:422});
  const message=await chatHttpFailure(response); assert.match(message,/validation failed/); assert.equal(message.includes('99'),false);
});
