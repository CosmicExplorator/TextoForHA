const $ = (selector, root = document) => root.querySelector(selector);
const el = (tag, text, className) => { const node = document.createElement(tag); if(text != null) node.textContent = String(text); if(className) node.className = className; return node; };
let modems = [], selected = null, tab = 'sms', busy = false, signature = '', editId = null;
const drafts = new Map();
const current = () => modems.find(m => m.config.id === selected);
const can = (action) => current()?.capabilities.includes(action);
const draft = () => { if(!drafts.has(selected)) drafts.set(selected, {}); return drafts.get(selected); };
const notice = (text, error = false) => { $('#notice').textContent = text; $('#notice').className = error ? 'error' : ''; };
const button = (text, handler, cls = 'secondary') => { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', handler); return b; };
const panel = (title) => { const p = el('section', null, 'panel'); p.append(el('h2', title)); return p; };

async function api(path, method = 'GET', data) {
  const response = await fetch(new URL(`api/${path}`, document.baseURI), {method, headers: method === 'GET' ? {} : {'Content-Type':'application/json','X-TextoForHA':'1'}, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if(!response.ok) throw new Error(result.error || 'La requête a échoué.');
  return result;
}
function lock(value) { busy = value; document.querySelectorAll('button,select,input,textarea').forEach(n => { n.disabled = value; }); if(!value) { if(editId) $('#modem-form [name=id]').disabled = true; driverFields(); } }
async function operation(fn, success) {
  if(busy) return;
  lock(true); notice('Opération en cours…');
  try { await fn(); notice(success); }
  catch(error) { notice(error.message, true); }
  finally { lock(false); }
}
async function load() {
  try {
    modems = (await api('modems')).modems;
    if(!modems.some(m => m.config.id === selected)) { selected = modems[0]?.config.id || null; render(); }
    const selector = $('#modem');
    if([...selector.options].map(o => o.value + o.text).join() !== modems.map(m => m.config.id + m.config.name).join()) {
      selector.replaceChildren(...modems.map(m => {const o=el('option',m.config.name);o.value=m.config.id;return o;}));
    }
    selector.value = selected || '';
    update();
  } catch(error) { notice('Application indisponible. '+error.message, true); }
}
async function act(action, data, success, after) {
  const id = selected;
  if(!can(action)) return;
  await operation(async () => {
    const result = await api(`modems/${encodeURIComponent(id)}/actions/${action}`, 'POST', data);
    const index = modems.findIndex(m => m.config.id === id);
    if(index !== -1) modems[index] = result.modem;
    if(after) after();
    update();
  }, success);
}
function field(form, labelText, key, multiline=false) {
  const label = el('label', labelText), input = el(multiline ? 'textarea' : 'input');
  input.name=key; input.required=true; input.value=draft()[key] || ''; if(multiline) input.rows=5;
  input.addEventListener('input',()=>{draft()[key]=input.value;}); label.append(input); form.append(label); return input;
}
function render() {
  signature='';
  document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===tab));
  const root=$('#content');root.replaceChildren();
  if(!current()){root.append(el('p','Ajoute une clé pour consulter ses SMS et son réseau.','empty'));return;}
  if(tab==='sms') {
    root.className='columns';
    const composer=panel('Nouveau message'), form=el('form');form.id='composer';
    const phone=field(form,'Destinataire','phone');phone.type='tel';phone.placeholder='+33612345678';phone.pattern='\\+?[0-9]{6,15}';
    const message=field(form,'Message','message',true);
    const isAT=current().config.driver==='serial'||current().config.source==='qualcomm';
    message.maxLength=isAT?160:1000;
    if(isAT) form.append(el('p','Un SMS simple : 160 caractères GSM ou 70 caractères Unicode. Certains emojis sont exclus à l’envoi.','hint'));
    const send=el('button',`Envoyer avec ${current().config.name}`);send.type='submit';form.append(send);
    form.addEventListener('submit',event=>{event.preventDefault();if(busy||!form.reportValidity())return;const saved=draft();act('send',{phone_number:phone.value.trim(),message:message.value},'Envoi accepté par le modem.',()=>{saved.message='';message.value='';});});
    composer.append(form);const inbox=panel('Boîte de réception');inbox.append(el('div',null,'dynamic'));root.append(composer,inbox);
  } else {root.className='';root.append(el('div',null,'dynamic'));}
  update();
}
function update() {
  const modem=current();if(!modem)return;
  $('#status').textContent=modem.available?'● Disponible':'○ Indisponible';$('#status').className='status'+(modem.available?' online':'');
  const sig=JSON.stringify([tab,modem]);if(sig===signature)return;signature=sig;
  const root=$('.dynamic');if(!root)return;
  if(tab!=='configuration'||root.dataset.configSignature!==JSON.stringify(modem.config))root.replaceChildren();
  if(tab==='sms') renderMessages(root,modem);
  if(tab==='network') renderNetwork(root,modem);
  if(tab==='configuration') {
    if(root.dataset.configSignature===JSON.stringify(modem.config) && root.querySelector('[data-sim-summary]')) {
      const summary=root.querySelector('[data-sim-summary]');summary.replaceChildren();
      for(const [key,value] of Object.entries(modem.sim))summary.append(el('dt',key),el('dd',value??'Non disponible'));
    } else renderConfig(root,modem);
  }
  if(tab==='contacts') renderContacts(root,modem);
  // A data refresh never replaces the SMS composer or clears its draft.
  if(busy) lock(true);
}
function formatDate(value){const d=new Date(String(value).replace(' ','T'));return Number.isNaN(d.getTime())?String(value):d.toLocaleString('fr');}
function renderMessages(root,modem){
  if(!modem.available)root.append(el('p',modem.error||'Modem indisponible. Les messages affichés sont les derniers connus.','hint'));
  if(!modem.messages.length)root.append(el('p',modem.available?'Aucun SMS reçu.':'La boîte de réception est indisponible.','empty'));
  for(const sms of modem.messages){
    const article=el('article',null,'message'),head=el('div',null,'message-head');head.append(el('strong',sms.contact_name||sms.from||'Expéditeur inconnu'),el('time',formatDate(sms.date),'meta'));article.append(head);
    if(sms.parts>1)article.append(el('p',`Partie ${sms.part} / ${sms.parts}`,'meta'));
    article.append(el('p',sms.content,'message-text'));
    const actions=el('div',null,'actions');
    if(/^\+?[0-9]{6,15}$/.test(sms.from||''))actions.append(button('Répondre',()=>{draft().phone=sms.from;$('#composer [name=phone]').value=sms.from;$('#composer [name=message]').focus();}));
    if(can('delete'))actions.append(button('Supprimer',()=>{if(confirm(`Supprimer ce SMS de ${modem.config.name} ?`))act('delete',{id:sms.id},'SMS supprimé.');},'danger'));
    article.append(actions);root.append(article);
  }
}
function renderNetwork(root,modem){
  const grid=el('div',null,'network-grid');
  for(const [name,value] of Object.entries({...modem.network,...modem.sim})){const p=el('section',null,'panel metric');p.append(el('span',name),el('strong',value??'Non disponible'));grid.append(p);}
  root.append(grid);
  if(!grid.childNodes.length)root.append(el('p','Aucune information réseau disponible pour cette clé.','empty'));
  root.append(el('p','Les informations disponibles dépendent du modem et de son firmware. Les paramètres radio sont en lecture seule dans cette version.','hint'));
}
function renderConfig(root,modem){
  root.dataset.configSignature=JSON.stringify(modem.config);
  const p=panel(modem.config.name),dl=el('dl');
  const labels={driver:'Connexion',url:'Adresse',port:'Port AT',baudrate:'Vitesse',storage:'Mémoire SMS',source:'Intégration',inbox:'Capteur SMS'};
  const drivers={huawei:'Huawei HiLink directe',serial:'Port série AT',homeassistant:'Intégration Home Assistant existante'};
  for(const [key,label] of Object.entries(labels))if(modem.config[key])dl.append(el('dt',label),el('dd',key==='driver'?drivers[modem.config[key]]:modem.config[key]));
  p.append(dl);const actions=el('div',null,'actions');actions.append(button('Modifier',()=>openEditor(modem.config)),button('Retirer de TextoForHA',()=>{if(confirm('Retirer cette configuration de TextoForHA ? La clé, ses SMS et les intégrations Home Assistant seront conservés.')){const id=selected;operation(async()=>{await api(`modems/${id}`,'DELETE',{});await load();},'Configuration retirée.');}},'danger'));p.append(actions);root.append(p);
  const sim=panel('Carte SIM');sim.classList.add('sim-panel');
  const summary=el('dl');summary.dataset.simSummary='1';for(const [key,value] of Object.entries(modem.sim))summary.append(el('dt',key),el('dd',value??'Non disponible'));sim.append(summary);
  if(can('pin_status')){
    sim.append(button('Lire le statut PIN',()=>act('pin_status',{},'Statut PIN actualisé.')));
    const form=el('form');form.id='pin-form';
    for(const [key,label] of [['current_pin','PIN actuel'],['new_pin','Nouveau PIN'],['confirm_pin','Confirmer le nouveau PIN']]){const l=el('label',label),i=el('input');i.name=key;i.type='password';i.inputMode='numeric';i.autocomplete='off';i.pattern='[0-9]{4,8}';i.maxLength=8;l.append(i);form.append(l);}
    form.append(el('p','Un code incorrect consomme une tentative. Aucun nouvel essai automatique.','hint'));
    const buttons=el('div',null,'actions');
    for(const [action,label] of [['pin_verify','Déverrouiller'],['pin_enable','Activer le PIN'],['pin_disable','Désactiver le PIN'],['pin_change','Changer le PIN']])buttons.append(button(label,()=>{
      const current=$('[name=current_pin]',form).value,next=$('[name=new_pin]',form).value,confirmation=$('[name=confirm_pin]',form).value;
      if(!/^[0-9]{4,8}$/.test(current)||(action==='pin_change'&&(!/^[0-9]{4,8}$/.test(next)||next!==confirmation))){notice('Vérifie les codes PIN et leur confirmation.',true);return;}
      if(!confirm(`${label} sur ${modem.config.name} ?`))return;
      const payload={current_pin:current};if(action==='pin_change')payload.new_pin=next;
      form.reset();act(action,payload,'Opération PIN acceptée.');
    }));form.append(buttons);sim.append(form);
  }else sim.append(el('p','La modification du PIN n’est pas prise en charge par ce pilote.','hint'));
  root.append(sim);
}
function renderContacts(root,modem){
  if(!can('contact_add')){root.append(el('p','Les contacts SIM ne sont pas encore pris en charge par ce pilote.','empty'));return;}
  const p=panel('Contacts SIM'),form=el('form');
  const name=field(form,'Nom','contactName'),phone=field(form,'Numéro','contactPhone');phone.type='tel';
  const add=el('button','Ajouter');add.type='submit';form.append(add);form.addEventListener('submit',e=>{e.preventDefault();const saved=draft();act('contact_add',{name:name.value,phone_number:phone.value.trim()},'Contact ajouté.',()=>{saved.contactName=saved.contactPhone='';name.value=phone.value='';});});p.append(form);
  for(const contact of modem.contacts){const row=el('article',null,'message');row.append(el('strong',contact.name),el('p',contact.phone_number),button('Supprimer',()=>{if(confirm(`Supprimer le contact ${contact.name} ?`))act('contact_delete',{id:contact.id},'Contact supprimé.');},'danger'));p.append(row);}root.append(p);
}
function driverFields(){const form=$('#modem-form'),driver=form.elements.driver.value;form.querySelectorAll('[data-driver]').forEach(group=>{group.hidden=group.dataset.driver!==driver;group.querySelectorAll('input,select').forEach(n=>{n.disabled=busy||group.hidden;});});}
function openEditor(config){if(busy)return;editId=config?.id||null;const form=$('#modem-form');form.reset();$('#editor-error').textContent='';$('#editor-title').textContent=config?'Modifier le modem':'Ajouter une clé';for(const [key,value] of Object.entries(config||{}))if(form.elements[key])form.elements[key].value=value;form.elements.id.disabled=Boolean(editId);form.elements.password.value='';$('#password-hint').textContent=config?.has_password?'Laisser vide pour conserver le mot de passe actuel.':'Laisser vide si aucun mot de passe n’est nécessaire.';driverFields();$('#editor').showModal();}
$('#editor').addEventListener('close',()=>{$('#modem-form').elements.password.value='';});
$('#add').addEventListener('click',()=>openEditor());$('#cancel').addEventListener('click',()=>$('#editor').close());$('#modem-form [name=driver]').addEventListener('change',driverFields);
$('#modem-form').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;const form=event.currentTarget,payload=Object.fromEntries(new FormData(form));if(editId)payload.id=editId;if(payload.baudrate)payload.baudrate=Number(payload.baudrate);const key=editId;lock(true);try{await api(key?`modems/${encodeURIComponent(key)}`:'modems',key?'PUT':'POST',payload);selected=payload.id;form.elements.password.value='';$('#editor').close();await load();render();notice('Configuration enregistrée.');}catch(error){$('#editor-error').textContent=error.message;}finally{lock(false);}});
$('#modem').addEventListener('change',event=>{if(busy)return;selected=event.target.value;notice('');render();});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{if(busy)return;tab=b.dataset.tab;notice('');render();}));
$('#refresh').addEventListener('click',()=>{const id=selected;if(id)operation(async()=>{await api(`modems/${id}/refresh`,'POST',{});await load();},'Lecture actualisée.');});
await load();setInterval(()=>{if(!busy&&!$('#editor').open)load();},10000);
