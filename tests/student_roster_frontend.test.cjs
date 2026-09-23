const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {isXlsx,displayStudentId,safeFilename,resultMessage}=require('../static/js/students-roster.js');

const source=fs.readFileSync(path.join(__dirname,'..','static','js','students-roster.js'),'utf8');
const template=fs.readFileSync(path.join(__dirname,'..','templates','students.html'),'utf8');

test('.xlsx is accepted while unsupported roster formats are rejected before upload',()=>{
  assert.equal(isXlsx({name:'students.XLSX'}),true);
  for(const name of ['students.xls','students.csv','students.xlsx.csv','']) assert.equal(isXlsx({name}),false);
  assert.doesNotMatch(template,/accept="[^"]*\.csv|accept="[^"]*\.xls(?:,|")/i);
});

test('Student IDs remain strings with canonical prefix and leading zeroes',()=>{
  assert.equal(displayStudentId('0000000042'),'STD0000000042');
  assert.equal(displayStudentId('STD0000000042'),'STD0000000042');
  assert.equal(displayStudentId(null),'—');
});

test('export consumes the backend workbook and server filename without rebuilding roster data',()=>{
  assert.equal(safeFilename('attachment; filename=student_roster_export_20260923.xlsx'),'student_roster_export_20260923.xlsx');
  assert.match(source,/fetch\("\/api\/students\/roster\/export"/);
  assert.match(source,/response\.blob\(\)/);
  assert.match(source,/response\.headers\.get\("Content-Disposition"\)/);
  assert.doesNotMatch(source,/SheetJS|ExcelJS|XLSX\./);
});

test('preview and apply re-upload roster_file and never submit approved rows or partial writes',()=>{
  assert.match(source,/upload\("\/api\/students\/roster\/import\/preview"\)/);
  assert.match(source,/upload\("\/api\/students\/roster\/import\/apply"\)/);
  assert.match(source,/body\.append\("roster_file", selectedFile/);
  assert.match(source,/window\.confirm\(/);
  assert.doesNotMatch(source,/approved_rows|valid_rows\s*\)|import valid rows|partial apply/i);
});

test('safe backend row errors remain textual and cross-tenant conflicts stay generic',()=>{
  assert.equal(resultMessage({status:'error',errors:[{field:'student_id',safe_message:'That Student ID is unavailable.'}]}),'student id: That Student ID is unavailable.');
  assert.equal(resultMessage({status:'error',errors:[{field:'student_id',safe_message:'That Student ID is unavailable.',display_name:'Safe Name'}]}),'student id: That Student ID is unavailable. (Safe Name)');
  assert.doesNotMatch(source,/tenant_name|school_group_name|organization_name|owner_name/);
  assert.match(source,/textContent =/);
  assert.doesNotMatch(source,/innerHTML/);
});

test('preview is accessible, bounded, canonical-section-only, and guarded from duplicate submit',()=>{
  assert.match(template,/role="status" aria-live="polite" tabindex="-1"/);
  assert.match(template,/<th scope="col">Row<\/th>/);
  assert.match(source,/if \(!selectedFile \|\| busy\) return/);
  assert.match(source,/data\.section_name/);
  assert.doesNotMatch(source,/section_display/);
  assert.doesNotMatch(source,/FileReader|arrayBuffer\(|readAsBinaryString|readAsArrayBuffer/);
});

test('success clears stale state and refreshes the existing Students roster',()=>{
  assert.match(source,/selectedFile = null/);
  assert.match(source,/fileInput\.value = ""/);
  assert.match(source,/window\.location\.assign\(`\/students\/\?success=roster-imported-/);
  assert.match(template,/Student roster imported successfully/);
});

test('M11 scope contains no CSV, xls, upsert, background job, migration, or backend semantic change',()=>{
  assert.doesNotMatch(template,/update existing|overwrite|upsert|sync Students/i);
  assert.doesNotMatch(source,/WebSocket|EventSource|setInterval|background|batch_id/);
  assert.match(source,/CSV and \.xls files are not supported/);
});
