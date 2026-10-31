const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

// Load the shipped UI without making requests or needing a browser.
const elements=new Map();
const document={querySelector(selector){
 if(!elements.has(selector))elements.set(selector,{});
 return elements.get(selector);
},addEventListener(){}};
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
const context=vm.createContext({document});
vm.runInContext(source.replace(/\nrefresh\(\);\s*$/,''),context);
const summary=context.comparisonSummary;
const rows=n=>Array.from({length:5},(_,i)=>({after:i<n?{clarity:false,completeness:true,depth:true}:null}));

for(const n of [0,3,5])test(`unfinished comparison with ${n} evaluated reports hides totals and change`,()=>{
 const html=summary({complete:false,passed:[12,n*2],change_percentage_points:-80,rows:rows(n)},true);
 assert.match(html,new RegExp(`Evaluation in progress · ${n} of 5 evaluated`));
 assert.doesNotMatch(html,/\/15|percentage points|Before:|After:|Result target/);
});
test('stopped or failed evaluation remains incomplete, not a quality score',()=>{
 const html=summary({complete:false,rows:rows(3)},false);
 assert.match(html,/Evaluation incomplete · 3 of 5 evaluated/);
 assert.doesNotMatch(html,/\/15|percentage points/);
});
test('completed comparison shows the actual score and improvement',()=>{
 const html=summary({complete:true,qualifies:true,status:'Result target met',passed:[12,15],change_percentage_points:20,before:{clarity:3},after:{clarity:5}},false);
 assert.match(html,/12\/15 → 15\/15/);
 assert.match(html,/\+20 percentage points/);
 assert.match(html,/Result target met/);
});
test('completed zero-score result is still a real result',()=>{
 const html=summary({complete:true,status:'Below passing target',passed:[12,0],change_percentage_points:-80},false);
 assert.match(html,/12\/15 → 0\/15/);
 assert.match(html,/-80 percentage points/);
});
