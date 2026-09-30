const body=document.querySelector("#ranking-body");
const updated=document.querySelector("#updated");
const gamesGrid=document.querySelector("#games-grid");
const esc=function(value){return String(value??"").replace(/[&<>"']/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]);});};
const confShort=function(c){const map={"Big Ten":"BIG TEN","Big 12":"BIG 12","Mid-American":"MAC","American Athletic":"AAC","Conference USA":"C-USA","Sun Belt":"SUN BELT","Mountain West":"MW","FBS Independents":"IND","Pac-12":"PAC-12","ACC":"ACC","SEC":"SEC"};return map[c]||String(c||"").toUpperCase();};

fetch("data/rankings.json",{cache:"no-store"})
.then(function(response){if(!response.ok)throw new Error("Ranking data unavailable ("+response.status+")");return response.json();})
.then(function(data){
  const rankings=data.rankings||[];
  if(!rankings.length)throw new Error("No rankings were returned.");
  const top=rankings[0];
  document.querySelector("#hero-rank").textContent="#"+top.rank;
  document.querySelector("#hero-team").textContent=top.team;
  document.querySelector("#hero-record").innerHTML=top.wins+"–"+top.losses+" <span>•</span> "+esc(top.conference);
  document.querySelector("#hero-rating").textContent=Number(top.rating).toFixed(3);
  updated.textContent="Updated "+new Date(data.generatedAt).toLocaleString()+" • "+data.teamCount+" teams";
  body.innerHTML=rankings.map(function(t){
    const record=t.wins+"-"+t.losses;
    const last="—";
    const move='<span class="move same">—</span>';
    return "<tr><td>"+t.rank+"</td><td><div class=\"team-name\">"+esc(t.team)+"</div><div class=\"team-sub\">"+esc(t.conference)+"</div></td><td>"+record+"</td><td>"+esc(confShort(t.conference))+"</td><td>"+last+"</td><td>"+move+"</td><td class=\"rating\">"+Number(t.rating).toFixed(3)+"</td></tr>";
  }).join("");
  gamesGrid.innerHTML=[
    {label:"TEAMS",value:String(data.teamCount),meta:"FBS teams ranked"},
    {label:"GAMES",value:String(rankings.reduce(function(sum,t){return sum+(t.gamesPlayed||0);},0)/2),meta:"completed games in feed"},
    {label:"LEADER",value:"#"+top.rank+" "+top.team,meta:top.wins+"-"+top.losses+" record"},
    {label:"DATA",value:"CFBD",meta:"CollegeFootballData.com"}
  ].map(function(x){return '<article class="game"><div class="week">'+esc(x.label)+'</div><div class="matchup">'+esc(x.value)+'</div><div class="game-meta">'+esc(x.meta)+'</div><div class="game-tag">LIVE DATA</div></article>';}).join("");
})
.catch(function(error){
  updated.textContent="Unable to load live rankings";
  body.innerHTML='<tr><td colspan="7">Ranking data could not be loaded. Please refresh the page.</td></tr>';
  gamesGrid.innerHTML='<article class="game"><div class="week">DATA ERROR</div><div class="matchup">'+esc(error.message)+'</div></article>';
});