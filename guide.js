/* Enhancements share the existing map engine and city data. */
var filterState = {category:'all', day:'', budget:'', area:'', period:'', query:'', saved:false, ended:false};
var savedEvents = [];
try { savedEvents = JSON.parse(localStorage.getItem('weekend-saved') || '[]'); } catch (_) {}
if (!Array.isArray(savedEvents)) savedEvents = [];
var selectedEvent = null;
var pinGroups = {};
function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function safeLink(url) { try { var u = new URL(url); return /^https?:$/.test(u.protocol) ? u.href : ''; } catch (_) { return ''; } }
function link(label, url, primary) { url = safeLink(url); return url ? '<a class="action'+(primary?' primary':'')+'" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+' ↗</a>' : ''; }
function keyFor(a) { return currentCity + ':' + a.id; }
function isSaved(a) { return savedEvents.indexOf(keyFor(a)) !== -1; }
function saveEvent(a) {
  var key = keyFor(a), index = savedEvents.indexOf(key);
  if (index < 0) savedEvents.push(key); else savedEvents.splice(index,1);
  try { localStorage.setItem('weekend-saved',JSON.stringify(savedEvents)); } catch (_) { document.getElementById('result-count').textContent = 'Saved for this visit; browser storage is unavailable.'; }
  buildSidebar(); applyFilters();
  if (selectedEvent) showPopup(selectedEvent);
}
function todayBkk() { return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
function ended(a) {
  if (a.end_at) return Date.parse(a.end_at) < Date.now();
  return !!a.end_date && a.end_date < todayBkk();
}
function dateLabel(a) {
  if (!a.start_date || !a.end_date) return a.until || 'Check event dates';
  var format = function(d) {return new Date(d+'T12:00:00+07:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'Asia/Bangkok'});};
  return format(a.start_date)+(a.start_date===a.end_date?'':' – '+format(a.end_date))+(a.start_date.slice(0,4)!==a.end_date.slice(0,4)?' '+a.end_date.slice(0,4):'');
}
function badges(a) {
  if (ended(a)) return 'Finished';
  if (a.kind === 'anytime') return 'Anytime place';
  var meta = typeof META_BANGKOK !== 'undefined' ? META_BANGKOK : {};
  if (a.end_date && a.end_date <= meta.weekend_end) return 'Last chance this weekend';
  if (a.first_seen && a.first_seen.slice(0,10) >= meta.weekend_start) return 'New this week';
  return a.kind === 'exhibition' ? 'Still on' : '';
}
function hasPin(a) { return Number.isFinite(a.lat) && Number.isFinite(a.lng) && (currentCity !== 'bangkok' || a.location_status === 'verified'); }
function directions(a) {
  if (safeLink(a.maps_url)) return a.maps_url;
  if (hasPin(a)) return 'https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(a.lat+','+a.lng);
  return 'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(a.loc+' '+CITY_CONFIG[currentCity].name);
}
function matches(a) {
  if (!filterState.ended && ended(a)) return false;
  if (filterState.category !== 'all' && a.cat !== filterState.category) return false;
  if (filterState.saved && !isSaved(a)) return false;
  if (filterState.budget === 'free' && !a.free) return false;
  if (filterState.budget === '500' && !(a.free || a.price_min != null && a.price_min <= 500)) return false;
  if (filterState.area && a.neighborhood !== filterState.area) return false;
  if (filterState.period && a.period !== filterState.period && a.period !== 'both') return false;
  if (filterState.query && [a.title,a.event_name,a.loc,a.desc].join(' ').toLowerCase().indexOf(filterState.query.toLowerCase()) < 0) return false;
  if (filterState.day) {
    var date = filterState.day;
    if (a.kind !== 'anytime' && (!a.start_date || !a.end_date || date < a.start_date || date > a.end_date)) return false;
    var weekday = (new Date(date+'T12:00:00+07:00').getUTCDay()+6)%7;
    if (a.weekdays && a.weekdays.length && a.weekdays.indexOf(weekday) < 0) return false;
  }
  return true;
}
function applyFilters() {
  var count=0, mapped=0;
  A.forEach(function(a) {
    var show=matches(a), card=document.getElementById('card-'+a.id);
    if (card) card.classList.toggle('hide',!show);
    if (show) { count++; if(hasPin(a)) mapped++; }
  });
  Object.keys(pinGroups).forEach(function(id) {
    var visible=pinGroups[id].filter(matches), pin=document.getElementById('pin-'+id);
    pin.classList.toggle('hidden',!visible.length);
    pin.querySelector('.mpin-dot').textContent=visible.length>1?visible.length:(visible[0]||pinGroups[id][0]).e;
    pin.querySelector('.mpin-label').textContent=visible.map(function(a){return a.title;}).join(' · ');
  });
  document.getElementById('result-count').textContent=count+' picks'+(currentCity==='bangkok'?' · '+mapped+' with verified map locations':'');
  var empty=document.getElementById('empty-state');
  if(empty) empty.hidden=!!count;
  var extras=['day','budget','area','period','ended'].filter(function(k){return !!filterState[k];}).length;
  document.getElementById('filters-toggle').textContent='Filters'+(extras?' ('+extras+')':'');
  document.querySelectorAll('.mobile-nav button').forEach(function(b){b.setAttribute('aria-pressed',b.dataset.view===(document.body.classList.contains('map-view')?'map':filterState.saved?'saved':'list'));});
  render();
}
buildMarkers = function() {
  markerLayer.querySelectorAll('.mpin').forEach(function(p){p.remove();});
  pinGroups={}; var positions={};
  A.filter(hasPin).forEach(function(a) {
    var position=a.lat+','+a.lng;
    if(positions[position]) { pinGroups[positions[position]].push(a); return; }
    positions[position]=String(a.id); pinGroups[a.id]=[a];
    var pin=document.createElement('button'); pin.type='button'; pin.className='mpin'; pin.id='pin-'+a.id;
    pin.setAttribute('aria-label','Events at '+(a.venue||a.loc));
      pin.innerHTML='<span class="mpin-dot" style="background:'+(COLORS[a.cat]||'#888')+'">'+esc(a.e)+'</span><span class="mpin-label">'+esc(a.title)+'</span>';
    pin.addEventListener('click',function(e){e.stopPropagation(); var chosen=pinGroups[a.id].filter(matches)[0]; if(chosen){showPopup(chosen);highlightCard(chosen.id);}});
    markerLayer.appendChild(pin);
  });
};
buildSidebar = function() {
  sidebar.innerHTML='';
  A.forEach(function(a) {
    var el=document.createElement('article'); el.className='card'+(safeLink(a.img)?'':' no-image'); el.id='card-'+a.id;
    el.tabIndex=0; el.setAttribute('aria-label',a.title);
    el.innerHTML=(safeLink(a.img)?'<img loading="lazy" class="card-img" src="'+esc(a.img)+'" alt="">':'')+
      '<div class="card-body"><span class="ctag tag-'+esc(a.cat)+'">'+esc(a.e+' '+a.cat)+'</span> <span class="event-badge">'+esc(badges(a))+'</span>'+
      '<h2 class="card-title">'+esc(a.title)+'</h2><div class="card-meta"><span>'+esc(dateLabel(a))+(a.time?' · '+esc(a.time):'')+'</span><span>'+esc(a.loc)+'</span><span class="'+(a.free?'green':'amber')+'">'+esc(a.price)+'</span></div>'+
      '<p class="card-desc">'+esc(a.desc)+'</p><div class="card-footer"><button class="action details" type="button">Details</button><button class="action save" type="button">'+(isSaved(a)?'♥ Saved':'♡ Save')+'</button></div></div>';
    el.addEventListener('click',function(e){ if(e.target.closest('.save')) {saveEvent(a);return;} flyTo(a); });
    el.addEventListener('keydown',function(e){if(e.target===el && (e.key==='Enter'||e.key===' ')){e.preventDefault();flyTo(a);}});
    var img=el.querySelector('img'); if(img) img.addEventListener('error',function(){img.remove();el.classList.add('no-image');});
    sidebar.appendChild(el);
  });
  var empty=document.createElement('p'); empty.id='empty-state'; empty.className='empty'; empty.hidden=true;
  empty.textContent='No matching picks. Try another day or clear a filter.'; sidebar.appendChild(empty);
};
document.body.appendChild(popup);
popup.setAttribute('role','dialog'); popup.setAttribute('aria-labelledby','popup-title');
document.getElementById('popup-close').setAttribute('aria-label','Close event details');
popup.addEventListener('click',function(e){e.stopPropagation();});
showPopup = function(a) {
  selectedEvent=a; popupImg.style.display=safeLink(a.img)?'':'none';
  if(safeLink(a.img)) popupImg.src=a.img;
  popupTitle.textContent=a.title;
  var sources=(a.sources||[]).map(function(s){return '<a href="'+esc(safeLink(s.url))+'" target="_blank" rel="noopener noreferrer">'+esc(s.name)+'</a>';}).join(' · ');
  var otherDetails=(a.sources||[]).filter(function(s){return s.event_url && s.event_url!==a.detail_url && s.event_url!==a.official_url && s.event_url!==a.ticket_url;}).map(function(s){return link('More details via '+s.name,s.event_url);}).join('');
  var sourceUrl=a.detail_url;
  if(!sourceUrl && currentCity!=='bangkok') sourceUrl='https://www.timeout.com/'+(currentCity==='hongkong'?'hong-kong':currentCity)+'/things-to-do/things-to-do-in-'+(currentCity==='hongkong'?'hong-kong':currentCity)+'-this-weekend';
  popupMeta.innerHTML='<p>'+esc(a.desc)+'</p><span>📅 '+esc(dateLabel(a))+(a.time?' · '+esc(a.time):'')+'</span><span>📍 '+esc(a.loc)+'</span><span>💰 '+esc(a.price)+'</span>'+
    (a.access?'<span>'+esc(a.access)+'</span>':'')+(a.booking?'<span>Booking: '+esc(a.booking)+'</span>':'')+(a.language?'<span>Language: '+esc(a.language)+'</span>':'')+
    '<div class="detail-actions">'+link(a.official_url?'Official details':(a.detail_url?'Event details':'Source roundup'),a.official_url||sourceUrl,true)+link('Tickets / RSVP',a.ticket_url)+link(hasPin(a)?'Directions':'Find venue on Maps',directions(a))+'<button class="action" id="detail-save">'+(isSaved(a)?'♥ Saved':'♡ Save')+'</button><button class="action" id="detail-share">Share event</button></div>'+
    (otherDetails?'<div class="detail-actions">'+otherDetails+'</div>':'')+
    '<p class="detail-note">'+(hasPin(a)?(currentCity==='bangkok'?'Venue coordinates verified. Check floor and entrance above.':'Check the venue before travelling.'):'Exact location not yet confirmed; no map pin is shown.')+'</p>'+
    '<p class="detail-note">'+sources+(a.checked_at?'<br>Checked '+esc(new Date(a.checked_at).toLocaleString('en-GB',{timeZone:'Asia/Bangkok'}))+' Bangkok time.':'')+' Ticket availability may change.</p>'+
    '<div id="same-venue" class="related"></div><p id="share-status" class="detail-note" role="status"></p>';
  document.getElementById('detail-save').onclick=function(){saveEvent(a);};
  document.getElementById('detail-share').onclick=async function(){
    var url=new URL(location.href); url.hash=currentCity+'/'+a.id;
    try { await navigator.clipboard.writeText(url.href); document.getElementById('share-status').textContent='Event link copied.'; }
    catch(_){document.getElementById('share-status').textContent='Copy this link: '+url.href;}
  };
  var related=document.getElementById('same-venue');
  A.filter(function(other){return other.id!==a.id && a.venue_id && other.venue_id===a.venue_id && !ended(other);}).forEach(function(other){var b=document.createElement('button');b.className='action';b.textContent='Also here: '+other.title;b.onclick=function(){showPopup(other);};related.appendChild(b);});
  related.hidden=!related.children.length;
  popup.style.setProperty('--detail-top',(document.querySelector('.layout').getBoundingClientRect().top+12)+'px');
  popup.style.display='block';
  document.getElementById('popup-close').focus({preventScroll:true});
};
function closeDetail(){popup.style.display='none';selectedEvent=null;}
document.getElementById('popup-close').addEventListener('click',closeDetail);
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDetail();});
flyTo = function(a) {
  if(hasPin(a)){centerLat=a.lat;centerLng=a.lng;zoom=15;loadedTiles={};tileLayer.innerHTML='';render();}
  showPopup(a);highlightCard(a.id);
};
var baseSwitchCity=switchCity;
switchCity=function(city) {
  filterState={category:'all',day:'',budget:'',area:'',period:'',query:'',saved:false,ended:false};
  selectedEvent=null; baseSwitchCity(city);
  document.querySelectorAll('.ctab').forEach(function(t){t.classList.toggle('on',t.dataset.city===city);});
  document.getElementById('search-events').value='';
  ['day-filter','budget-filter','area-filter','period-filter'].forEach(function(id){document.getElementById(id).value='';});
  document.getElementById('saved-filter').checked=false;document.getElementById('ended-filter').checked=false;
  var meta=typeof META_BANGKOK!=='undefined'?META_BANGKOK:{};
  var editionLabel=city==='bangkok'&&meta.weekend_start?dateLabel({start_date:meta.weekend_start,end_date:meta.weekend_end})+' '+meta.weekend_end.slice(0,4):getCityLabel(city);
  document.getElementById('city-sub').textContent=A.length+' picks · '+editionLabel;
  document.querySelector('.badge').textContent='Weekly · Friday';
  var day=document.getElementById('day-filter');day.innerHTML='<option value="">Any day</option>';
  if(city==='bangkok'&&meta.weekend_start){['Friday','Saturday','Sunday'].forEach(function(name,i){var d=new Date(meta.weekend_start+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+i);day.add(new Option(name,d.toISOString().slice(0,10)));});}
  day.disabled=city!=='bangkok';
  var area=document.getElementById('area-filter');area.innerHTML='<option value="">All neighborhoods</option>';
  Array.from(new Set(A.map(function(a){return a.neighborhood;}).filter(Boolean))).sort().forEach(function(n){area.add(new Option(n,n));});
  area.disabled=area.options.length===1;
  document.getElementById('period-filter').disabled=!A.some(function(a){return a.period&&a.period!=='unknown';});
  document.getElementById('budget-filter').querySelector('[value="500"]').hidden=city!=='bangkok';
  var health=document.getElementById('source-health');
  health.hidden=city!=='bangkok'||!meta.updated_at;
  health.innerHTML=city==='bangkok'&&meta.updated_at?'<summary>Updated '+esc(new Date(meta.updated_at).toLocaleString('en-GB',{timeZone:'Asia/Bangkok'}))+' Bangkok time · Sources</summary>'+meta.sources.map(function(s){return '<div>'+esc(s.name)+': '+(s.status==='ok'?s.count+' valid listings':'unavailable this run; earlier valid listings retained')+'</div>';}).join(''):'';
  applyFilters();
};
document.querySelectorAll('.pill:not([data-f="bac"])').forEach(function(p){p.addEventListener('click',function(){filterState.category=p.dataset.f;applyFilters();});});
document.getElementById('search-events').addEventListener('input',function(e){filterState.query=e.target.value;applyFilters();});
[['day-filter','day'],['budget-filter','budget'],['area-filter','area'],['period-filter','period']].forEach(function(pair){document.getElementById(pair[0]).addEventListener('change',function(e){filterState[pair[1]]=e.target.value;closeDetail();applyFilters();});});
[['saved-filter','saved'],['ended-filter','ended']].forEach(function(pair){document.getElementById(pair[0]).addEventListener('change',function(e){filterState[pair[1]]=e.target.checked;closeDetail();applyFilters();});});
document.querySelectorAll('.mobile-nav button').forEach(function(b){b.onclick=function(){
  document.body.classList.toggle('map-view',b.dataset.view==='map');
  filterState.saved=b.dataset.view==='saved';
  document.getElementById('saved-filter').checked=filterState.saved;
  closeDetail();applyFilters();
};});
document.getElementById('filters-toggle').onclick=function(){
  var open=this.getAttribute('aria-expanded')!=='true';
  this.setAttribute('aria-expanded',open);document.body.classList.toggle('filters-open',open);render();
};
document.getElementById('clear-filters').onclick=function(){switchCity(currentCity);};
var installPrompt=null;
window.addEventListener('beforeinstallprompt',function(e){e.preventDefault();installPrompt=e;});
document.getElementById('install-app').onclick=async function(){
  if(installPrompt){await installPrompt.prompt();installPrompt=null;}
  else document.getElementById('install-help').hidden=false;
};
document.getElementById('dismiss-install').onclick=function(){document.getElementById('install-help').hidden=true;};
window.addEventListener('appinstalled',function(){document.getElementById('install-app').hidden=true;});
// Move labels, never their venue coordinates, to reduce overlap on phones.
var baseRenderMarkers=renderMarkers;
renderMarkers=function(){
  baseRenderMarkers();
  var mobile=window.matchMedia('(max-width:760px)').matches, occupied=[];
  markerLayer.querySelectorAll('.mpin').forEach(function(pin){
    var label=pin.querySelector('.mpin-label');
    label.style.left='';label.style.top='';
    var leader=pin.querySelector('.label-leader');if(leader)leader.remove();
    if(!mobile||pin.classList.contains('hidden'))return;
    var x=parseFloat(pin.style.left), y=parseFloat(pin.style.top), w=label.offsetWidth, h=label.offsetHeight;
    if(x<0||x>wrap.clientWidth||y<0||y>wrap.clientHeight)return;
    var left=x+26+w>wrap.clientWidth?x-26-w:x+26;
    left=Math.max(4,Math.min(left,wrap.clientWidth-w-4));
    var top=Math.max(4,Math.min(y-22,wrap.clientHeight-h-4));
    for(var offset=0;offset<wrap.clientHeight;offset+=12){
      var candidates=[top+offset,top-offset], found=false;
      for(var i=0;i<candidates.length;i++){
        var t=candidates[i];if(t<4||t+h>wrap.clientHeight-4)continue;
        if(!occupied.some(function(r){return left<r.right+4&&left+w>r.left-4&&t<r.bottom+4&&t+h>r.top-4;})){
          top=t;found=true;break;
        }
      }
      if(found)break;
    }
    occupied.push({left:left,right:left+w,top:top,bottom:top+h});
    label.style.left=(left-x+22)+'px';label.style.top=(top-y+22)+'px';
    var dx=(left>x?left:left+w)-x,dy=top+h/2-y;
    leader=document.createElement('span');leader.className='label-leader';
    leader.style.width=Math.hypot(dx,dy)+'px';leader.style.transform='rotate('+Math.atan2(dy,dx)+'rad)';
    pin.insertBefore(leader,pin.firstChild);
  });
};
new ResizeObserver(function(){render();}).observe(wrap);
function openSharedEvent(){var parts=location.hash.slice(1).split('/');if(CITY_CONFIG[parts[0]]){switchCity(parts[0]);var a=A.find(function(e){return String(e.id)===parts[1];});if(a)flyTo(a);}}
window.addEventListener('hashchange',openSharedEvent);
document.querySelectorAll('.pill,.ctab,.zbtn').forEach(function(control){
  control.setAttribute('role','button');control.tabIndex=0;
  control.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();control.click();}});
});
setInterval(function(){applyFilters();},60000);
